"""Reproduce seven findings from docs/dx-findings.md, one screen each (SPEC UC-7).

    python3 scripts/reproduce_findings.py            # live public endpoints, no key
    python3 scripts/reproduce_findings.py --offline  # recorded real responses (fixtures/)

Each screen prints the exact request, the raw fields that matter, what we expected, and whether the
finding reproduces right now. F1 is session-dependent (6 findings reproduce every time, F1 outside
regular hours); the screen says so instead of pretending. Standard library only.
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import uuid
from typing import Callable, Dict, List, Optional

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FIX = os.path.join(ROOT, "fixtures")

BASE = "https://www.binance.com/bapi/defi"
LIST = BASE + "/v1/public/wallet-direct/buw/wallet/market/token/rwa/stock/detail/list/ai?type={t}"
DYNAMIC = BASE + "/v2/public/wallet-direct/buw/wallet/market/token/rwa/dynamic/ai?chainId=56&contractAddress={a}"
MARKET = BASE + "/v1/public/wallet-direct/buw/wallet/market/token/rwa/market/status/ai"
KLINE = BASE + "/v1/public/wallet-direct/buw/wallet/dex/market/token/kline/ai?chainId=56&contractAddress={a}&interval=1d&limit=10"
AUDIT = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/security/token/audit"

NFLXON = "0x7048f5227b032326cc8dbc53cf3fddd947a2c757"
NFLXX = "0xa6a65ac27e76cd53cb790473e4345c46e5ebf961"
NFLXB = "0xd6829ea836b6fa224d099d40e54b31262f874631"
DOCUMENTED_SESSIONS = {"premarket", "regular", "postmarket", "overnight", "closed", "pause"}   # tokenized-securities SKILL.md L328


def _f(x) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# --- checks: pure functions over the `data` part of each response ---------------------------------

def _day(ms) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(float(ms) / 1000))


def check_f10(list_data: List[Dict], dynamic: Dict, address: str, recorded_dynamic: Optional[Dict] = None,
              klines: Optional[List] = None) -> Dict:
    row = next((x for x in list_data if str(x.get("contractAddress", "")).lower() == address and str(x.get("chainId")) == "56"), {})
    lm, dm = row.get("multiplier"), (dynamic.get("tokenInfo") or {}).get("sharesMultiplier")
    a, b = _f(lm), _f(dm)
    obs = {"list multiplier": lm, "dynamic sharesMultiplier": dm,
           "tokenInfo.price": (dynamic.get("tokenInfo") or {}).get("price"), "stockInfo.price": (dynamic.get("stockInfo") or {}).get("price")}
    if recorded_dynamic is not None:
        obs["tokenInfo.price unchanged since recording"] = obs["tokenInfo.price"] == (recorded_dynamic.get("tokenInfo") or {}).get("price")
    traded = [k for k in klines or [] if isinstance(k, list) and len(k) > 6 and (_f(k[5]) or 0) > 0]
    if traded:      # F16: the token price is the last trade's close, and only the K-line says when that was
        last = traded[-1]
        obs["last K-line candle with volume"] = f"{_day(last[0])} close {float(last[4]):.4f} volume {float(last[5]):.2f}"
        tp = _f(obs["tokenInfo.price"])
        obs["tokenInfo.price == that close"] = bool(tp and abs(float(last[4]) / tp - 1) < 1e-9)
    return {"observed": obs, "expected": "the same multiplier from the list and the price feed",
            "reproduced": bool(a and b and abs(a - b) / max(a, b) > 0.01)}


def check_f9(dyn_xstock: Dict, dyn_bstock: Dict) -> Dict:
    sx, sb = dyn_xstock.get("statusInfo") or {}, dyn_bstock.get("statusInfo") or {}
    obs = {"NFLXx statusInfo.marketStatus": sx.get("marketStatus"), "NFLXx reasonCode": sx.get("reasonCode"),
           "NFLXB statusInfo.marketStatus": sb.get("marketStatus"), "NFLXB reasonCode": sb.get("reasonCode")}
    return {"observed": obs, "expected": "a market session for every token, as Ondo tokens have",
            "reproduced": sx.get("marketStatus") is None or sb.get("marketStatus") is None}


def check_f12(dyn_bstock: Dict) -> Dict:
    p = (dyn_bstock.get("stockInfo") or {}).get("price")
    return {"observed": {"NFLXB stockInfo.price": p, "NFLXB tokenInfo.price": (dyn_bstock.get("tokenInfo") or {}).get("price")},
            "expected": "an underlying stock price to compare with", "reproduced": p is None}


def check_f1(dyn_ondo: Dict) -> Dict:
    t, s, m = _f((dyn_ondo.get("tokenInfo") or {}).get("price")), _f((dyn_ondo.get("stockInfo") or {}).get("price")), \
        _f((dyn_ondo.get("tokenInfo") or {}).get("sharesMultiplier"))
    session = (dyn_ondo.get("statusInfo") or {}).get("marketStatus")
    gap_bp = abs(s * m / t - 1) * 1e4 if (t and s and m) else None
    near_copy = gap_bp is not None and session != "regular" and gap_bp <= 50
    return {"observed": {"tokenInfo.price": t, "stockInfo.price": s, "sharesMultiplier": m,
                         "gap between stockInfo.price x multiplier and tokenInfo.price (bp)": None if gap_bp is None else round(gap_bp, 3),
                         "statusInfo.marketStatus": session},
            "expected": "outside regular hours: stockInfo.price null or an independent quote (SKILL.md L473), not the token price within 50 bp",
            "reproduced": near_copy,
            "note": "session-dependent: exact on weekends (432/458 tokens), within 50 bp for 449/458 Ondo tokens overnight 2026-10-07; NO = independent right now"}


def check_f2(market: Dict) -> Dict:
    ms = market.get("marketStatus")
    has_obj = isinstance(market.get("offhours"), dict)
    return {"observed": {"marketStatus": ms, "undocumented offhours object": has_obj, "offhours": market.get("offhours")},
            "expected": "only the documented fields and enum values (premarket, regular, postmarket, overnight, closed, pause)",
            "reproduced": has_obj or (ms is not None and ms not in DOCUMENTED_SESSIONS)}


def check_f7(klines: List, others: Optional[Dict[str, List]] = None) -> Dict:
    vols = [str(k[5]) for k in klines if isinstance(k, list) and len(k) > 5]
    zero = sum(1 for v in vols if _f(v) == 0)
    obs = {"NFLXon candles": len(vols), "NFLXon candles with volume 0": zero, "NFLXon close prices move": len({k[4] for k in klines}) > 1}
    for sym, ks in (others or {}).items():   # xStocks/bStocks candles do carry volume: the gap is Ondo-specific
        obs[f"{sym} candles with volume > 0"] = sum(1 for k in ks if isinstance(k, list) and len(k) > 5 and (_f(k[5]) or 0) > 0)
    return {"observed": obs, "expected": "some volume on Ondo candles whose price moves, as xStocks/bStocks candles have",
            "reproduced": bool(vols) and zero == len(vols)}


def check_f14(audit: Dict) -> Dict:
    obs = {k: audit.get(k) for k in ("hasResult", "isSupported", "riskLevel", "riskLevelEnum")}
    return {"observed": obs, "expected": "an audit result for a token from the official RWA list",
            "reproduced": not (audit.get("hasResult") and audit.get("isSupported"))}


# --- sources ---------------------------------------------------------------------------------------

def _get(url: str) -> Dict:
    req = urllib.request.Request(url, headers={"User-Agent": "stockguard-reproduce/1.0", "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def _post(url: str, payload: Dict) -> Dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={
        "Content-Type": "application/json", "source": "agent", "User-Agent": "binance-web3/1.4 (Skill)", "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def _fx(name: str) -> Dict:
    with open(os.path.join(FIX, name)) as f:
        return json.load(f)


class OfflineSource:
    """Recorded real responses: weekend 2026-10-03/04 (fixtures/)."""
    label = "recorded responses, 2026-10-03/04 (weekend)"

    def list_xstocks(self) -> List[Dict]:
        return _fx("list_nflx_three_issuers.json")["data"]

    def dynamic(self, address: str) -> Dict:
        name = {NFLXON: "dynamic_nflx_weekend.json", NFLXX: "dynamic_nflxx_weekend.json", NFLXB: "dynamic_nflxb_weekend.json"}[address]
        return _fx(name)["data"]

    def market(self) -> Dict:
        return _fx("market_status_weekend.json")["data"]

    def kline(self, address: str) -> List:
        return _fx("kline_nflx_1d.json")["data"]["klineInfos"] if address == NFLXON else []   # only Ondo was recorded

    def audit(self, address: str) -> Dict:
        return _fx(os.path.join("recorded", "demo-2026-10-04.json"))["audit"][address]["data"]

    def recorded_dynamic(self, address: str) -> Optional[Dict]:
        return None


class LiveSource(OfflineSource):
    label = "live public endpoints"

    def __init__(self, get: Callable[[str], Dict] = _get, post: Callable[[str, Dict], Dict] = _post):
        self._get, self._post = get, post

    def list_xstocks(self):
        return self._get(LIST.format(t=2))["data"]

    def dynamic(self, address):
        return self._get(DYNAMIC.format(a=address))["data"]

    def market(self):
        return self._get(MARKET)["data"]

    def kline(self, address):
        return self._get(KLINE.format(a=address))["data"]["klineInfos"]

    def audit(self, address):
        return self._post(AUDIT, {"binanceChainId": "56", "contractAddress": address, "requestId": str(uuid.uuid4())})["data"]

    def recorded_dynamic(self, address):
        return OfflineSource.dynamic(self, address)


SCREENS = [
    ("F10", "NFLXx: the token list and the price feed disagree on the multiplier (+ F16: its price is an old trade)",
     [LIST.format(t=2), DYNAMIC.format(a=NFLXX), KLINE.format(a=NFLXX)],
     lambda s: check_f10(s.list_xstocks(), s.dynamic(NFLXX), NFLXX, s.recorded_dynamic(NFLXX), s.kline(NFLXX))),
    ("F9", "xStocks and bStocks report no market session",
     [DYNAMIC.format(a=NFLXX), DYNAMIC.format(a=NFLXB)], lambda s: check_f9(s.dynamic(NFLXX), s.dynamic(NFLXB))),
    ("F12", "bStocks carry no underlying stock price", [DYNAMIC.format(a=NFLXB)], lambda s: check_f12(s.dynamic(NFLXB))),
    ("F1", "Ondo outside regular hours: token price and stock quote are pinned together (stock x multiplier = token)",
     [DYNAMIC.format(a=NFLXON)], lambda s: check_f1(s.dynamic(NFLXON))),
    ("F2", "Market status carries fields and values that are not documented", [MARKET], lambda s: check_f2(s.market())),
    ("F7", "Ondo K-line volume is always 0 (xStocks and bStocks candles do carry volume)",
     [KLINE.format(a=NFLXON), KLINE.format(a=NFLXX), KLINE.format(a=NFLXB)],
     lambda s: check_f7(s.kline(NFLXON), {"NFLXx": s.kline(NFLXX), "NFLXB": s.kline(NFLXB)})),
    ("F14", "The wallet's required token audit has no data for a listed stock token",
     ["POST " + AUDIT + '  {"binanceChainId":"56","contractAddress":"' + NFLXON + '","requestId":"<uuid4>"}'],
     lambda s: check_f14(s.audit(NFLXON))),
]


def run(source) -> List[Dict]:
    out = []
    for fid, title, calls, fn in SCREENS:
        try:
            r = fn(source)
        except Exception as e:          # one failed call must not hide the other screens
            r = {"observed": {}, "expected": "", "reproduced": False, "error": f"{type(e).__name__}: {e}"}
        out.append({"id": fid, "title": title, "calls": calls, **r})
    return out


def render(results: List[Dict], mode: str) -> str:
    lines = [f"StockGuard: {len(results)} DX findings, {mode}, run at {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}", ""]
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}/{len(results)}] {r['id']}  {r['title']}")
        lines += [f"  {c}" for c in r["calls"]]
        for k, v in r["observed"].items():
            lines.append(f"    {k}: {json.dumps(v)}")
        if r.get("expected"):
            lines.append(f"  expected: {r['expected']}")
        if r.get("error"):
            lines.append(f"  error: {r['error']}")
        lines.append(f"  reproduced: {'YES' if r['reproduced'] else 'NO'}" + (f"  ({r['note']})" if r.get("note") and not r["reproduced"] else ""))
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--offline", action="store_true", help="use recorded real responses (no network)")
    ap.add_argument("--json", action="store_true", help="print JSON instead of screens")
    a = ap.parse_args(argv)
    src = OfflineSource() if a.offline else LiveSource()
    res = run(src)
    print(json.dumps(res, indent=1) if a.json else render(res, src.label))
    return 0


if __name__ == "__main__":
    sys.exit(main())
