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
        opts = "; ".join(f"{c['symbol']} ({c['issuer']}, 1 token = {shares(c['multiplier'])})" for c in self.candidates)
        return f"'{self.query}' is {len(self.candidates)} different tokens on BNB Chain: {opts}. Pick one by its symbol."


def _f(x) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


class Guard:
    def __init__(self, client: RwaPort, to_snapshot: ToSnapshot, chain_id: str = "56", list_ttl: float = 600.0,
                 onchain: Optional[SupplyPort] = None):
        self.client, self.to_snapshot, self.chain_id, self.list_ttl = client, to_snapshot, chain_id, list_ttl
        self.onchain = onchain
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

    def compare(self, ticker: str, side: str = "BUY", token_qty: Optional[float] = None,
                usd_amount: Optional[float] = None) -> List[Dict]:
        """The same underlying from every issuer, checked side by side (Ondo, xStocks, bStocks)."""
        q = ticker.strip().lower()
        hits = [t for t in self.tokens() if str(t.get("ticker", "")).lower() == q]
        if not hits:
            self.resolve(ticker)   # raises TickerNotFound with suggestions
            hits = [self.resolve(ticker)]
        return [self.check(t["contractAddress"], side, token_qty, usd_amount=usd_amount) for t in hits]

    def snapshot(self, query: str) -> Snapshot:
        return self._snapshot(self.resolve(query))[0]

    def _snapshot(self, t: Dict):
        dyn = self.client.dynamic(t["contractAddress"], self.chain_id)
        s = self.to_snapshot(dyn, self.client.market_status())
        if _f(t.get("multiplier")):
            s = dataclasses.replace(s, list_multiplier=_f(t.get("multiplier")))
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
        return s, notes

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


def render(s: Snapshot, v: Verdict, side: str, qty: float) -> Dict:
    return {
        "symbol": s.symbol, "ticker": s.ticker, "side": side, "token_qty": qty,
        "verdict": v.level, "risk": v.risk, "reasons": v.reasons, "notes": v.notes,
        "onchain_supply": s.onchain_supply, "order_share_of_supply": v.order_share_of_supply,
        "share_equivalent": v.share_equivalent, "multiplier": s.multiplier,
        "list_multiplier": s.list_multiplier, "multiplier_conflict": s.multiplier_conflict,
        "token_price": s.token_price, "stock_price": s.stock_price,
        "reference_price": v.reference_price, "premium": v.premium,
        "reference_derived": s.reference_derived,
        "next_open_ms": s.next_open_ms,
        "session": s.session, "status": s.status, "reason": s.reason, "market_session": s.market_session,
        "checked_at": int(time.time()),
    }
