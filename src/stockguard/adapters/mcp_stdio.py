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
            "usd_amount": {"type": "number", "description": "Alternative to token_qty: order size in US dollars; "
                                                            "the tool returns the correct token quantity"},
        },
        "required": ["ticker"],
    },
}


GATE_TOOL = {
    "name": "guard_agentic_wallet_swap",
    "description": ("Call this BEFORE any Binance Agentic Wallet `baw market-order swap` or `baw limit-order buy|sell` "
                    "of a tokenized US stock on BNB Chain. Returns PROCEED, CONFIRM (show the reasons and get an explicit yes), ASK (the ticker is "
                    "several tokens — ask which issuer) or REFUSE (do not trade), plus the exact baw quote/swap/poll "
                    "(or limit-order) commands sized in the right units, with the token audit result. Pass the output of `baw wallet settings --json` as "
                    "wallet_settings to respect the wallet's daily quota and allowed-token list. Never signs."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Token symbol (NFLXon, NFLXx, NFLXB), ticker or contract"},
            "usd_amount": {"type": "number", "description": "Order size in US dollars"},
            "token_qty": {"type": "number", "description": "SELL only: size in tokens instead of usd_amount"},
            "side": {"type": "string", "enum": ["BUY", "SELL"], "default": "BUY"},
            "pay_with": {"type": "string", "enum": ["USDT", "USDC", "USD1", "U", "BNB"], "default": "USDT"},
            "wallet_settings": {"type": "object", "description": "Output of `baw wallet settings --json` (optional)"},
            "slippage": {"type": "number", "description": "Percent; omitted = capped at 1% (not the wallet's \"auto\"), disclosed"},
            "wallet_quote": {"type": "object", "description": "Output of the emitted `baw market-order quote … --json`: "
                                                              "re-gates on the wallet's own price before the swap "
                                                              "(>1% worse: CONFIRM, >5%: REFUSE)"},
            "trigger_share_price": {"type": "number", "description": "Limit order at this price per SHARE; the tool "
                                                                    "returns the per-TOKEN trigger for `baw limit-order`"},
            "pay_price": {"type": "number", "description": "USD price of BNB when pay_with is BNB"},
        },
        "required": ["ticker"],
    },
}


def _gate(guard, a, auditor=None):
    import time
    from stockguard.adapters.agentic_wallet import commands, parse_wallet_settings
    from stockguard.application.wallet_gate import gate_swap
    out = gate_swap(guard, a["ticker"], float(a["usd_amount"]) if a.get("usd_amount") else None,
                    side=a.get("side", "BUY"), token_qty=a.get("token_qty"),
                    pay_with=a.get("pay_with", "USDT"), settings=parse_wallet_settings(a.get("wallet_settings")),
                    auditor=auditor, slippage=a.get("slippage"), trigger_share_price=a.get("trigger_share_price"),
                    pay_price=a.get("pay_price"), today=time.strftime("%Y-%m-%d", time.gmtime()))
    out["baw_commands"] = commands(out)
    if a.get("wallet_quote"):
        from stockguard.application.trade import apply_wallet_quote
        out = apply_wallet_quote(out, a["wallet_quote"], pay_price=a.get("pay_price"))
    return out


def handle(guard, msg, auditor=None):
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        res = {"protocolVersion": params.get("protocolVersion", "2024-11-05"),
               "capabilities": {"tools": {}}, "serverInfo": {"name": "stockguard", "version": "0.3.0"}}
    elif method == "tools/list":
        res = {"tools": [TOOL, GATE_TOOL]}
    elif method == "tools/call" and params.get("name") == GATE_TOOL["name"]:
        a = params.get("arguments") or {}
        if not isinstance(a.get("ticker"), str) or not a["ticker"].strip() \
                or not ((isinstance(a.get("usd_amount"), (int, float)) and a["usd_amount"] > 0)
                        or (isinstance(a.get("token_qty"), (int, float)) and a["token_qty"] > 0)):
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602,
                    "message": "arguments 'ticker' (string) and 'usd_amount' or 'token_qty' (positive number) are required"}}
        try:
            res = {"content": [{"type": "text", "text": json.dumps(_gate(guard, a, auditor))}], "isError": False}
        except ValueError as e:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": str(e)}}
        except Exception as e:   # never take the server down; the agent sees an error result
            res = {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}
    elif method == "tools/call":
        if params.get("name") != TOOL["name"]:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown tool"}}
        a = params.get("arguments") or {}
        if not isinstance(a.get("ticker"), str) or not a["ticker"].strip():
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "argument 'ticker' (string) is required"}}
        if a.get("side", "BUY") not in ("BUY", "SELL"):
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "side must be BUY or SELL"}}
        try:
            r = guard.check(a["ticker"], a.get("side", "BUY"), a.get("token_qty"), usd_amount=a.get("usd_amount"))
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


def run(guard, fin, fout, auditor=None):
    for line in fin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            out = handle(guard, msg, auditor)
        if out is not None:
            fout.write(json.dumps(out) + "\n")
            fout.flush()
