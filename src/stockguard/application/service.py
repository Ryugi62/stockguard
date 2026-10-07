"""Use cases: check one trade, scan every BSC tokenized stock. Depends on a client port, not on HTTP."""
import dataclasses
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from typing import Callable, Dict, Iterable, List, Optional, Protocol

from stockguard.domain.guard import Snapshot, Verdict, check_trade, find_inconsistencies
from stockguard.domain.issuers import issuer_name

ToSnapshot = Callable[[Dict, Optional[Dict]], Snapshot]


class RwaPort(Protocol):
    def list_tokens(self, chain_id: str = "56") -> List[Dict]: ...
    def market_status(self) -> Dict: ...
    def dynamic(self, address: str, chain_id: str = "56") -> Dict: ...
    def meta(self, address: str, chain_id: str = "56") -> Dict: ...


class SupplyPort(Protocol):
    def total_supply(self, token: str) -> Optional[float]: ...


class TickerNotFound(KeyError):
    def __init__(self, query: str, suggestions: Optional[List[str]] = None):
        super().__init__(query)
        self.query, self.suggestions = query, suggestions or []


class AmbiguousTicker(LookupError):
    """A bare ticker matches tokens from more than one issuer; the caller must choose (never default to one)."""
    def __init__(self, query: str, candidates: List[Dict]):
        super().__init__(query)
        self.query, self.candidates = query, candidates

    def message(self) -> str:
        def shares(m):
            return "1 share" if abs(m - 1) <= 0.05 else f"{m:.4g} shares"
        opts = "; ".join(f"{c['symbol']} ({c['issuer']}, 1 token = {c.get('shares_label') or shares(c['multiplier'])})"
                         for c in self.candidates)
        return f"'{self.query}' is {len(self.candidates)} different tokens on BNB Chain: {opts}. Pick one by its symbol."


def _f(x) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def last_trade_age_hours(klines: List, now_s: float) -> Optional[float]:
    """Hours since the close of the last K-line candle, if the candles are trade-derived (some volume > 0).
    Ondo candles always carry volume 0 (F7), so they say nothing about the last trade -> None."""
    traded = [k for k in klines or [] if isinstance(k, (list, tuple)) and len(k) > 6 and (_f(k[5]) or 0) > 0]
    if not traded:
        return None
    return max(0.0, (now_s * 1000 - float(traded[-1][6])) / 3.6e6)


class Guard:
    def __init__(self, client: RwaPort, to_snapshot: ToSnapshot, chain_id: str = "56", list_ttl: float = 600.0,
                 onchain: Optional[SupplyPort] = None, clock: Callable[[], float] = time.time):
        self.client, self.to_snapshot, self.chain_id, self.list_ttl = client, to_snapshot, chain_id, list_ttl
        self.onchain = onchain
        self.clock = clock
        self._tokens: Optional[List[Dict]] = None
        self._tokens_at = 0.0

    def tokens(self) -> List[Dict]:
        if self._tokens is None or time.time() - self._tokens_at > self.list_ttl:
            self._tokens = self.client.list_tokens(self.chain_id)
            self._tokens_at = time.time()
        return self._tokens

    def resolve(self, query: str) -> Dict:
        """Exact token symbol or contract first; a bare ticker only if exactly one issuer has it."""
        q = query.strip().lower()
        for t in self.tokens():
            if q in (str(t.get("symbol", "")).lower(), str(t.get("contractAddress", "")).lower()):
                return t
        hits = [t for t in self.tokens() if str(t.get("ticker", "")).lower() == q]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise AmbiguousTicker(query, [self.candidate(t) for t in hits])
        import difflib
        names = sorted({str(t.get("ticker", "")) for t in self.tokens()} | {str(t.get("symbol", "")) for t in self.tokens()})
        raise TickerNotFound(query, difflib.get_close_matches(query.strip().upper(), names, n=3, cutoff=0.6))

    @staticmethod
    def candidate(t: Dict) -> Dict:
        return {"symbol": t.get("symbol"), "ticker": t.get("ticker"), "issuer": issuer_name(t.get("type")),
                "multiplier": _f(t.get("multiplier")) or 1.0, "contract": t.get("contractAddress")}

    def tokens_candidates(self, ticker: str) -> List[Dict]:
        q = ticker.strip().lower()
        return [self.candidate(t) for t in self.tokens() if str(t.get("ticker", "")).lower() == q]

    def describe(self, candidates: List[Dict]) -> List[Dict]:
        """Add the price-feed multiplier and one consistent label ("1 share", "10 shares", "1 or 10 shares?")."""
        out = []
        for c in candidates:
            c = dict(c)
            try:
                s, _ = self._snapshot({"contractAddress": c["contract"], "multiplier": c["multiplier"]})
                c["feed_multiplier"], c["multiplier_conflict"] = s.multiplier, s.multiplier_conflict
            except Exception:
                c["feed_multiplier"], c["multiplier_conflict"] = None, False
            c["shares_label"] = shares_label(c["multiplier"], c.get("feed_multiplier"), c["multiplier_conflict"])
            out.append(c)
        return out

    def compare(self, ticker: str, side: str = "BUY", token_qty: Optional[float] = None,
                usd_amount: Optional[float] = None) -> List[Dict]:
        """The same underlying from every issuer, checked side by side (Ondo, xStocks, bStocks)."""
        q = ticker.strip().lower()
        hits = [t for t in self.tokens() if str(t.get("ticker", "")).lower() == q]
        if not hits:
            self.resolve(ticker)   # raises TickerNotFound with suggestions
            hits = [self.resolve(ticker)]
        rows = [self.check(t["contractAddress"], side, token_qty, usd_amount=usd_amount) for t in hits]
        for r in rows:   # same share, three prices: the per-share view also shows which multiplier the price supports
            m = r["share_equivalent"] / r["token_qty"] if r.get("token_qty") else r["multiplier"]
            r["per_share_price"] = (r["token_price"] / m) if r.get("token_price") and m else None
        for r in rows:   # a price from a trade days ago is not comparable with live ones (F16)
            age = r.get("last_trade_age_h")
            r["stale_price"] = bool(age is not None and age > 72)
        priced = [r["per_share_price"] for r in rows if r["per_share_price"] and not r["stale_price"]]
        lo = min(priced) if priced else None
        for r in rows:
            r["per_share_spread"] = (r["per_share_price"] / lo - 1) if lo and r["per_share_price"] and not r["stale_price"] \
                else None
        return rows

    def snapshot(self, query: str) -> Snapshot:
        return self._snapshot(self.resolve(query))[0]

    def _snapshot(self, t: Dict):
        dyn = self.client.dynamic(t["contractAddress"], self.chain_id)
        s = self.to_snapshot(dyn, self.client.market_status())
        if _f(t.get("multiplier")):
            s = dataclasses.replace(s, list_multiplier=_f(t.get("multiplier")))
        s = dataclasses.replace(s, api_supply=_f((dyn.get("tokenInfo") or {}).get("circulatingSupply")))
        notes = []
        if self.onchain is not None:
            try:
                supply = self.onchain.total_supply(t["contractAddress"])
                s = dataclasses.replace(s, onchain_supply=supply)
                api = float((dyn.get("tokenInfo") or {}).get("circulatingSupply") or 0)
                if supply and api and abs(api - supply) / supply > 0.001:
                    notes.append(f"{s.symbol}: API circulatingSupply {api:,.4f} != on-chain totalSupply {supply:,.4f}")
            except Exception as e:  # chain read is a bonus; never fail the check on it
                notes.append(f"{s.symbol}: on-chain read failed ({type(e).__name__})")
        if s.stock_price is None and s.token_price:      # bStocks carry no stock quote (F12): the feed is shared
            s = self._borrow_reference(t, s, notes)        # across issuers (85/86 tickers identical, 2026-10-07)
        try:                        # Market API K-line: when did this token last trade on-chain? (F16)
            kl = self.client.kline(t["contractAddress"], "1d", 10, self.chain_id) if hasattr(self.client, "kline") else []
            s = dataclasses.replace(s, last_trade_age_h=last_trade_age_hours(kl, self.clock()))
        except Exception as e:      # a bonus signal; never fail the check on it
            notes.append(f"{s.symbol}: K-line read failed ({type(e).__name__})")
        return s, notes

    def _borrow_reference(self, t: Dict, s: Snapshot, notes: List[str]) -> Snapshot:
        ticker = str(t.get("ticker") or "").lower()
        for other in self.tokens():
            if other is t or str(other.get("ticker") or "").lower() != ticker or \
                    other.get("contractAddress", "").lower() == t.get("contractAddress", "").lower():
                continue
            try:
                price = _f(((self.client.dynamic(other["contractAddress"], self.chain_id) or {}).get("stockInfo") or {})
                           .get("price"))
            except Exception:
                continue
            if price:
                notes.append(f"{s.symbol}: no stock quote of its own; using the {t.get('ticker')} quote from "
                             f"{other.get('symbol')} (the stock feed is shared across issuers)")
                return dataclasses.replace(s, stock_price=price, reference_source=other.get("symbol"))
        return s

    def check(self, query: str, side: str = "BUY", token_qty: Optional[float] = None, premium_threshold: float = 0.01,
              usd_amount: Optional[float] = None) -> Dict:
        """Size by tokens, or by dollars (usd_amount) — dollars are converted with the per-TOKEN price."""
        t = self.resolve(query)
        s, notes = self._snapshot(t)
        if usd_amount is not None:
            if usd_amount <= 0:
                raise ValueError("usd_amount must be positive")
            if s.token_price:
                token_qty = usd_amount / s.token_price   # no price -> the verdict BLOCKs; quantity stays a placeholder
        token_qty = 1.0 if token_qty is None else float(token_qty)
        v = check_trade(s, side.upper(), token_qty, premium_threshold, sized_in_usd=usd_amount is not None)
        out = render(s, v, side.upper(), token_qty)
        out["contract"] = t["contractAddress"]
        out["issuer"] = issuer_name(t.get("type"))
        out["usd_amount"] = round(token_qty * s.token_price, 2)
        out["data_notes"] = notes + find_inconsistencies(s)
        out.update(self._issuer_info(t["contractAddress"]))
        return out

    def _issuer_info(self, address: str) -> Dict:
        """Company name and the issuer's attestation reports (proof the token is backed). Optional: never fails a check."""
        try:
            m = self.client.meta(address, self.chain_id) or {}
        except Exception:
            return {}
        def url(p):
            if not p:
                return None
            return p if str(p).startswith("http") else "https://bin.bnbstatic.com" + p   # bStocks send absolute URLs
        return {"name": m.get("name"), "company": (m.get("companyInfo") or {}).get("companyName"),
                "attestation_daily": url(m.get("dailyAttestationReports")),
                "attestation_monthly": url(m.get("monthlyAttestationReports"))}

    def scan(self, workers: int = 8, limit: Optional[int] = None) -> Iterable[Dict]:
        market = self.client.market_status()
        toks = self.tokens()[:limit] if limit else self.tokens()

        def one(t):
            try:
                s = self.to_snapshot(self.client.dynamic(t["contractAddress"], self.chain_id), market)
                if _f(t.get("multiplier")):
                    s = dataclasses.replace(s, list_multiplier=_f(t.get("multiplier")))
                v = check_trade(s, "BUY", 1.0)
                rec = render(s, v, "BUY", 1.0)
                rec["inconsistencies"] = find_inconsistencies(s)
                rec["list_multiplier"] = float(t.get("multiplier") or 0)
                rec["contract"] = t.get("contractAddress")
                rec["list_symbol"] = t.get("symbol")
                rec["issuer"] = issuer_name(t.get("type"))
                if s.symbol in ("?", "") or s.symbol != t.get("symbol"):
                    rec["inconsistencies"].append(
                        f"{t.get('symbol')}: dynamic endpoint returned symbol {s.symbol!r} (list says {t.get('symbol')!r})")
                if abs(rec["list_multiplier"] - s.multiplier) > 1e-9 and not s.multiplier_conflict:
                    rec["inconsistencies"].append(   # tiny drift; >1% is reported by find_inconsistencies
                        f"{s.symbol}: list multiplier {rec['list_multiplier']} != dynamic sharesMultiplier {s.multiplier}")
                return rec
            except Exception as e:  # keep scanning; record the failure as data
                return {"symbol": t.get("symbol"), "ticker": t.get("ticker"), "error": str(e)[:300]}

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(one, t) for t in toks]
            for f in as_completed(futs):
                yield f.result()


def shares_label(list_m: float, feed_m: Optional[float] = None, conflict: bool = False) -> str:
    def one(m):
        return "1 share" if abs(m - 1) <= 0.05 else f"{m:.4g} shares"
    if conflict and feed_m:
        return f"{list_m:.4g} or {feed_m:.4g} shares? (the API disagrees)"
    return one(feed_m if feed_m else list_m)


def render(s: Snapshot, v: Verdict, side: str, qty: float) -> Dict:
    return {
        "symbol": s.symbol, "ticker": s.ticker, "side": side, "token_qty": qty,
        "verdict": v.level, "risk": v.risk, "reasons": v.reasons, "notes": v.notes,
        "onchain_supply": s.onchain_supply, "order_share_of_supply": v.order_share_of_supply,
        "share_equivalent": v.share_equivalent, "multiplier": s.multiplier,
        "list_multiplier": s.list_multiplier, "multiplier_conflict": s.multiplier_conflict,
        "shares_label": shares_label(s.list_multiplier or s.multiplier, s.multiplier, s.multiplier_conflict),
        "api_supply": s.api_supply, "supply_mismatch": s.supply_mismatch,
        "token_price": s.token_price, "stock_price": s.stock_price,
        "reference_price": v.reference_price, "premium": v.premium,
        "reference_derived": s.reference_derived,
        "next_open_ms": s.next_open_ms, "last_trade_age_h": s.last_trade_age_h,
        "reference_source": s.reference_source, "effective_multiplier": s.effective_multiplier,
        "session": s.session, "status": s.status, "reason": s.reason, "market_session": s.market_session,
        "checked_at": int(time.time()),
    }
