"""UC-6 guarded trade: the gate drives Agentic Wallet end to end, and the wallet signs under its own limits.

preflight (`wallet status`, `wallet settings`) -> gate -> `market-order quote` re-checked against the token price
-> explicit yes from the user -> `market-order swap` -> poll `market-order list` until FINISHED or FAILED.
A limit order is placed only as a limit order; if the wallet rejects it, we stop (skill step 7).
"""
from typing import Callable, Dict, List, Optional, Protocol, Tuple

from stockguard.application.service import Guard
from stockguard.application.wallet_gate import gate_swap
from stockguard.domain.wallet_gate import ASK, REFUSE, WalletSettings, check_quote, check_quote_size


class WalletPort(Protocol):
    def status(self) -> Optional[str]: ...
    def settings(self) -> Optional[WalletSettings]: ...
    def price(self, symbol: str) -> Optional[float]: ...
    def balance(self, contract: str) -> float: ...
    def commands(self, gate: Dict) -> List[str]: ...
    def quote(self, gate: Dict) -> Tuple[float, float]: ...
    def swap(self, gate: Dict) -> Optional[str]: ...
    def order_status(self, order_id: str) -> Tuple[str, Optional[str]]: ...
    def place_limit(self, gate: Dict) -> Tuple[bool, Optional[str], Dict]: ...
    def pay_balance(self, symbol: str) -> Optional[float]: ...
    def cli_ok(self, required: str = ...) -> Optional[bool]: ...


def _quote_in_tokens_and_usd(gate, frm, to, pay_price):
    """baw 1.10.0 quotes tokenized stocks in SHARES (BUY toCoinAmount, SELL fromCoinAmount) — convert back to token
    units with the multiplier baw applies; a BNB leg is converted to dollars."""
    m = gate.get("wallet_multiplier") or 1.0
    if gate["side"] == "BUY":
        to = to / m
    else:
        frm = frm / m
    if gate["pay_with"] == "BNB":
        if gate["side"] == "BUY":
            frm = frm * (pay_price or 0)
        else:
            to = to * (pay_price or 0)
    return frm, to


def _size_problem(gate, frm):
    expected = gate["approved_usd"] if gate["side"] == "BUY" else gate["approved_token_qty"]
    return check_quote_size(gate["side"], frm, expected)


def apply_wallet_quote(gate: Dict, raw_quote: Dict, pay_price: Optional[float] = None) -> Dict:
    """`gate --quote-json`: the same wallet-quote check `trade` runs, for an agent that runs the commands itself.
    > 5% worse -> REFUSE (no commands); > 1% worse -> at least CONFIRM."""
    from stockguard.adapters.agentic_wallet import parse_quote      # parsing only; no wallet call here
    out = dict(gate, reasons=list(gate.get("reasons", [])), notes=list(gate.get("notes", [])))
    if out["action"] in (REFUSE, ASK):
        return out
    try:
        frm, to = parse_quote(raw_quote)
    except (KeyError, TypeError, ValueError) as e:
        out.update(action=REFUSE, baw_commands=[], approved_usd=0.0)
        out["reasons"].append(f"The wallet quote can't be read ({e}) — get a fresh one before swapping")
        return out
    frm, to = _quote_in_tokens_and_usd(out, frm, to, pay_price)
    size = _size_problem(out, frm)
    if size:
        out.update(action=REFUSE, baw_commands=[], approved_usd=0.0)
        out["reasons"].append(size)
        return out
    q = check_quote(out["side"], frm, to, out["token_price"])
    out["quote_check"] = {"level": q.level, "reason": q.reason, "from": frm, "to": to}
    if q.level == REFUSE:
        out.update(action=REFUSE, baw_commands=[], approved_usd=0.0)
        out["reasons"].append(q.reason)
    elif q.level == "CONFIRM":
        out["action"] = "CONFIRM"
        out["confirmation_required"] = True
        out["reasons"].append(q.reason)
    return out


def run_guarded_trade(guard: Guard, wallet: WalletPort, ticker: str, usd_amount: float, side: str = "BUY",
                      pay_with: str = "USDT", slippage: Optional[float] = None, auditor=None,
                      token_qty: Optional[float] = None,
                      trigger_share_price: Optional[float] = None, confirm: Callable[[Dict], bool] = lambda s: False,
                      sleep: Optional[Callable[[float], None]] = None, today: Optional[str] = None,
                      clock: Optional[Callable[[], float]] = None,
                      max_polls: int = 30) -> Dict:
    import time as _time
    sleep = sleep or _time.sleep
    clock = clock or _time.time
    st = wallet.status()
    if st != "CONNECTED":
        if st and "BAW_NOT_FOUND" in str(st):
            return {"stage": "preflight", "result": str(st).split("BAW_NOT_FOUND: ")[-1].rstrip(")")}
        return {"stage": "preflight", "result": f"Agentic Wallet is not ready (status {st}) — run `baw auth signin`"}
    cli = wallet.cli_ok("1.10.0") if hasattr(wallet, "cli_ok") else None
    if cli is False:
        return {"stage": "preflight", "result": "baw CLI is older than 1.10.0 (the skill's requiredCliVersion) — upgrade it"}
    newer = wallet.skill_update("1.12.0") if hasattr(wallet, "skill_update") else None
    settings = wallet.settings()
    pay_price = wallet.price("BNB") if pay_with.upper() == "BNB" else None   # BUY sizing and SELL quote check
    if pay_with.upper() == "BNB" and not pay_price:
        return {"stage": "preflight", "result": "The wallet shows no BNB price (it lists only tokens you hold) — "
                                                "pay with USDT, or hold some BNB first"}
    gate = gate_swap(guard, ticker, usd_amount, side=side, pay_with=pay_with, settings=settings, auditor=auditor,
                     slippage=slippage, trigger_share_price=trigger_share_price, pay_price=pay_price, today=today,
                     token_qty=token_qty)
    if newer:
        gate["notes"].append(f"A newer binance-agentic-wallet skill ({newer}) is available; StockGuard was checked "
                             f"against 1.12.0.")
    if settings is not None and settings.session_expires:
        gate["notes"].append(f"Wallet session expires at {settings.session_expires}.")
    gate["baw_commands"] = wallet.commands(gate)
    if gate["action"] in (REFUSE, ASK) or not gate["baw_commands"]:
        return {"stage": "gate", "gate": gate}
    if gate["side"] == "BUY" and hasattr(wallet, "pay_balance"):
        have = wallet.pay_balance(gate["pay_with"])
        need = gate["pay_qty"]
        if have is not None and have + 1e-9 < need:
            return {"stage": "balance", "gate": gate, "result": f"Wallet holds {have:g} {gate['pay_with']}, "
                                                                 f"less than the {need:g} this order needs"}
    if gate["side"] == "SELL":   # `baw wallet balance --json` reports a tokenized stock in SHARES (rawBalance is dropped)
        try:
            held = wallet.balance(gate["contract"]) / (gate.get("wallet_multiplier") or 1.0)
        except ValueError as e:
            return {"stage": "balance", "gate": gate, "result": f"Could not read the wallet balance — {e}"}
        if held + 1e-12 < gate["approved_token_qty"]:
            return {"stage": "balance", "gate": gate, "result": f"Wallet holds {held:g} {gate['symbol']}, "
                                                                 f"less than the {gate['approved_token_qty']:g} to sell"}
    if hasattr(wallet, "tx_locked") and wallet.tx_locked():
        return {"stage": "tx-lock", "gate": gate, "result": "The wallet has a transaction in progress, or one waiting for "
                                                            "your confirmation in the Binance App — finish that first"}
    if gate.get("trigger_token_price"):
        if not confirm({"gate": gate}):
            return {"stage": "confirm", "gate": gate, "result": "Not confirmed — nothing was placed"}
        ok, sid, raw = wallet.place_limit(gate)
        if not ok:
            return {"stage": "limit", "gate": gate, "wallet": raw,
                    "result": "The wallet rejected the limit order; stopping without a market-order fallback"}
        return {"stage": "done", "gate": gate, "status": "LIMIT_PLACED", "strategy_id": sid,
                "result": f"Limit order placed (strategyId {sid}) — placed, not filled. Check it with "
                          f"`baw limit-order list --strategyId {sid} --json`."}
    if gate.get("slippage") is None:       # bind the swap to what the quote check accepted
        gate["slippage"] = 1.0
        gate["notes"].append("No slippage given: capped at 1% to match the quote check (instead of the wallet's \"auto\").")
        gate["baw_commands"] = wallet.commands(gate)
    try:
        frm, to = wallet.quote(gate)
        quoted_at = clock()
    except (KeyError, TypeError, ValueError) as e:
        return {"stage": "quote", "gate": gate, "result": f"No usable quote from the wallet — {e}"}
    frm, to = _quote_in_tokens_and_usd(gate, frm, to, pay_price)
    size = _size_problem(gate, frm)
    if size:
        return {"stage": "quote", "gate": gate, "quote": {"from": frm, "to": to}, "result": size}
    q = check_quote(gate["side"], frm, to, gate["token_price"])
    summary = {"gate": gate, "quote": {"from": frm, "to": to, "check": q.level, "reason": q.reason}}
    if q.level == REFUSE:
        return {"stage": "quote", **summary, "result": q.reason}
    if not confirm(summary):
        return {"stage": "confirm", **summary, "result": "Not confirmed — nothing was placed"}
    if clock() - quoted_at > 30:      # the user took a while: re-quote before swapping
        try:
            frm2, to2 = wallet.quote(gate)
        except (KeyError, TypeError, ValueError) as e:
            return {"stage": "quote", **summary, "result": f"Re-quote failed — {e}"}
        frm2, to2 = _quote_in_tokens_and_usd(gate, frm2, to2, pay_price)
        size2 = _size_problem(gate, frm2)          # the re-quote gets the same unit-error guard as the first quote
        if size2:
            return {"stage": "quote", **summary, "result": "Re-quote: " + size2}
        q2 = check_quote(gate["side"], frm2, to2, gate["token_price"])
        if q2.level == REFUSE:
            return {"stage": "quote", **summary, "result": "The price moved after confirmation: " + q2.reason}
        if q2.level != q.level and not confirm({**summary, "quote": {"from": frm2, "to": to2, "check": q2.level,
                                                                      "reason": q2.reason}}):
            return {"stage": "confirm", **summary, "result": "The re-quote is worse than the one you accepted, and it "
                                                             "was not confirmed again — nothing was placed"}
    try:
        oid = wallet.swap(gate)
    except ValueError as e:
        if str(e).startswith("TIMEOUT"):   # no answer is not a rejection: the order may exist — never retry blind
            return {"stage": "unknown", **summary, "result": f"No answer from the wallet — {e}"}
        return {"stage": "swap", **summary, "result": f"The wallet rejected the swap — {e}"}
    status, tx = "PENDING", None
    for _ in range(max_polls):     # an orderId is not a completed swap (market-order.md)
        status, tx = wallet.order_status(oid)
        if status in ("FINISHED", "FAILED"):
            break
        sleep(2.0)
    if status not in ("FINISHED", "FAILED"):
        return {"stage": "pending", **summary, "order_id": oid, "status": status, "tx_hash": tx,
                "result": f"Order {oid} is still processing — not a success yet. If your wallet asks for a second "
                          f"confirmation (NeedConfirmation), approve it in the Binance App; re-check with "
                          f"`baw market-order list --orderId {oid} --json`."}
    return {"stage": "done", **summary, "order_id": oid, "status": status, "tx_hash": tx}
