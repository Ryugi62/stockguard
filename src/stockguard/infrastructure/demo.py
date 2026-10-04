"""`stockguard demo` / `python3 demo.py` — the one-minute judge walkthrough. Offline (recorded real data) by default."""
from stockguard.adapters.agentic_wallet import commands, parse_wallet_settings
from stockguard.application.replay import naive_share_bot
from stockguard.application.service import Guard
from stockguard.application.wallet_gate import gate_swap

# Shape of `baw wallet settings --json` (references/wallet-setting.md); quotaLeft lowered to 250 for the demo.
SAMPLE_WALLET_SETTINGS = {"success": True, "data": {"dailyLimit": 1000, "quotaUsed": 750, "quotaLeft": 250,
                                                    "abnormalTxnHandling": "NeedConfirmation", "tradeAllTokens": True}}


def _usd(x):
    return f"${x:,.2f}"


def _gate_block(out, indent="   "):
    lines = [f"{indent}→ {out['action']}" + (f"  (approved {_usd(out['approved_usd'])} of {_usd(out['requested_usd'])})"
                                             if out.get("approved_usd") not in (None, out["requested_usd"]) else "")]
    lines += [f"{indent}  · {r}" for r in out.get("reasons", [])[:4]]
    cmds = commands(out)
    lines += [f"{indent}  $ {c}" for c in cmds] if cmds else [f"{indent}  (no wallet command is emitted)"]
    return lines


def run_demo(guard: Guard, live: bool = False, out=print) -> None:
    src = "live public data" if live else \
        f"recorded real Binance Web3 responses ({getattr(guard.client, 'captured_at', '?')}, Sunday — US market closed)"
    out("StockGuard demo — a safety check in front of every tokenized-stock trade, for people and for agents.")
    out(f"Data: {src}. No API key, no wallet, nothing is signed.")
    out("")
    out('1) A person asks: "Can I buy $1,000 of Netflix right now?"')
    rows = guard.compare("NFLX", usd_amount=1000)
    out(f"   NFLX is {len(rows)} different tokens on BNB Chain — StockGuard asks which one instead of guessing:")
    for r in rows:
        if r.get("multiplier_conflict"):
            share = f"1 token = {r['list_multiplier']:.4g} or {r['multiplier']:.4g}?"
        else:
            share = f"1 token = {r['multiplier']:.4g} shares" if abs(r["multiplier"] - 1) > 0.05 else "1 token = 1 share"
        out(f"   {r['symbol']:<8} {r['issuer']:<20} {share:<22} {_usd(r['token_price']) if r['token_price'] else 'no price':>10}"
            f"   {r['verdict']:<5} risk {r['risk']}")
    for r in rows:
        conflict = [n for n in r.get("data_notes", []) if "multiplier" in n and "!=" in n]
        if conflict:
            out(f"   ! {r['symbol']}: {conflict[0].split(': ', 1)[1]} — the API contradicts itself, so StockGuard won't trust either")
    out("")
    on = next((r for r in rows if r["symbol"].endswith("on")), rows[0])
    out(f"2) They pick {on['symbol']}:  stockguard check {on['symbol']} --usd 1000")
    out(f"   → {on['verdict']} (risk {on['risk']}): $1,000 = {on['token_qty']:.4g} tokens = {on['share_equivalent']:.4g} shares")
    out(f"   · " + "\n   · ".join(on["reasons"][:3]))
    out("")
    out("3) An AI agent is about to buy $1,000 of KLAC through Agentic Wallet:  stockguard gate KLACon --usd 1000")
    k = guard.check("KLACon", usd_amount=1000)
    naive = naive_share_bot([k], 1000)
    if naive:
        out(f"   Without the gate, a bot that reads the per-share price buys {_usd(naive[0]['real_usd'])} of KLAC, not $1,000 "
            f"(1 token = {k['multiplier']:.4g} shares).")
    for line in _gate_block(gate_swap(guard, "KLACon", 1000)):
        out(line)
    out("")
    if not live:
        out("4) Scenario (SPLITDEMOon is synthetic, not live data): the token is paused for a stock split")
        for line in _gate_block(gate_swap(guard, "SPLITDEMOon", 1000)):
            out(line)
        out("")
    out("5) The wallet's own limits count too (example `baw wallet settings --json`: quotaLeft $250)")
    for line in _gate_block(gate_swap(guard, "AAPLon", 500, settings=parse_wallet_settings(SAMPLE_WALLET_SETTINGS))):
        out(line)
    out("")
    out("Same checks as a web page: stockguard serve   ·   as MCP tools for agents: stockguard mcp")
    out("Live data instead of the recording: python3 demo.py --live")
