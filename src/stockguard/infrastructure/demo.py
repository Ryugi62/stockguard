"""`stockguard demo` / `python3 demo.py` — the one-minute judge walkthrough. Offline (recorded real data) by default."""
from stockguard.adapters.agentic_wallet import commands, parse_wallet_settings
from stockguard.application.service import Guard
from stockguard.application.wallet_gate import gate_swap

# Shape of `baw wallet settings --json` (references/wallet-setting.md); quotaLeft lowered to 250 for the demo.
SAMPLE_WALLET_SETTINGS = {"success": True, "data": {"dailyLimit": 1000, "quotaUsed": 750, "quotaLeft": 250,
                                                    "abnormalTxnHandling": "NeedConfirmation", "tradeAllTokens": True}}


def _usd(x):
    return f"${x:,.2f}"


def _gate_block(out, indent="   ", max_reasons=3):
    head = f"{indent}→ {out['action']}"
    if out.get("approved_usd") not in (None, out["requested_usd"]) and out["action"] != "REFUSE":
        head += f"  (approved {_usd(out['approved_usd'])} of {_usd(out['requested_usd'])})"
    lines = [head] + [f"{indent}  · {r}" for r in out.get("reasons", [])[:max_reasons]]
    cmds = commands(out)
    lines += [f"{indent}  $ {c}" for c in cmds[:2]] if cmds else [f"{indent}  (no wallet command is emitted)"]
    return lines


def run_demo(guard: Guard, live: bool = False, out=print, auditor=None) -> None:
    src = "live public data" if live else \
        f"recorded real Binance Web3 responses ({getattr(guard.client, 'captured_at', '?')}, Sunday — US market closed)"
    out("StockGuard demo — a safety gate in front of every tokenized-stock trade, for people and for AI agents.")
    out(f"Data: {src}. No API key, no wallet, nothing is signed.")
    out("")
    out('1) A person asks: "Can I buy $1,000 of Netflix right now?"')
    cands = guard.describe(guard.tokens_candidates("NFLX"))
    out(f"   NFLX is {len(cands)} different tokens on BNB Chain — StockGuard asks which one instead of guessing:")
    rows = {r["symbol"]: r for r in guard.compare("NFLX", usd_amount=1000)}
    for c in cands:
        r = rows.get(c["symbol"], {})
        per = f"${r['per_share_price']:,.2f}/share" if r.get("per_share_price") else "no price"
        spread = f" (+{r['per_share_spread'] * 100:.1f}%)" if r.get("per_share_spread") else ""
        out(f"   {c['symbol']:<8} {c['issuer']:<20} 1 token = {c['shares_label']:<40} {per}{spread}")
    out("   Same share, three prices. The per-share price also settles NFLXx: $71.30 per token only makes sense as 1 share.")
    out("")
    on = guard.check("NFLXon", usd_amount=1000)
    out(f"2) They pick NFLXon:  stockguard check NFLXon --usd 1000")
    out(f"   → {on['verdict']} (risk {on['risk']}): $1,000 = {on['token_qty']:.4g} tokens = {on['share_equivalent']:.4g} shares")
    out("   · " + "\n   · ".join(on["reasons"][:2]))
    out("")
    out("3) An AI agent is about to buy $100 of NFLXx through Agentic Wallet:  stockguard gate NFLXx --usd 100")
    for line in _gate_block(gate_swap(guard, "NFLXx", 100, auditor=auditor), max_reasons=3):
        out(line)
    out("")
    out("4) The agent buys $1,000 of KLACon instead:  stockguard gate KLACon --usd 1000 --slippage 1")
    k = gate_swap(guard, "KLACon", 1000, auditor=auditor, slippage=1.0)
    for line in _gate_block(k):
        out(line)
    if k.get("audit") and not k["audit"]["available"]:
        out("     (the wallet skill's mandatory token audit has no data for 663 of 675 stock tokens, so the user must acknowledge;")
        out("      StockGuard puts its stock warnings into that same confirmation)")
    out("")
    out('5) "Sell my NFLXon when Netflix hits $75":  stockguard gate NFLXon --usd 200 --side SELL --trigger-share-price 75')
    lim = gate_swap(guard, "NFLXon", 200, side="SELL", trigger_share_price=75, auditor=auditor)
    if lim.get("trigger_token_price"):
        out(f"   `baw limit-order --triggerPrice` is the TOKEN price: $75/share × {lim['multiplier']:.4g} = ${lim['trigger_token_price']:,.2f}/token."
            f" Sent as $75, the trigger is already met (the token trades near ${lim['token_price']:,.0f}), so it would sell now instead of waiting.")
    for line in _gate_block(lim, max_reasons=1):
        out(line)
    out("   (No audit needed: a SELL's target is USDT. The skill quotes an `Ondo-related tokens cannot be traded` error for")
    out("    limit orders — if the wallet rejects it, `trade` stops and never falls back to a market order.)")
    out("")
    if not live:
        out("6) Scenario (SPLITDEMOon is synthetic, not live data): the token is paused for a stock split")
        for line in _gate_block(gate_swap(guard, "SPLITDEMOon", 1000), max_reasons=1):
            out(line)
        out("")
    out(f"{6 if live else 7}) The wallet's own limits count too (example `baw wallet settings --json`: quotaLeft $250)")
    q = gate_swap(guard, "AAPLon", 500, settings=parse_wallet_settings(SAMPLE_WALLET_SETTINGS), slippage=1.0)
    out(f"   → {q['action']}  (approved {_usd(q['approved_usd'])} of {_usd(q['requested_usd'])}): {q['reasons'][-1]}")
    out("")
    out("With a signed-in Agentic Wallet, `stockguard trade KLACon --usd 5` runs it end to end: preflight → gate →")
    out("the wallet's quote re-checked against the token price → your typed yes → swap → poll until FINISHED/FAILED.")
    out("Same checks as a web page: stockguard serve   ·   as MCP tools for agents: stockguard mcp")
    out("Recorded data instead: python3 demo.py" if live else "Live data instead of the recording: python3 demo.py --live")
