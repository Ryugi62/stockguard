"""UC-4: gate an Agentic Wallet order before it is placed. Never signs, never calls the wallet by itself."""
from typing import Dict, Optional, Protocol

from stockguard.application.service import AmbiguousTicker, Guard, TickerNotFound
from stockguard.domain.guard import Verdict
from stockguard.domain.wallet_gate import (ASK, CONFIRM, REFUSE, AuditResult, WalletSettings, decide,
                                           per_token_trigger)

PAY_TOKENS = ("USDT", "USDC", "USD1", "U", "BNB")   # BSC payment tokens listed in the Agentic Wallet skill
DOLLAR_TOKENS = ("USDT", "USDC", "USD1", "U")


class AuditPort(Protocol):
    def audit(self, address: str) -> AuditResult: ...


def _refuse(query: str, side: str, usd: float, reason: str) -> Dict:
    return {"action": REFUSE, "query": query, "side": side, "requested_usd": usd, "approved_usd": 0.0,
            "reasons": [reason], "notes": [], "confirmation_required": False}


def gate_swap(guard: Guard, query: str, usd_amount: float, side: str = "BUY", pay_with: str = "USDT",
              settings: Optional[WalletSettings] = None, auditor: Optional[AuditPort] = None,
              slippage: Optional[float] = None, trigger_share_price: Optional[float] = None,
              pay_price: Optional[float] = None, today: Optional[str] = None,
              token_qty: Optional[float] = None) -> Dict:
    """Size by dollars (`usd_amount`) or, for a SELL, by tokens (`token_qty`)."""
    side, pay_with = side.upper(), pay_with.upper()
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")
    if pay_with not in PAY_TOKENS:
        raise ValueError(f"pay_with must be one of {', '.join(PAY_TOKENS)}")
    if token_qty is not None and (side != "SELL" or token_qty <= 0):
        raise ValueError("token_qty sizing is for SELL orders and must be positive")
    if token_qty is None and (not usd_amount or usd_amount <= 0):
        raise ValueError("usd_amount must be positive")
    if slippage is not None and not (0 < slippage <= 100):
        raise ValueError("slippage is a percentage between 0 and 100")
    if trigger_share_price is not None and pay_with not in ("USDT", "USDC", "BNB"):
        raise ValueError("limit orders only take USDT, USDC or BNB (references/limit-order.md)")
    if pay_with == "BNB" and side == "BUY" and not (pay_price and pay_price > 0):
        raise ValueError("paying with BNB needs the BNB price in USD (pay_price) — `baw wallet balance` shows it")
    try:
        t = guard.resolve(query)
    except AmbiguousTicker as e:
        try:
            e.candidates = guard.describe(e.candidates)
        except Exception:
            pass
        return {"action": ASK, "query": query, "side": side, "requested_usd": usd_amount, "approved_usd": 0.0,
                "choices": e.candidates, "confirmation_required": True, "notes": [],
                "reasons": [e.message() + " Ask the user which one — do not pick an issuer for them."]}
    except TickerNotFound as e:
        if query.strip().lower().startswith("0x"):
            return _refuse(query, side, usd_amount, f"Contract {query} is not in the RWA token list — never trade an "
                                                    f"address that did not come from the official list")
        if getattr(e, "reason", None):
            return _refuse(query, side, usd_amount, e.reason)
        hint = f" Did you mean {', '.join(e.suggestions)}?" if e.suggestions else ""
        return _refuse(query, side, usd_amount, f"No tokenized stock on BNB Chain matches '{query}'.{hint}")
    except Exception as e:  # token list unreachable: no fresh check, no trade
        return _refuse(query, side, usd_amount, f"Market data unavailable ({type(e).__name__}) — fail-closed: StockGuard refuses "
                                                f"to gate without fresh data. Tell the user.")
    try:
        if token_qty is not None:
            r = guard.check(t["contractAddress"], side, token_qty)
            usd_amount = r["token_qty"] * (r["token_price"] or 0.0)
            if usd_amount <= 0:
                return _refuse(query, side, 0.0, "No token price — the sale can't be valued")
        else:
            r = guard.check(t["contractAddress"], side, usd_amount=usd_amount)
    except Exception as e:
        return _refuse(query, side, usd_amount, f"Market data unavailable ({type(e).__name__}) — fail-closed: StockGuard refuses "
                                                f"to gate without fresh data. Tell the user.")
    # security.md §1: the audit target is --toToken. A SELL's target is a trusted stablecoin/BNB -> skip (step 1).
    audit = auditor.audit(t["contractAddress"]) if auditor is not None and side == "BUY" else None
    v = Verdict(r["verdict"], list(r["reasons"]), risk=r["risk"], notes=list(r["notes"]))
    d = decide(v, usd_amount, settings, audit=audit)
    notes = list(d.notes)
    if side == "SELL":
        notes.append(f"Token audit not needed: the target is {pay_with}, a trusted token (security.md §1, step 1).")
    elif auditor is None:
        notes.append("No token audit was run by this caller.")
    if settings is None:
        notes.append("Wallet limits were not checked — pass the output of `baw wallet settings --json`.")
    elif today and settings.quota_date and settings.quota_date != today:
        notes.append(f"The wallet settings are from {settings.quota_date}, not today ({today}) — quotaLeft may be "
                     f"stale; read them again.")
    if slippage is None:          # same cap as `trade`: an agent copying these commands never gets "auto"
        slippage = 1.0
        notes.append('No slippage given: capped at 1% (instead of the wallet\'s "auto" default) — tell the user; '
                     'pass --slippage to change it.')
    trigger = None
    action = d.action
    reasons = list(d.reasons)
    if trigger_share_price is not None and action not in (REFUSE,):
        try:
            trigger = per_token_trigger(trigger_share_price, r["multiplier"], r.get("multiplier_conflict", False))
            px = r["token_price"] or 0.0
            trigger = float(f"{trigger:.6g}")          # the exact value the command will carry
            if px and ((side == "BUY" and trigger >= px) or (side == "SELL" and trigger <= px)):
                action = CONFIRM if action != REFUSE else action
                reasons = reasons + [f"Limit trigger ${trigger:,.2f} per token is already met (the token trades at "
                                     f"${px:,.2f}) — the order would fire immediately, like a market order"]
            if str(r["symbol"]).endswith("on"):
                notes.append("Heads-up to show the user: the wallet skill quotes an `Ondo-related tokens cannot be "
                             "traded` error for limit orders — this Ondo limit order may be rejected; then stop, don't "
                             "switch to a market order.")
            notes.append(f"Limit order: ${trigger_share_price:,.2f} per {r['ticker']} share = ${trigger:,.2f} per "
                         f"{r['symbol']} token (1 token = {r['multiplier']:.4g} shares). If the wallet rejects the limit "
                         f"order, stop and ask the user — do not fall back to a market order (skill, step 7).")
        except ValueError as e:
            action, reasons = REFUSE, reasons + [f"Limit order refused: {e}"]
    price = r["token_price"] or 0.0
    approved = d.approved_usd if action != REFUSE else 0.0
    if pay_with == "BNB":
        notes.append(f"Paying with BNB at ${pay_price:,.2f} per BNB (BNB is not a dollar token; the quote has the "
                     f"final amount)." if pay_price else "Selling into BNB.")
    qty_at = trigger if (trigger and side == "SELL" and token_qty is None) else price   # a limit SELL fills at the trigger
    return {"action": action, "query": query, "side": side, "pay_with": pay_with,
            "symbol": r["symbol"], "ticker": r["ticker"], "issuer": r.get("issuer"), "contract": r["contract"],
            "requested_usd": d.requested_usd, "approved_usd": approved,
            "approved_token_qty": (token_qty if token_qty is not None and approved == d.requested_usd
                                   else (approved / qty_at) if qty_at else 0.0),
            "pay_qty": (approved / pay_price) if pay_with == "BNB" and pay_price else approved,
            "token_price": price, "multiplier": r["multiplier"], "shares_label": r.get("shares_label"),
            # the multiplier `baw` itself applies (its RWA list = scaleui/list, identical to list/ai for all 675 BSC
            # tokens on 2026-10-07): market-order SELL quantities, quotes and balances are in SHARES in baw 1.10.0
            "wallet_multiplier": r.get("list_multiplier") or r["multiplier"],
            "verdict": r["verdict"], "risk": r["risk"], "reasons": reasons, "notes": notes,
            "confirmation_required": d.confirmation_required or action == CONFIRM,
            "slippage": slippage, "trigger_token_price": trigger,
            "audit": None if audit is None else {"available": audit.available, "risk_level": audit.risk_level,
                                                 "hits": list(audit.hits), "error": audit.error},
            "data_notes": r.get("data_notes", [])}
