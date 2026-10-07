"""stockguard CLI: demo | check | compare | gate | trade | scan | serve | mcp | kline | replay"""
import argparse
import json
import os
import sys
import time

from stockguard.adapters.binance_rwa import RwaClient, RwaError
from stockguard.adapters.bsc_rpc import BscRpc
from stockguard.adapters.mapping import to_snapshot
from stockguard.application.service import AmbiguousTicker, Guard, TickerNotFound


# Exit codes (README "Exit codes"): agents and scripts can branch without parsing JSON. 1/2 stay "error"/"usage".
EXIT = {"PROCEED": 0, "ALLOW": 0, "CONFIRM": 10, "WARN": 10, "ASK": 11, "REFUSE": 12, "BLOCK": 12}


def trade_exit_code(r) -> int:
    if r.get("stage") == "done" and r.get("status") in ("FINISHED", "LIMIT_PLACED"):
        return 0
    return 3 if r.get("stage") == "pending" else 1


def _wants_text(a) -> bool:
    return sys.stdout.isatty() if getattr(a, "text", None) is None else bool(a.text)


def text_check(r) -> str:
    lines = [f"{r['symbol']} ({r.get('issuer') or ''}): {r['verdict']} · risk {r['risk']}/100 · "
             f"{r['token_qty']:.4g} tokens = {r['share_equivalent']:.4g} {r['ticker']} shares"]
    lines += [f"  · {x}" for x in r.get("reasons", [])] + [f"  i {x}" for x in r.get("notes", []) + r.get("data_notes", [])]
    return "\n".join(lines) + "\n(--json for the full answer)"


def text_gate(g) -> str:
    lines = [f"{g.get('symbol') or g.get('query')}: {g['action']}" +
             (f" · approved ${g['approved_usd']:,.2f} of ${g['requested_usd']:,.2f}" if g.get("requested_usd") else "")]
    lines += [f"  · {x}" for x in g.get("reasons", [])]
    lines += [f"  i {x.split(': ', 1)[1]}" for x in g.get("notes", []) if x.startswith("Heads-up to show the user: ")]
    lines += [f"  $ {c}" for c in g.get("baw_commands", [])] or ["  (no wallet command)"]
    return "\n".join(lines) + "\n(--json for the full answer)"


def build_auditor(offline: bool = False, skip: bool = False):
    if skip:
        from stockguard.adapters.token_audit import SkippedAudit
        return SkippedAudit()
    if offline:
        from stockguard.adapters.recorded import RecordedAudit
        return RecordedAudit()
    from stockguard.adapters.token_audit import TokenAuditClient
    return TokenAuditClient()


def build_guard(offline: bool = False) -> Guard:
    if offline:
        from stockguard.adapters.recorded import RecordedRwaClient, RecordedSupply
        return Guard(RecordedRwaClient(), to_snapshot, onchain=RecordedSupply())
    return Guard(RwaClient(), to_snapshot, onchain=BscRpc())


def _parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--text", action="store_true", default=None,
                        help="short human-readable answer (default when printing to a terminal; JSON otherwise)")
    common.add_argument("--json", dest="text", action="store_false", help="always print JSON (what agents read)")
    common.add_argument("--offline", action="store_true", default=os.environ.get("STOCKGUARD_OFFLINE") == "1",
                        help="use recorded real responses (no network, no key) — also STOCKGUARD_OFFLINE=1")
    p = argparse.ArgumentParser(prog="stockguard")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", parents=[common], help="One-minute walkthrough (offline by default)")
    d.add_argument("--live", action="store_true", help="use live public data instead of the recording")
    c = sub.add_parser("check", parents=[common], help="Is this tokenized-stock trade safe right now?")
    c.add_argument("ticker"); c.add_argument("side", nargs="?", default="BUY")
    c.add_argument("qty", nargs="?", type=float, default=None, help="tokens (default 1)")
    c.add_argument("--usd", type=float, default=None, help="size the order in US dollars instead of tokens")
    c.add_argument("--threshold", type=float, default=0.01)
    cm = sub.add_parser("compare", parents=[common], help="Same stock from every issuer (Ondo, xStocks, bStocks)")
    cm.add_argument("ticker"); cm.add_argument("--usd", type=float, default=1000.0)
    order = argparse.ArgumentParser(add_help=False)
    order.add_argument("ticker"); order.add_argument("--usd", type=float, default=None)
    order.add_argument("--tokens", type=float, default=None, help="SELL size in tokens (instead of --usd)")
    order.add_argument("--side", default="BUY"); order.add_argument("--pay-with", default="USDT")
    order.add_argument("--slippage", type=float, default=None, help="percent; omitted = capped at 1%% (not the wallet's \"auto\")")
    order.add_argument("--trigger-share-price", type=float, default=None,
                       help="limit order at this price per SHARE (converted to the per-token trigger)")
    order.add_argument("--no-audit", action="store_true",
                       help="skip the token security audit (disclosed; the user must then acknowledge)")
    g = sub.add_parser("gate", parents=[common, order], help="Gate an Agentic Wallet order: PROCEED | CONFIRM | ASK | REFUSE")
    g.add_argument("--wallet-settings", default=None, help="file with the output of `baw wallet settings --json`")
    g.add_argument("--quote-json", default=None,
                   help="file with the output of the emitted `baw market-order quote … --json`: re-gates on the wallet's "
                        "own price (the check `trade` does), so an agent running the commands itself gets it too")
    g.add_argument("--pay-price", type=float, default=None, help="USD price of BNB when --pay-with BNB")
    tr = sub.add_parser("trade", parents=[common, order],
                        help="Guarded trade through Agentic Wallet (needs `baw`, signed in): gate -> quote check -> yes -> swap -> poll")
    tr.add_argument("--yes", action="store_true",
                    help="skip the typed confirmation — only honoured for PROCEED orders with risk 0 and an audit")
    s = sub.add_parser("scan", parents=[common], help="Scan every BSC tokenized stock -> JSONL")
    s.add_argument("--out", default="data/snapshot.jsonl"); s.add_argument("--workers", type=int, default=8)
    s.add_argument("--limit", type=int, default=None)
    w = sub.add_parser("serve", parents=[common], help="Web page + JSON API"); w.add_argument("--port", type=int, default=8787)
    sub.add_parser("mcp", parents=[common], help="MCP stdio server (tools: check_tokenized_stock_trade, guard_agentic_wallet_swap)")
    k = sub.add_parser("kline", parents=[common], help="On-chain K-line candles + volume (reproduces DX finding F7)")
    k.add_argument("ticker"); k.add_argument("--interval", default="1d"); k.add_argument("--limit", type=int, default=10)
    rp = sub.add_parser("replay", parents=[common], help="Multiplier exposure table: what $X becomes if 1 token is mistaken for 1 share (arithmetic on real multipliers)")
    rp.add_argument("scan_file"); rp.add_argument("--budget", type=float, default=1000.0)
    return p


def main(argv=None):
    a = _parser().parse_args(argv)
    if a.cmd == "demo":
        from stockguard.infrastructure.demo import run_demo
        return run_demo(build_guard(offline=not a.live), live=a.live, auditor=build_auditor(offline=not a.live))
    if a.cmd == "replay":
        from stockguard.application.replay import naive_share_bot
        recs = [json.loads(l) for l in open(a.scan_file)]
        print(json.dumps(naive_share_bot(recs, a.budget), indent=1))
        return
    guard = build_guard(a.offline)
    try:
        return _run(a, guard)
    except AmbiguousTicker as e:
        try:
            e.candidates = guard.describe(e.candidates)
        except Exception:
            pass
        sys.exit(e.message() + f" Example: stockguard check {e.candidates[0]['symbol']}  ·  side by side: "
                               f"stockguard compare {e.query}")
    except TickerNotFound as e:
        if getattr(e, "reason", None):
            sys.exit(e.reason)
        hint = f" Did you mean: {', '.join(e.suggestions)}?" if e.suggestions else ""
        sys.exit(f"No tokenized stock on BNB Chain matches '{e.query}'.{hint}")
    except ValueError as e:
        sys.exit(f"Invalid order: {e}")
    except (RwaError, LookupError) as e:
        sys.exit(f"Market data unavailable right now: {e}")


def _run(a, guard: Guard):
    if a.cmd == "check":
        r = guard.check(a.ticker, a.side, a.qty, a.threshold, usd_amount=a.usd)
        print(text_check(r) if _wants_text(a) else json.dumps(r, indent=2, ensure_ascii=False))
        return EXIT.get(r.get("verdict"), 0)
    elif a.cmd == "compare":
        rows = guard.compare(a.ticker, usd_amount=a.usd)
        for r in rows:
            r["multiplier_used"] = r["share_equivalent"] / r["token_qty"] if r.get("token_qty") else r["multiplier"]
        print(json.dumps([{k: r.get(k) for k in ("symbol", "issuer", "verdict", "risk", "shares_label", "multiplier_used",
                                                  "multiplier_conflict", "per_share_price", "per_share_spread", "token_price",
                                                  "token_qty", "share_equivalent", "session", "status", "last_trade_age_h", "stale_price", "reasons",
                                                  "data_notes", "contract")} for r in rows], indent=2))
    elif a.cmd == "gate":
        from stockguard.adapters.agentic_wallet import commands, parse_wallet_settings
        from stockguard.application.wallet_gate import gate_swap
        settings = None
        if a.wallet_settings:
            try:
                settings = parse_wallet_settings(json.load(open(a.wallet_settings)))
            except (OSError, ValueError) as e:
                sys.exit(f"Can't read --wallet-settings {a.wallet_settings}: {e}. Save the output of "
                         f"`baw wallet settings --json` to that file.")
        out = gate_swap(guard, a.ticker, a.usd, side=a.side, pay_with=a.pay_with, settings=settings,
                        auditor=build_auditor(a.offline, a.no_audit), slippage=a.slippage,
                        trigger_share_price=a.trigger_share_price, pay_price=a.pay_price,
                        today=time.strftime("%Y-%m-%d", time.gmtime()), token_qty=a.tokens)
        out["baw_commands"] = commands(out)
        if a.quote_json:
            from stockguard.application.trade import apply_wallet_quote
            try:
                raw = json.load(open(a.quote_json))
            except (OSError, ValueError) as e:
                sys.exit(f"Can't read --quote-json {a.quote_json}: {e}")
            out = apply_wallet_quote(out, raw, pay_price=a.pay_price)
        print(text_gate(out) if _wants_text(a) else json.dumps(out, indent=2, ensure_ascii=False))
        return EXIT.get(out.get("action"), 0)
    elif a.cmd == "trade":
        from stockguard.adapters.agentic_wallet import AgenticWallet, BawRunner
        from stockguard.application.trade import run_guarded_trade

        def confirm(summary):
            g = summary["gate"]
            print(json.dumps(summary, indent=2))
            audited = (g.get("audit") or {}).get("available") or (g["side"] == "SELL" and g.get("audit") is None)
            quote_ok = (summary.get("quote") or {}).get("check", "PROCEED") == "PROCEED"
            if a.yes and g["action"] == "PROCEED" and g["risk"] == 0 and audited and quote_ok:
                return True   # --yes only for a clean, audited order; everything else needs a typed yes
            return input(f"Place {g['side']} ${g['approved_usd']:,.2f} of {g['symbol']} through Agentic Wallet? "
                         f"Type yes: ").strip().lower() == "yes"
        r = run_guarded_trade(guard, AgenticWallet(BawRunner()), a.ticker, a.usd, side=a.side, pay_with=a.pay_with,
                              slippage=a.slippage, auditor=build_auditor(a.offline, a.no_audit), token_qty=a.tokens,
                              trigger_share_price=a.trigger_share_price, confirm=confirm,
                              today=time.strftime("%Y-%m-%d", time.gmtime()))
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return trade_exit_code(r)
    elif a.cmd == "scan":
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        t0, n, bad, inc = time.time(), 0, 0, 0
        with open(a.out, "w") as f:
            for rec in guard.scan(workers=a.workers, limit=a.limit):
                f.write(json.dumps(rec) + "\n"); n += 1
                bad += "error" in rec; inc += bool(rec.get("inconsistencies"))
        print(json.dumps({"tokens": n, "errors": bad, "with_inconsistencies": inc,
                          "seconds": round(time.time() - t0, 1), "out": a.out}))
    elif a.cmd == "serve":
        from stockguard.adapters.web import serve
        serve(guard, a.port, auditor=build_auditor(a.offline))
    elif a.cmd == "kline":
        t = guard.resolve(a.ticker)
        rows = guard.client.kline(t["contractAddress"], a.interval, a.limit)
        vols = [float(r[5]) for r in rows]
        print(json.dumps({"symbol": t["symbol"], "candles": len(rows), "candles_with_volume": sum(v > 0 for v in vols),
                          "last_close": rows[-1][4] if rows else None, "raw": rows}, indent=1))
    elif a.cmd == "mcp":
        from stockguard.adapters.mcp_stdio import run
        run(guard, sys.stdin, sys.stdout, auditor=build_auditor(a.offline))


if __name__ == "__main__":
    sys.exit(main())
