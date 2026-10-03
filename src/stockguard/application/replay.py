"""Replay: what a naive agent that treats 1 token as 1 share would get wrong, in dollars, on a real snapshot."""
from typing import Dict, Iterable, List


def naive_share_bot(records: Iterable[Dict], budget_usd: float = 1000.0) -> List[Dict]:
    """A bot wants `budget_usd` of exposure. It reads the per-share stock price and buys budget/price TOKENS.
    Real exposure = tokens * token_price. Error = real - intended."""
    out = []
    for r in records:
        if r.get("error") or not r.get("token_price") or not r.get("multiplier"):
            continue
        m = float(r["multiplier"])
        if abs(m - 1.0) <= 0.05:
            continue
        share_price = r["token_price"] / m
        tokens = budget_usd / share_price
        real = tokens * r["token_price"]
        out.append({"symbol": r["symbol"], "ticker": r["ticker"], "multiplier": round(m, 6),
                    "intended_usd": budget_usd, "real_usd": round(real, 2), "error_usd": round(real - budget_usd, 2)})
    return sorted(out, key=lambda x: -abs(x["error_usd"]))
