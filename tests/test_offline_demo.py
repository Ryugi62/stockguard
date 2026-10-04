"""Judges' path: clone -> one command -> demo, with no key, no wallet and no network (recorded real responses)."""
import io, json, os, subprocess, sys, time, urllib.request
from contextlib import redirect_stdout

import pytest

from stockguard.adapters.recorded import RecordedRwaClient, RecordedSupply, DEFAULT_RECORDING
from stockguard.adapters.mapping import to_snapshot
from stockguard.application.service import Guard
from stockguard.infrastructure.cli import main

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network used in offline mode")
    monkeypatch.setattr(urllib.request, "urlopen", boom)


def test_recording_is_real_and_dated():
    rec = json.load(open(DEFAULT_RECORDING))
    assert rec["captured_at_utc"].startswith("2026-10-04")
    syms = {t["symbol"] for t in rec["list"]}
    assert {"NFLXon", "NFLXx", "NFLXB", "KLACon", "ENLVon"} <= syms
    assert all(t.get("synthetic") for t in rec["list"] if t["symbol"].startswith("SPLITDEMO"))


def test_offline_guard_checks_without_network(no_network):
    g = Guard(RecordedRwaClient(), to_snapshot, onchain=RecordedSupply())
    r = g.check("NFLXon", usd_amount=1000)
    assert r["symbol"] == "NFLXon" and r["verdict"] in ("WARN", "BLOCK") and r["onchain_supply"]


def test_cli_offline_flag(no_network, capsys):
    main(["check", "KLACon", "--usd", "1000", "--offline"])
    d = json.loads(capsys.readouterr().out)
    assert d["symbol"] == "KLACon" and abs(d["usd_amount"] - 1000) < 0.01


def test_demo_runs_offline_fast_and_tells_the_story(no_network):
    buf = io.StringIO()
    t0 = time.time()
    with redirect_stdout(buf):
        main(["demo"])
    out = buf.getvalue()
    assert time.time() - t0 < 5
    for must in ("NFLXon", "NFLXx", "NFLXB", "1 token = 10 shares", "REFUSE", "CONFIRM",
                 "baw market-order swap", "recorded", "SPLITDEMO"):
        assert must in out, must


def test_repo_root_one_command(tmp_path):
    p = subprocess.run([sys.executable, os.path.join(ROOT, "demo.py")], capture_output=True, text=True, timeout=60,
                       cwd=str(tmp_path), env={**os.environ, "PYTHONPATH": ""})
    assert p.returncode == 0, p.stderr
    assert "StockGuard demo" in p.stdout and "baw market-order" in p.stdout
