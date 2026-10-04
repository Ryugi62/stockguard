"""Agentic Wallet (`baw` CLI) adapter: parse `baw wallet settings --json`, render the exact commands for a gated swap.

Syntax copied from binance-skills-hub/skills/binance-web3/binance-agentic-wallet/references/market-order.md
(skill version 1.12.0). StockGuard prints these commands; it never runs them and never signs.
"""
import math
from typing import Dict, List, Optional

from stockguard.domain.wallet_gate import ASK, REFUSE, WalletSettings

# SKILL.md "Common Token Addresses" — BNB Smart Chain
BSC_STABLES = {"USDT": "0x55d398326f99059fF775485246999027B3197955",
               "USDC": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
               "U": "0xcE24439F2D9C6a2289F741120FE202248B666666",
               "USD1": "0x8d0D000Ee44948FC98c9B98A4FA4921476f08B0d"}
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
    return WalletSettings(quota_left=num("quotaLeft"), daily_limit=num("dailyLimit"),
                          abnormal_handling=d.get("abnormalTxnHandling"),
                          trade_all_tokens=tat if isinstance(tat, bool) else None)


def _floor(x: float, places: int = 6) -> str:
    return f"{math.floor(x * 10 ** places) / 10 ** places:.{places}f}"


def commands(gate: Dict) -> List[str]:
    """quote -> swap -> poll, or nothing when the gate refused or must ask which token."""
    if gate.get("action") in (REFUSE, ASK) or not gate.get("approved_usd"):
        return []
    stable = BSC_STABLES[gate.get("pay_with", "USDT")]
    if gate["side"] == "BUY":
        qty, src, dst = f"{gate['approved_usd']:.2f}", stable, gate["contract"]
    else:
        qty, src, dst = _floor(gate["approved_token_qty"]), gate["contract"], stable
    args = f"--fromTokenQty {qty} --fromToken {src} --toToken {dst} --binanceChainId 56"
    return [f"baw market-order quote {args} --json",
            f"baw market-order swap {args} --json",
            "baw market-order list --orderId <orderId from the swap> --json   # repeat until status is FINISHED or FAILED"]
