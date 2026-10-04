"""Agentic Wallet (`baw` CLI) adapter: parse `baw wallet settings --json`, render the exact commands for a gated swap.

Syntax copied from binance-skills-hub/skills/binance-web3/binance-agentic-wallet/references/market-order.md
(skill version 1.12.0). StockGuard prints these commands; it never runs them and never signs.
"""
import json
import math
import shutil
import subprocess
from typing import Callable, Dict, List, Optional

from stockguard.domain.wallet_gate import ASK, REFUSE, WalletSettings

# SKILL.md "Common Token Addresses" — BNB Smart Chain
BSC_STABLES = {"USDT": "0x55d398326f99059fF775485246999027B3197955",
               "USDC": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
               "U": "0xcE24439F2D9C6a2289F741120FE202248B666666",
               "USD1": "0x8d0D000Ee44948FC98c9B98A4FA4921476f08B0d",
               "BNB": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"}   # native, listed in the same table
USDT_BSC = BSC_STABLES["USDT"]


def parse_wallet_settings(raw: Optional[Dict]) -> Optional[WalletSettings]:
    """Accepts the full `{"success":..., "data": {...}}` response or just its `data`."""
    if not raw:
        return None
    d = raw.get("data", raw) if isinstance(raw, dict) else {}

    def num(k):
        try:
            return float(d[k]) if d.get(k) is not None else None
        except (TypeError, ValueError):
            return None
    tat = d.get("tradeAllTokens")
    _session = d.get("sessionExpireTime")
    return WalletSettings(quota_left=num("quotaLeft"), daily_limit=num("dailyLimit"),
                          abnormal_handling=d.get("abnormalTxnHandling"),
                          trade_all_tokens=tat if isinstance(tat, bool) else None, quota_date=d.get("quotaDate"),
                          session_expires=_session)


def parse_quote(raw: Dict):
    """`baw market-order quote --json` -> (fromCoinAmount, toCoinAmount)."""
    d = raw.get("data", raw) if isinstance(raw, dict) else {}
    return float(d["fromCoinAmount"]), float(d["toCoinAmount"])


def _floor(x: float, places: int = 6) -> str:
    return f"{math.floor(x * 10 ** places) / 10 ** places:.{places}f}"


def _args(gate: Dict) -> str:
    pay = BSC_STABLES[gate.get("pay_with", "USDT")]
    if gate["side"] == "BUY":
        qty = _floor(gate["pay_qty"], 6) if gate.get("pay_with") == "BNB" else f"{gate['approved_usd']:.2f}"
        src, dst = pay, gate["contract"]
    else:
        qty, src, dst = _floor(gate["approved_token_qty"]), gate["contract"], pay
    return f"--fromTokenQty {qty} --fromToken {src} --toToken {dst} --binanceChainId 56"


def _slip(gate: Dict) -> str:
    return f" --slippage {gate['slippage']:g}" if gate.get("slippage") is not None else ""


def commands(gate: Dict) -> List[str]:
    """quote -> swap -> poll (or a limit order), or nothing when the gate refused or must ask which token."""
    if gate.get("action") in (REFUSE, ASK) or not gate.get("approved_usd"):
        return []
    a = _args(gate)
    if gate.get("trigger_token_price"):
        side = "buy" if gate["side"] == "BUY" else "sell"
        return [f"baw limit-order {side} --triggerPrice {gate['trigger_token_price']:.2f} {a}{_slip(gate)} --json",
                "baw limit-order list --strategyId <strategyId from the order> --json   # placed is not filled; if it was "
                "rejected, stop and ask — never a market order"]
    return [f"baw market-order quote {a}{_slip(gate)} --json",
            f"baw market-order swap {a}{_slip(gate)} --json",
            "baw market-order list --orderId <orderId from the swap> --json   # repeat until status is FINISHED or FAILED"]


class BawRunner:
    """Runs `baw … --json` and returns the parsed JSON. Used by `stockguard trade`; StockGuard itself never signs —
    the wallet does, under its own limits."""
    def __init__(self, run: Optional[Callable[[List[str]], str]] = None, binary: str = "baw"):
        self.binary = binary
        self._run = run or self._subprocess

    def _subprocess(self, argv: List[str]) -> str:
        if not shutil.which(self.binary):
            raise FileNotFoundError("baw CLI not found — npm install -g @binance/agentic-wallet, then baw auth signin")
        p = subprocess.run([self.binary] + argv, capture_output=True, text=True, timeout=60)
        return p.stdout or p.stderr

    def __call__(self, command: str) -> Dict:
        argv = command.split("#")[0].split()[1:]          # drop the leading "baw" and any trailing comment
        out = self._run(argv)
        try:
            return json.loads(out)
        except ValueError:
            return {"success": False, "raw": out[:500]}


class AgenticWallet:
    """WalletPort over the `baw` CLI (application/trade.py). Every state change goes through the wallet's own policy."""
    def __init__(self, baw: BawRunner):
        self.baw = baw

    @staticmethod
    def _data(r):
        return r.get("data") if isinstance(r, dict) else None

    def status(self):
        return (self._data(self.baw("baw wallet status --json")) or {}).get("status")

    def settings(self):
        return parse_wallet_settings(self.baw("baw wallet settings --json"))

    def price(self, symbol):
        rows = self._data(self.baw(f"baw wallet balance --symbol {symbol} --binanceChainId 56 --json")) or []
        return float(rows[0]["price"]) if rows else None

    def balance(self, contract):
        rows = self._data(self.baw(f"baw wallet balance --tokenAddress {contract} --binanceChainId 56 --json")) or []
        return float(rows[0]["balance"]) if rows else 0.0

    def pay_balance(self, symbol):
        """None when the wallet doesn't answer (the swap will then fail on its own)."""
        r = self.baw(f"baw wallet balance --symbol {symbol} --binanceChainId 56 --json")
        rows = self._data(r)
        if not isinstance(rows, list):
            return None
        return float(rows[0]["balance"]) if rows else 0.0

    def cli_ok(self, required="1.10.0"):
        d = self._data(self.baw(f"baw cli-check --required-version {required} --json")) or {}
        return None if not d else not d.get("needUpdateCli", False)

    def commands(self, gate):
        return commands(gate)

    def quote(self, gate):
        return parse_quote(self.baw(commands(gate)[0]))

    def swap(self, gate):
        return (self._data(self.baw(commands(gate)[1])) or {}).get("orderId")

    def order_status(self, order_id):
        rows = (self._data(self.baw(f"baw market-order list --orderId {order_id} --json")) or {}).get("list") or []
        return (rows[0].get("status", "PENDING"), rows[0].get("txHash")) if rows else ("PENDING", None)

    def place_limit(self, gate):
        r = self.baw(commands(gate)[0])
        return bool(r.get("success")), (self._data(r) or {}).get("strategyId"), r
