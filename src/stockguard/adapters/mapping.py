"""Raw RWA JSON -> domain Snapshot. Translation only; the rules live in domain/guard.py."""
from typing import Dict, Optional

from stockguard.domain.guard import Snapshot

DERIVED_TOLERANCE = 1e-6


def _f(x) -> Optional[float]:
    try:
        return None if x is None or x == "" else float(x)
    except (TypeError, ValueError):
        return None


def to_snapshot(dynamic: Dict, market: Optional[Dict] = None) -> Snapshot:
    tok = dynamic.get("tokenInfo") or {}
    stk = dynamic.get("stockInfo") or {}
    st = dynamic.get("statusInfo") or {}
    token_price = _f(tok.get("price")) or 0.0
    stock_price = _f(stk.get("price"))
    mult = _f(tok.get("sharesMultiplier")) or 1.0
    derived = False
    if stock_price and token_price:
        # Outside US hours the API fills stockInfo.price with tokenPrice / multiplier (observed 2026-10-03).
        derived = abs(stock_price * mult - token_price) <= DERIVED_TOLERANCE * max(1.0, token_price)
    reason_code = st.get("reasonCode") or "UNKNOWN"
    return Snapshot(
        symbol=dynamic.get("symbol") or "?",
        ticker=dynamic.get("ticker") or "?",
        token_price=token_price,
        stock_price=stock_price,
        multiplier=mult,
        session=st.get("marketStatus") or "",
        status=reason_code,
        reason=st.get("reasonMsg"),
        market_session=(market or {}).get("marketStatus"),
        reference_derived=derived,
        next_open_ms=int(st["nextOpenTime"]) if st.get("nextOpenTime") else None,
    )
