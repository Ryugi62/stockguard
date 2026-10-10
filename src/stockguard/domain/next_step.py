"""What to do after a verdict (SPEC UC-11). Pure: no I/O, no framework.

A verdict alone leaves a non-crypto user stuck ("OK, and now?"). Every check therefore ends in one next action:
how to place exactly this order in Binance Wallet, or why to wait.
"""
from typing import Dict, Optional

WALLET_URL = "https://www.binance.com/en/web3wallet"


def _num(x: float) -> str:
    return f"{float(x):.4g}"


def _usd(x: float) -> str:
    return f"${float(x):,.2f}".replace(".00", "")


def next_step(verdict: str, symbol: str, ticker: str, contract: str, side: str, usd: Optional[float],
              token_qty: float, shares: float) -> Dict:
    side = (side or "BUY").upper()
    if verdict == "BLOCK":
        return {"kind": "wait", "title": f"Don't {side.lower()} {symbol} now — check again later",
                "button": None, "wallet_url": None, "copy": None, "agent_command": None,
                "steps": ["Nothing to do in your wallet: the reasons above mean an order could fill at a wrong price "
                          "or not at all.",
                          "Check again when the reason is gone (see the next trading session above, if shown)."]}
    amount = f"{_usd(usd)} of" if usd else f"{_num(token_qty)} tokens of"
    verb = "Buy" if side == "BUY" else "Sell"
    what = f"{_num(token_qty)} tokens = {_num(shares)} {ticker} shares"
    if side == "BUY":
        pay = f"Pay {_usd(usd)} in USDT. You get about {what}." if usd else f"Buy {what}."
    else:
        pay = f"Sell about {what} for about {_usd(usd)} in USDT." if usd else f"Sell {what}."
    steps = ["Open Binance Wallet and go to Trade (or Swap) on BNB Chain.",
             f"Find the token by this contract address, not by the name: {contract}. "
             f"'{ticker}' can mean several tokens with different terms.",
             pay,
             "On the confirm screen, check the address and the amount once more, then confirm."]
    if verdict == "WARN":
        steps.insert(0, "Read the warning above first. If you still want to go ahead:")
    cmd = f"stockguard trade {symbol} --usd {('%.2f' % usd).rstrip('0').rstrip('.')}" if usd else None
    return {"kind": side.lower(), "title": f"{verb} {amount} {symbol}",
            "button": f"{verb} {amount} {symbol}", "wallet_url": WALLET_URL, "copy": contract,
            "agent_command": cmd, "steps": steps}
