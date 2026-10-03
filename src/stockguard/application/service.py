"""Use cases: check one trade, scan every BSC tokenized stock. Depends on a client port, not on HTTP."""
import dataclasses
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from typing import Callable, Dict, Iterable, List, Optional, Protocol

from stockguard.domain.guard import Snapshot, Verdict, check_trade, find_inconsistencies

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
        q = query.strip().lower()
        for t in self.tokens():
            if q in (str(t.get("ticker", "")).lower(), str(t.get("symbol", "")).lower(),
                     str(t.get("contractAddress", "")).lower()):
                return t
        import difflib
        names = [str(t.get("ticker", "")) for t in self.tokens()]
        raise TickerNotFound(query, difflib.get_close_matches(query.upper(), names, n=3, cutoff=0.6))

    def snapshot(self, query: str) -> Snapshot:
        return self._snapshot(self.resolve(query))[0]

    def _snapshot(self, t: Dict):
        dyn = self.client.dynamic(t["contractAddress"], self.chain_id)
        s = self.to_snapshot(dyn, self.client.market_status())
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
            if usd_amount <= 0 or not s.token_price:
                raise ValueError("usd_amount must be positive and a token price must exist")
            token_qty = usd_amount / s.token_price
        token_qty = 1.0 if token_qty is None else float(token_qty)
        v = check_trade(s, side.upper(), token_qty, premium_threshold)
        out = render(s, v, side.upper(), token_qty)
        out["contract"] = t["contractAddress"]
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
        base = "https://bin.bnbstatic.com"
        return {"name": m.get("name"), "company": (m.get("companyInfo") or {}).get("companyName"),
                "attestation_daily": base + m["dailyAttestationReports"] if m.get("dailyAttestationReports") else None,
                "attestation_monthly": base + m["monthlyAttestationReports"] if m.get("monthlyAttestationReports") else None}

    def scan(self, workers: int = 8, limit: Optional[int] = None) -> Iterable[Dict]:
        market = self.client.market_status()
        toks = self.tokens()[:limit] if limit else self.tokens()

        def one(t):
            try:
                s = self.to_snapshot(self.client.dynamic(t["contractAddress"], self.chain_id), market)
                v = check_trade(s, "BUY", 1.0)
                rec = render(s, v, "BUY", 1.0)
                rec["inconsistencies"] = find_inconsistencies(s)
                rec["list_multiplier"] = float(t.get("multiplier") or 0)
                rec["contract"] = t.get("contractAddress")
                rec["list_symbol"] = t.get("symbol")
                if s.symbol in ("?", "") or s.symbol != t.get("symbol"):
                    rec["inconsistencies"].append(
                        f"{t.get('symbol')}: dynamic endpoint returned symbol {s.symbol!r} (list says {t.get('symbol')!r})")
                if abs(rec["list_multiplier"] - s.multiplier) > 1e-9:
                    rec["inconsistencies"].append(
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
        "verdict": v.level, "risk": v.risk, "reasons": v.reasons,
        "onchain_supply": s.onchain_supply, "order_share_of_supply": v.order_share_of_supply,
        "share_equivalent": v.share_equivalent, "multiplier": s.multiplier,
        "token_price": s.token_price, "stock_price": s.stock_price,
        "reference_price": v.reference_price, "premium": v.premium,
        "reference_derived": s.reference_derived,
        "next_open_ms": s.next_open_ms,
        "session": s.session, "status": s.status, "reason": s.reason, "market_session": s.market_session,
        "checked_at": int(time.time()),
    }
