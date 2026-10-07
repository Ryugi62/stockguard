"""scripts/reproduce_findings.py — each DX finding reproduces from the recorded real responses (SPEC UC-7)."""
import importlib.util
import json
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")
_spec = importlib.util.spec_from_file_location("reproduce_findings", os.path.join(ROOT, "scripts", "reproduce_findings.py"))
rf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rf)


def fx(name):
    with open(os.path.join(ROOT, "fixtures", name)) as f:
        return json.load(f)


def test_offline_run_reproduces_all_seven_in_order():
    results = rf.run(rf.OfflineSource())
    assert [r["id"] for r in results] == ["F10", "F9", "F12", "F1", "F2", "F7", "F14"]
    assert all(r["reproduced"] for r in results), [r["id"] for r in results if not r["reproduced"]]
    for r in results:
        assert r["calls"] and all(c.startswith("https://") or c.startswith("POST https://") for c in r["calls"])


def test_f10_multiplier_conflict_detected_and_not_when_equal():
    lst = fx("list_nflx_three_issuers.json")["data"]
    dyn = fx("dynamic_nflxx_weekend.json")["data"]
    r = rf.check_f10(lst, dyn, rf.NFLXX)
    assert r["observed"]["list multiplier"] == "1" and r["observed"]["dynamic sharesMultiplier"] == "10"
    assert r["reproduced"] is True
    same = dict(dyn, tokenInfo=dict(dyn["tokenInfo"], sharesMultiplier="1"))
    assert rf.check_f10(lst, same, rf.NFLXX)["reproduced"] is False


def test_f10_flags_token_price_unchanged_since_recording():
    dyn = fx("dynamic_nflxx_weekend.json")["data"]
    r = rf.check_f10(fx("list_nflx_three_issuers.json")["data"], dyn, rf.NFLXX, recorded_dynamic=dyn)
    assert r["observed"]["tokenInfo.price unchanged since recording"] is True


def test_f9_null_session_only_when_null():
    dx = fx("dynamic_nflxx_weekend.json")["data"]
    db = fx("dynamic_nflxb_weekend.json")["data"]
    assert rf.check_f9(dx, db)["reproduced"] is True
    ok = dict(db, statusInfo=dict(db["statusInfo"], marketStatus="closed"))
    assert rf.check_f9(dict(dx, statusInfo=dict(dx["statusInfo"], marketStatus="closed")), ok)["reproduced"] is False


def test_f12_bstock_stock_price_null():
    db = fx("dynamic_nflxb_weekend.json")["data"]
    assert rf.check_f12(db)["reproduced"] is True
    assert rf.check_f12(dict(db, stockInfo={"price": "69.1"}))["reproduced"] is False


def test_f1_derived_reference_price():
    d = fx("dynamic_nflx_weekend.json")["data"]
    assert rf.check_f1(d)["reproduced"] is True
    live = dict(d, stockInfo=dict(d["stockInfo"], price="69.165385"))   # an independent quote (seen 2026-10-07 04:38 UTC)
    assert rf.check_f1(live)["reproduced"] is False


def test_f2_undocumented_offhours_object_or_enum_value():
    m = fx("market_status_weekend.json")["data"]
    r = rf.check_f2(m)
    assert r["reproduced"] is True
    assert r["observed"]["undocumented offhours object"] is True
    assert rf.check_f2({"marketStatus": "regular", "nextOpenTime": 1, "nextCloseTime": 2})["reproduced"] is False
    assert rf.check_f2({"marketStatus": "offhours"})["reproduced"] is True


def test_f7_kline_volume_all_zero():
    k = fx("kline_nflx_1d.json")["data"]["klineInfos"]
    assert rf.check_f7(k)["reproduced"] is True
    assert rf.check_f7([[0, "1", "1", "1", "1", "5", 1]])["reproduced"] is False


def test_f14_audit_no_data_but_low_label():
    rec = fx(os.path.join("recorded", "demo-2026-10-04.json"))["audit"][rf.NFLXON]["data"]
    r = rf.check_f14(rec)
    assert r["reproduced"] is True and r["observed"]["riskLevelEnum"] == "LOW" and r["observed"]["riskLevel"] == -1
    assert rf.check_f14({"hasResult": True, "isSupported": True, "riskLevel": 0, "riskLevelEnum": "LOW"})["reproduced"] is False


def test_live_source_failure_is_reported_not_raised():
    class Boom(rf.OfflineSource):
        def dynamic(self, address):
            raise OSError("network down")
    results = rf.run(Boom())
    bad = [r for r in results if r.get("error")]
    assert bad and all(r["reproduced"] is False for r in bad)


def test_render_shows_endpoint_and_result_line():
    text = rf.render(rf.run(rf.OfflineSource()), mode="offline")
    assert "[1/7] F10" in text and "reproduced: YES" in text and "/dynamic/ai" in text
