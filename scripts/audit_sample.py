"""F14 evidence: query the public Token Security Audit for the first N stock tokens of each issuer.

    PYTHONPATH=src python3 scripts/audit_sample.py --n 15 --out data/audit-sample-20261004.jsonl
"""
import argparse
import json
import time
import uuid

from stockguard.adapters.binance_rwa import RwaClient
from stockguard.adapters.token_audit import AUDIT_URL, urllib_post


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=15); ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    c = RwaClient()
    rows = []
    for t in (1, 2, 3):
        for tok in c.list_tokens("56", types=(t,))[:a.n]:
            r = urllib_post(AUDIT_URL, {"binanceChainId": "56", "contractAddress": tok["contractAddress"],
                                        "requestId": str(uuid.uuid4())})
            d = r.get("data") or {}
            rows.append({"symbol": tok["symbol"], "type": t, "contract": tok["contractAddress"],
                         "hasResult": d.get("hasResult"), "isSupported": d.get("isSupported"),
                         "riskLevel": d.get("riskLevel"), "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    with open(a.out, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(json.dumps({"tokens": len(rows), "available": sum(bool(r["hasResult"] and r["isSupported"]) for r in rows)}))


if __name__ == "__main__":
    main()
