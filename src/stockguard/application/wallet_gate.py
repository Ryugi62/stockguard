"""UC-4: gate an Agentic Wallet market-order swap before it is placed. Never signs, never calls the wallet."""
from typing import Dict, Optional

from stockguard.application.service import AmbiguousTicker, Guard, TickerNotFound
from stockguard.domain.guard import Verdict
from stockguard.domain.wallet_gate import ASK, REFUSE, WalletSettings, decide

STABLES = ("USDT", "USDC", "USD1", "U")   # payment tokens listed for BSC in the Agentic Wallet skill


def _refuse(query: str, side: str, usd: float, reason: str) -> Dict:
    return {"action": REFUSE, "query": query, "side": side, "requested_usd": usd, "approved_usd": 0.0,
            "reasons": [reason], "notes": [], "confirmation_required": False}


def gate_swap(guard: Guard, query: str, usd_amount: float, side: str = "BUY", pay_with: str = "USDT",
              settings: Optional[WalletSettings] = None) -> Dict:
    side, pay_with = side.upper(), pay_with.upper()
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")
    if pay_with not in STABLES:
        raise ValueError(f"pay_with must be one of {', '.join(STABLES)}")
    if not usd_amount or usd_amount <= 0:
        raise ValueError("usd_amount must be positive")
    try:
        t = guard.resolve(query)
    except AmbiguousTicker as e:
        return {"action": ASK, "query": query, "side": side, "requested_usd": usd_amount, "approved_usd": 0.0,
                "choices": e.candidates, "confirmation_required": True, "notes": [],
                "reasons": [e.message() + " Ask the user which one — do not pick an issuer for them."]}
    except TickerNotFound as e:
        if query.strip().lower().startswith("0x"):
            return _refuse(query, side, usd_amount, f"Contract {query} is not in the RWA token list — never trade an "
                                                    f"address that did not come from the official list")
        hint = f" Did you mean {', '.join(e.suggestions)}?" if e.suggestions else ""
        return _refuse(query, side, usd_amount, f"No tokenized stock on BNB Chain matches '{query}'.{hint}")
    try:
        r = guard.check(t["contractAddress"], side, usd_amount=usd_amount)
    except Exception as e:  # fail-closed: no fresh check, no trade
        return _refuse(query, side, usd_amount, f"Market data unavailable ({type(e).__name__}) — fail-closed: no trade "
                                                f"without a fresh check. Tell the user and get their acknowledgment.")
    v = Verdict(r["verdict"], list(r["reasons"]), risk=r["risk"], notes=list(r["notes"]))
    d = decide(v, usd_amount, settings)
    notes = d.notes + ([] if settings else ["Wallet limits were not checked — pass the wallet's security settings "
                                            "(daily quota, allowed-token list) to include them."])
    price = r["token_price"] or 0.0
    return {"action": d.action, "query": query, "side": side, "pay_with": pay_with,
            "symbol": r["symbol"], "ticker": r["ticker"], "issuer": r.get("issuer"), "contract": r["contract"],
            "requested_usd": d.requested_usd, "approved_usd": d.approved_usd,
            "approved_token_qty": (d.approved_usd / price) if price else 0.0,
            "token_price": price, "multiplier": r["multiplier"], "verdict": r["verdict"], "risk": r["risk"],
            "reasons": d.reasons, "notes": notes, "confirmation_required": d.confirmation_required,
            "data_notes": r.get("data_notes", [])}
