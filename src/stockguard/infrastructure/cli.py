"""stockguard CLI: check | scan | serve | mcp"""
import argparse
import json
import os
import sys
import time

from stockguard.adapters.binance_rwa import RwaClient
from stockguard.application.service import Guard


def main(argv=None):
    p = argparse.ArgumentParser(prog="stockguard")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="Is this tokenized-stock trade safe right now?")
    c.add_argument("ticker"); c.add_argument("side", nargs="?", default="BUY")
    c.add_argument("qty", nargs="?", type=float, default=1.0)
    c.add_argument("--threshold", type=float, default=0.01)
    s = sub.add_parser("scan", help="Scan every BSC tokenized stock -> JSONL")
    s.add_argument("--out", default="data/snapshot.jsonl"); s.add_argument("--workers", type=int, default=8)
    s.add_argument("--limit", type=int, default=None)
    w = sub.add_parser("serve", help="Web page + JSON API"); w.add_argument("--port", type=int, default=8787)
    sub.add_parser("mcp", help="MCP stdio server (tool: check_tokenized_stock_trade)")
    rp = sub.add_parser("replay", help="Dollar error of a naive 1-token-=-1-share bot on a scan file")
    rp.add_argument("scan_file"); rp.add_argument("--budget", type=float, default=1000.0)
    a = p.parse_args(argv)
    guard = Guard(RwaClient())
    if a.cmd == "check":
        print(json.dumps(guard.check(a.ticker, a.side, a.qty, a.threshold), indent=2))
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
    elif a.cmd == "replay":
        from stockguard.application.replay import naive_share_bot
        recs = [json.loads(l) for l in open(a.scan_file)]
        print(json.dumps(naive_share_bot(recs, a.budget), indent=1))
        return
    elif a.cmd == "mcp":
        from stockguard.adapters.mcp_stdio import run
        run(guard, sys.stdin, sys.stdout)


if __name__ == "__main__":
    main()
