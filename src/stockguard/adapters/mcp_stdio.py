"""Minimal MCP (JSON-RPC 2.0 over stdio, newline-delimited) exposing one tool to LLM agents."""
import json

TOOL = {
    "name": "check_tokenized_stock_trade",
    "description": ("Before buying or selling a tokenized US stock on BNB Chain, check whether the trade is safe "
                    "right now: market session, corporate-action pauses (dividend, split, earnings), how many real "
                    "shares one token represents (multiplier), and whether an independent reference price exists. "
                    "Returns ALLOW, WARN or BLOCK with plain-English reasons."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Underlying ticker (AAPL), token symbol (AAPLon) or contract"},
            "side": {"type": "string", "enum": ["BUY", "SELL"], "default": "BUY"},
            "token_qty": {"type": "number", "default": 1, "description": "Quantity in TOKENS, not shares"},
        },
        "required": ["ticker"],
    },
}


def handle(guard, msg):
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        res = {"protocolVersion": params.get("protocolVersion", "2024-11-05"),
               "capabilities": {"tools": {}}, "serverInfo": {"name": "stockguard", "version": "0.1.0"}}
    elif method == "tools/list":
        res = {"tools": [TOOL]}
    elif method == "tools/call":
        if params.get("name") != TOOL["name"]:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown tool"}}
        a = params.get("arguments") or {}
        try:
            r = guard.check(a["ticker"], a.get("side", "BUY"), float(a.get("token_qty", 1)))
            res = {"content": [{"type": "text", "text": json.dumps(r)}], "isError": False}
        except Exception as e:
            res = {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}
    elif method and method.startswith("notifications/"):
        return None
    elif method == "ping":
        res = {}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": res}


def run(guard, fin, fout):
    for line in fin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            out = handle(guard, msg)
        if out is not None:
            fout.write(json.dumps(out) + "\n")
            fout.flush()
