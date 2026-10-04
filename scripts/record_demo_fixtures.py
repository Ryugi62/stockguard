"""Record real public Binance Web3 RWA responses (+ BSC totalSupply) for the offline demo.

    PYTHONPATH=src python3 scripts/record_demo_fixtures.py

Writes fixtures/recorded/demo-2026-10-04.json (or --out). One extra token, SPLITDEMOon, is synthetic and flagged
`"synthetic": true` everywhere: it shows the stock-split BLOCK path, which could not be observed on a weekend.
"""
import argparse
import datetime
import json
import os
import sys

from stockguard.adapters.binance_rwa import RwaClient
from stockguard.adapters.bsc_rpc import BscRpc
from stockguard.adapters.token_audit import AUDIT_URL, urllib_post

SYMBOLS = ["NFLXon", "NFLXx", "NFLXB", "KLACon", "ENLVon", "AAPLon", "AAPLx", "AAPLB", "ABBVx"]
SYNTH = "0x0000000000000000000000000000000000000001"   # not a real token


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join("fixtures", "recorded", "demo-2026-10-04.json"))
    a = ap.parse_args(argv)
    c, rpc = RwaClient(), BscRpc()
    by_sym = {t["symbol"]: t for t in c.list_tokens("56")}
    toks = [by_sym[s] for s in SYMBOLS if s in by_sym]
    rec = {"captured_at_utc": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
           "source": "Binance Web3 public RWA endpoints (no key) + BSC public RPC totalSupply()",
           "list": toks, "market_status": c.market_status(), "dynamic": {}, "meta": {}, "supply": {}, "audit": {}}
    for t in toks:
        addr = t["contractAddress"]
        rec["dynamic"][addr] = c.dynamic(addr)
        try:
            rec["meta"][addr] = c.meta(addr)
        except Exception as e:
            rec["meta"][addr] = {"error": str(e)[:200]}
        try:
            import uuid
            rec["audit"][addr] = urllib_post(AUDIT_URL, {"binanceChainId": "56", "contractAddress": addr,
                                                         "requestId": str(uuid.uuid4())})
        except Exception as e:
            print(f"audit {t['symbol']}: {e}", file=sys.stderr)
        try:
            rec["supply"][addr] = rpc.total_supply(addr)
        except Exception as e:
            print(f"supply {t['symbol']}: {e}", file=sys.stderr)
    # Synthetic scenario token (clearly labelled): a stock-split pause, the BLOCK path of SPEC.md G/W/T #1.
    rec["list"].append({"chainId": "56", "contractAddress": SYNTH, "symbol": "SPLITDEMOon", "ticker": "SPLITDEMO",
                        "type": 1, "multiplier": "1", "synthetic": True})
    rec["dynamic"][SYNTH] = {"synthetic": True, "symbol": "SPLITDEMOon", "ticker": "SPLITDEMO",
                             "tokenInfo": {"price": "100", "sharesMultiplier": "1"}, "stockInfo": {"price": "99.80"},
                             "statusInfo": {"openState": False, "marketStatus": "regular", "reasonCode": "ASSET_PAUSED",
                                            "reasonMsg": "stock_split"}}
    rec["meta"][SYNTH] = {"synthetic": True, "name": "Split scenario (synthetic, not a real token)"}
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(rec, f, indent=1)
    print(json.dumps({"out": a.out, "tokens": len(rec["list"]), "captured_at_utc": rec["captured_at_utc"]}))


if __name__ == "__main__":
    main()
