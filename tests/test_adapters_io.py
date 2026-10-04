from stockguard.adapters.mapping import to_snapshot
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
    run(Guard(FakeClient(), to_snapshot), fin, fout)
    out = [json.loads(l) for l in fout.getvalue().splitlines()]
    assert [o["id"] for o in out] == [1, 2, 3]
    payload = json.loads(out[2]["result"]["content"][0]["text"])
    assert payload["verdict"] == "WARN" and payload["share_equivalent"] == 10


def test_mcp_rejects_missing_ticker_and_sizes_by_usd():
    fin = io.StringIO("\n".join(json.dumps(m) for m in [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "check_tokenized_stock_trade", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "check_tokenized_stock_trade", "arguments": {"ticker": "NFLX", "usd_amount": 1000}}},
    ]) + "\n")
    fout = io.StringIO()
    run(Guard(FakeClient(), to_snapshot), fin, fout)
    out = [json.loads(l) for l in fout.getvalue().splitlines()]
    assert out[0]["error"]["code"] == -32602
    p = json.loads(out[1]["result"]["content"][0]["text"])
    assert abs(p["token_qty"] - 1000 / 670.62353) < 1e-9 and abs(p["share_equivalent"] - 10000 / 670.62353) < 1e-6


def test_mcp_lists_wallet_gate_tool_and_gates_a_swap():
    fin = io.StringIO("\n".join(json.dumps(m) for m in [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "guard_agentic_wallet_swap", "arguments": {"ticker": "NFLXon", "usd_amount": 100,
                    "wallet_settings": {"data": {"quotaLeft": 40, "tradeAllTokens": True}}}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "guard_agentic_wallet_swap", "arguments": {"ticker": "NFLXon"}}},
    ]) + "\n")
    fout = io.StringIO()
    run(Guard(FakeClient(), to_snapshot), fin, fout)
    out = [json.loads(l) for l in fout.getvalue().splitlines()]
    assert {t["name"] for t in out[0]["result"]["tools"]} == {"check_tokenized_stock_trade", "guard_agentic_wallet_swap"}
    g = json.loads(out[1]["result"]["content"][0]["text"])
    assert g["action"] == "CONFIRM" and g["approved_usd"] == 40 and g["baw_commands"][1].startswith("baw market-order swap --fromTokenQty 40.00")
    assert out[2]["error"]["code"] == -32602   # usd_amount required
