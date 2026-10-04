"""Latency of each public RWA endpoint (DX report: "what the latency looked like").

    PYTHONPATH=src python3 scripts/latency.py --n 10
"""
import argparse
import json
import statistics
import time

from stockguard.adapters.binance_rwa import BASE, PATHS, urllib_get

NFLXON = "0x7048f5227b032326cc8dbc53cf3fddd947a2c757"
CALLS = {
    "list type=1 (Ondo)": PATHS["list"] + "?type=1",
    "list type=2 (xStocks)": PATHS["list"] + "?type=2",
    "list type=3 (bStocks)": PATHS["list"] + "?type=3",
    "market status": PATHS["market_status"],
    "dynamic (v2)": PATHS["dynamic"] + f"?chainId=56&contractAddress={NFLXON}",
    "meta": PATHS["meta"] + f"?chainId=56&contractAddress={NFLXON}",
    "kline 1d": PATHS["kline"] + f"?chainId=56&contractAddress={NFLXON}&interval=1d&limit=10",
}


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=10)
    a = ap.parse_args(argv)
    out = {}
    for name, path in CALLS.items():
        ms = []
        for _ in range(a.n):
            t0 = time.perf_counter(); urllib_get(BASE + path); ms.append((time.perf_counter() - t0) * 1000)
        ms.sort()
        out[name] = {"n": a.n, "p50_ms": round(statistics.median(ms)), "p95_ms": round(ms[max(0, int(0.95 * a.n) - 1)]),
                     "max_ms": round(ms[-1])}
    print(json.dumps({"measured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "client": "South Korea, home connection",
                      "results": out}, indent=1))


if __name__ == "__main__":
    main()
