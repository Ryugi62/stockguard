"""Use cases: check one trade, scan every BSC tokenized stock. Depends on a client port, not on HTTP."""
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from typing import Dict, Iterable, List, Optional, Protocol

from stockguard.adapters.mapping import to_snapshot
from stockguard.domain.guard import Snapshot, Verdict, check_trade, find_inconsistencies


class RwaPort(Protocol):
    def list_tokens(self, chain_id: str = "56") -> List[Dict]: ...
    def market_status(self) -> Dict: ...
    def dynamic(self, address: str, chain_id: str = "56") -> Dict: ...


class TickerNotFound(KeyError):
    pass


class Guard:
    def __init__(self, client: RwaPort, chain_id: str = "56", list_ttl: float = 600.0):
        self.client, self.chain_id, self.list_ttl = client, chain_id, list_ttl
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
        raise TickerNotFound(query)

    def snapshot(self, query: str) -> Snapshot:
        t = self.resolve(query)
        return to_snapshot(self.client.dynamic(t["contractAddress"], self.chain_id), self.client.market_status())

    def check(self, query: str, side: str = "BUY", token_qty: float = 1.0, premium_threshold: float = 0.01) -> Dict:
        s = self.snapshot(query)
        v = check_trade(s, side.upper(), token_qty, premium_threshold)
        return render(s, v, side.upper(), token_qty)

    def scan(self, workers: int = 8, limit: Optional[int] = None) -> Iterable[Dict]:
        market = self.client.market_status()
        toks = self.tokens()[:limit] if limit else self.tokens()

        def one(t):
            try:
                s = to_snapshot(self.client.dynamic(t["contractAddress"], self.chain_id), market)
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
        "verdict": v.level, "reasons": v.reasons,
        "share_equivalent": v.share_equivalent, "multiplier": s.multiplier,
        "token_price": s.token_price, "stock_price": s.stock_price,
        "reference_price": v.reference_price, "premium": v.premium,
        "reference_derived": s.reference_derived,
        "next_open_ms": s.next_open_ms,
        "session": s.session, "status": s.status, "reason": s.reason, "market_session": s.market_session,
        "checked_at": int(time.time()),
    }
