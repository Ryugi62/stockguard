"""Check that the numbers the docs quote match the raw data and the test suite (no network).

    python3 scripts/check_numbers.py                 # README, docs, skill, web page, demo
    python3 scripts/check_numbers.py form.md         # also check extra files (e.g. the submission form text)
    python3 scripts/check_numbers.py --json

Facts are recomputed from `data/` every run; each "N of M" claim with a known denominator, and each "N tests"
claim, must match. Exit 1 on any mismatch.

Metric definitions (one sentence each, used in README, the form and the DX report):
- audit_no_data: stock tokens on BNB Chain for which the Token Security Audit returned hasResult=false or
  isSupported=false, out of all stock tokens in the RWA list (2026-10-04 scan, data/audit-all-20261004.jsonl).
- ondo_pinned: Ondo tokens whose weekend stockInfo.price × multiplier equals tokenInfo.price to 1e-6, out of all
  Ondo tokens (2026-10-03 rescan, data/scan-20261003-weekend.jsonl).
"""
import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_FILES = ["README.md", "docs/dx-findings.md", "skills/stockguard-pretrade/SKILL.md",
                 "src/stockguard/web/index.html", "src/stockguard/infrastructure/demo.py"]


def _rows(name):
    with open(os.path.join(ROOT, "data", name), encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def facts():
    audit = [r for r in _rows("audit-all-20261004.jsonl") if r.get("type") in (1, 2, 3)]
    weekend = _rows("scan-20261003-weekend.jsonl")
    allx = [r for r in _rows("scan-20261004-all-issuers.jsonl") if str(r.get("issuer", "")).startswith("xStocks")
            or str(r.get("symbol", "")).endswith("x")]
    n_tests = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"], cwd=ROOT,
                             capture_output=True, text=True).stdout
    m = re.search(r"(\d+) tests? collected", n_tests)
    return {
        "audit_total": len(audit),
        "audit_no_data": sum(1 for r in audit if not (r.get("hasResult") and r.get("isSupported"))),
        "ondo_total": len(weekend),
        "ondo_pinned": sum(1 for r in weekend if r.get("reference_derived")),
        "xstocks_total": len(allx),
        "xstocks_multiplier_conflict": sum(1 for r in allx if r.get("multiplier_conflict")),
        "tests": int(m.group(1)) if m else None,
    }


def problems_in(text, f, where):
    out = []
    by_denominator = {f["audit_total"]: f["audit_no_data"], f["ondo_total"]: f["ondo_pinned"]}
    for n, d in re.findall(r"\b(\d{2,3}) (?:of|/) (?:the |all )?(\d{3})\b", text):
        n, d = int(n), int(d)
        if d in by_denominator and n != by_denominator[d] and n != d:
            out.append(f"{where}: '{n} of {d}' — data says {by_denominator[d]} of {d}")
    if f["tests"] is not None:
        for n in re.findall(r"\b(\d{2,4}) (?:offline )?tests\b", text):
            if int(n) != f["tests"]:
                out.append(f"{where}: '{n} tests' — pytest collects {f['tests']}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="*", help="extra files to check")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    f = facts()
    probs = []
    for p in DEFAULT_FILES + a.files:
        full = p if os.path.isabs(p) else os.path.join(ROOT, p)
        probs += problems_in(open(full, encoding="utf-8").read(), f, os.path.relpath(full, ROOT) if full.startswith(ROOT) else p)
    if a.json:
        print(json.dumps({"facts": f, "problems": probs}, ensure_ascii=False))
    else:
        print(json.dumps(f))
        print("\n".join(probs) or "OK — every quoted number matches the data")
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
