"""stockguard CLI: demo | check | compare | gate | scan | serve | mcp | kline | replay"""
import argparse
import json
import os
import sys
import time

from stockguard.adapters.binance_rwa import RwaClient, RwaError
from stockguard.adapters.bsc_rpc import BscRpc
from stockguard.adapters.mapping import to_snapshot
from stockguard.application.service import AmbiguousTicker, Guard, TickerNotFound


def build_guard(offline: bool = False) -> Guard:
    if offline:
        from stockguard.adapters.recorded import RecordedRwaClient, RecordedSupply
        return Guard(RecordedRwaClient(), to_snapshot, onchain=RecordedSupply())
    return Guard(RwaClient(), to_snapshot, onchain=BscRpc())


def _parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
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
    g = sub.add_parser("gate", parents=[common], help="Gate an Agentic Wallet swap: PROCEED | CONFIRM | ASK | REFUSE")
    g.add_argument("ticker"); g.add_argument("--usd", type=float, required=True)
    g.add_argument("--side", default="BUY"); g.add_argument("--pay-with", default="USDT")
    g.add_argument("--wallet-settings", default=None, help="file with the output of `baw wallet settings --json`")
    s = sub.add_parser("scan", parents=[common], help="Scan every BSC tokenized stock -> JSONL")
    s.add_argument("--out", default="data/snapshot.jsonl"); s.add_argument("--workers", type=int, default=8)
    s.add_argument("--limit", type=int, default=None)
    w = sub.add_parser("serve", parents=[common], help="Web page + JSON API"); w.add_argument("--port", type=int, default=8787)
    sub.add_parser("mcp", parents=[common], help="MCP stdio server (tools: check_tokenized_stock_trade, guard_agentic_wallet_swap)")
    k = sub.add_parser("kline", parents=[common], help="On-chain K-line candles + volume (reproduces DX finding F7)")
    k.add_argument("ticker"); k.add_argument("--interval", default="1d"); k.add_argument("--limit", type=int, default=10)
    rp = sub.add_parser("replay", parents=[common], help="Dollar error of a naive 1-token-=-1-share bot on a scan file")
    rp.add_argument("scan_file"); rp.add_argument("--budget", type=float, default=1000.0)
    return p


def main(argv=None):
    a = _parser().parse_args(argv)
    if a.cmd == "demo":
        from stockguard.infrastructure.demo import run_demo
        return run_demo(build_guard(offline=not a.live), live=a.live)
    if a.cmd == "replay":
        from stockguard.application.replay import naive_share_bot
        recs = [json.loads(l) for l in open(a.scan_file)]
        print(json.dumps(naive_share_bot(recs, a.budget), indent=1))
        return
    guard = build_guard(a.offline)
    try:
        _run(a, guard)
    except AmbiguousTicker as e:
        sys.exit(e.message() + f" Example: stockguard check {e.candidates[0]['symbol']}  ·  side by side: "
                               f"stockguard compare {e.query}")
    except TickerNotFound as e:
        hint = f" Did you mean: {', '.join(e.suggestions)}?" if e.suggestions else ""
        sys.exit(f"No tokenized stock on BNB Chain matches '{e.query}'.{hint}")
    except ValueError as e:
        sys.exit(f"Invalid order: {e}")
    except (RwaError, LookupError) as e:
        sys.exit(f"Market data unavailable right now: {e}")


def _run(a, guard: Guard):
    if a.cmd == "check":
        print(json.dumps(guard.check(a.ticker, a.side, a.qty, a.threshold, usd_amount=a.usd), indent=2))
    elif a.cmd == "compare":
        rows = guard.compare(a.ticker, usd_amount=a.usd)
        print(json.dumps([{k: r.get(k) for k in ("symbol", "issuer", "verdict", "risk", "multiplier", "token_price",
                                                  "token_qty", "share_equivalent", "session", "status", "reasons",
                                                  "data_notes", "contract")} for r in rows], indent=2))
    elif a.cmd == "gate":
        from stockguard.adapters.agentic_wallet import commands, parse_wallet_settings
        from stockguard.application.wallet_gate import gate_swap
        settings = parse_wallet_settings(json.load(open(a.wallet_settings))) if a.wallet_settings else None
        out = gate_swap(guard, a.ticker, a.usd, side=a.side, pay_with=a.pay_with, settings=settings)
        out["baw_commands"] = commands(out)
        print(json.dumps(out, indent=2))
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
        serve(guard, a.port)
    elif a.cmd == "kline":
        t = guard.resolve(a.ticker)
        rows = guard.client.kline(t["contractAddress"], a.interval, a.limit)
        vols = [float(r[5]) for r in rows]
        print(json.dumps({"symbol": t["symbol"], "candles": len(rows), "candles_with_volume": sum(v > 0 for v in vols),
                          "last_close": rows[-1][4] if rows else None, "raw": rows}, indent=1))
    elif a.cmd == "mcp":
        from stockguard.adapters.mcp_stdio import run
        run(guard, sys.stdin, sys.stdout)


if __name__ == "__main__":
    main()
