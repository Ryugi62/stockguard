import io, json
from stockguard.adapters.mcp_stdio import run
from stockguard.application.service import Guard
from tests_support import FakeClient


def test_mcp_roundtrip():
    fin = io.StringIO("\n".join(json.dumps(m) for m in [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "check_tokenized_stock_trade", "arguments": {"ticker": "NFLX", "token_qty": 1}}},
    ]) + "\n")
    fout = io.StringIO()
    run(Guard(FakeClient()), fin, fout)
    out = [json.loads(l) for l in fout.getvalue().splitlines()]
    assert [o["id"] for o in out] == [1, 2, 3]
    payload = json.loads(out[2]["result"]["content"][0]["text"])
    assert payload["verdict"] == "WARN" and payload["share_equivalent"] == 10
