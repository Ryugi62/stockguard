"""UC-6 guarded trade: the gate drives Agentic Wallet end to end, and the wallet signs under its own limits.

preflight (`wallet status`, `wallet settings`) -> gate -> `market-order quote` re-checked against the token price
-> explicit yes from the user -> `market-order swap` -> poll `market-order list` until FINISHED or FAILED.
A limit order is placed only as a limit order; if the wallet rejects it, we stop (skill step 7).
"""
from typing import Callable, Dict, List, Optional, Protocol, Tuple

from stockguard.application.service import Guard
from stockguard.application.wallet_gate import gate_swap
from stockguard.domain.wallet_gate import ASK, REFUSE, WalletSettings, check_quote


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


def run_guarded_trade(guard: Guard, wallet: WalletPort, ticker: str, usd_amount: float, side: str = "BUY",
                      pay_with: str = "USDT", slippage: Optional[float] = None, auditor=None,
                      trigger_share_price: Optional[float] = None, confirm: Callable[[Dict], bool] = lambda s: False,
                      sleep: Optional[Callable[[float], None]] = None, today: Optional[str] = None,
                      max_polls: int = 30) -> Dict:
    import time as _time
    sleep = sleep or _time.sleep
    st = wallet.status()
    if st != "CONNECTED":
        return {"stage": "preflight", "result": f"Agentic Wallet is not ready (status {st}) — run `baw auth signin`"}
    settings = wallet.settings()
    pay_price = wallet.price("BNB") if pay_with.upper() == "BNB" else None
    gate = gate_swap(guard, ticker, usd_amount, side=side, pay_with=pay_with, settings=settings, auditor=auditor,
                     slippage=slippage, trigger_share_price=trigger_share_price, pay_price=pay_price, today=today)
    gate["baw_commands"] = wallet.commands(gate)
    if gate["action"] in (REFUSE, ASK) or not gate["baw_commands"]:
        return {"stage": "gate", "gate": gate}
    if gate["side"] == "SELL":
        held = wallet.balance(gate["contract"])
        if held + 1e-12 < gate["approved_token_qty"]:
            return {"stage": "balance", "gate": gate, "result": f"Wallet holds {held:g} {gate['symbol']}, "
                                                                 f"less than the {gate['approved_token_qty']:g} to sell"}
    if gate.get("trigger_token_price"):
        if not confirm({"gate": gate}):
            return {"stage": "confirm", "gate": gate, "result": "Not confirmed — nothing was placed"}
        ok, sid, raw = wallet.place_limit(gate)
        if not ok:
            return {"stage": "limit", "gate": gate, "wallet": raw,
                    "result": "The wallet rejected the limit order; stopping without a market-order fallback"}
        return {"stage": "done", "gate": gate, "status": "LIMIT_PLACED", "strategy_id": sid}
    try:
        frm, to = wallet.quote(gate)
    except (KeyError, TypeError, ValueError) as e:
        return {"stage": "quote", "gate": gate, "result": f"No usable quote from the wallet ({e})"}
    if gate["side"] == "BUY" and gate["pay_with"] == "BNB":
        frm = frm * (pay_price or 0)           # the quote is in BNB; compare in dollars
    q = check_quote(gate["side"], frm, to, gate["token_price"])
    summary = {"gate": gate, "quote": {"from": frm, "to": to, "check": q.level, "reason": q.reason}}
    if q.level == REFUSE:
        return {"stage": "quote", **summary, "result": q.reason}
    if not confirm(summary):
        return {"stage": "confirm", **summary, "result": "Not confirmed — nothing was placed"}
    oid = wallet.swap(gate)
    if not oid:
        return {"stage": "swap", **summary, "result": "The wallet did not return an orderId"}
    status, tx = "PENDING", None
    for _ in range(max_polls):     # an orderId is not a completed swap (market-order.md)
        status, tx = wallet.order_status(oid)
        if status in ("FINISHED", "FAILED"):
            break
        sleep(2.0)
    return {"stage": "done", **summary, "order_id": oid, "status": status, "tx_hash": tx}
