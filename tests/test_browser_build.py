"""In-browser build (SPEC UC-8): the same Python package runs in Pyodide; I/O comes in through injected functions."""
import json
import os
import subprocess
import sys
import zipfile

from stockguard.adapters.browser import BrowserApp
from tests_support import load

ROOT = os.path.join(os.path.dirname(__file__), "..")
NFLXON = "0x7048f5227b032326cc8dbc53cf3fddd947a2c757"


def fake_get(url):
    if "/list/ai" in url:
        return {"code": "000000", "data": load("list_sample.json") if "type=1" in url else []}
    if "/market/status/ai" in url:
        return {"code": "000000", "data": load("market_status_weekend.json")}
    if "/dynamic/ai" in url and NFLXON in url:
        return {"code": "000000", "data": load("dynamic_nflx_weekend.json")}
    if "/meta/ai" in url:
        return {"code": "000000", "data": {}}
    raise OSError("no fixture for " + url)


def fake_post(url, payload):
    return {"jsonrpc": "2.0", "id": 1, "result": hex(18) if payload["params"][0]["data"] == "0x313ce567" else hex(220 * 10 ** 18)}


def test_check_through_injected_io_returns_status_and_body():
    app = BrowserApp(fake_get, fake_post)
    status, body = json.loads(app.handle("/api/check?ticker=NFLXon&side=BUY&usd=1000"))
    assert status == 200 and body["symbol"] == "NFLXon" and body["verdict"] == "WARN"
    assert body["agent_gate"]["action"] in ("CONFIRM", "PROCEED")


def test_browser_audit_is_reported_unavailable_not_skipped():
    app = BrowserApp(fake_get, fake_post)
    status, body = json.loads(app.handle("/api/check?ticker=NFLXon&usd=100"))
    assert any("temporarily unavailable" in r for r in body["agent_gate"]["reasons"])


def test_tickers_and_bad_path():
    app = BrowserApp(fake_get, fake_post)
    status, names = json.loads(app.handle("/api/tickers"))
    assert status == 200 and "NFLXon" in names
    assert json.loads(app.handle("/nope"))[0] == 404


def test_build_site_writes_page_boot_and_package(tmp_path):
    subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "build_site.py"), "--out", str(tmp_path)], check=True)
    html = (tmp_path / "index.html").read_text()
    assert '<script src="boot.js"></script>' in html and 'fetch("/api/' not in html
    assert (tmp_path / "boot.js").read_text().count("pyodide") >= 2
    names = zipfile.ZipFile(tmp_path / "stockguard.zip").namelist()
    assert "stockguard/adapters/browser.py" in names and "stockguard/domain/guard.py" in names
    assert not any("__pycache__" in n for n in names)
