from stockguard.adapters.bsc_rpc import BscRpc


def test_total_supply_scales_by_decimals():
    def post(url, payload):
        data = payload["params"][0]["data"]
        return {"result": "0x12" if data == "0x313ce567" else "0x00000000000000000000000000000000000000000000000bfadd7631ed2e89e2"}
    v = BscRpc(post=post).total_supply("0x7048f5227b032326cc8dbc53cf3fddd947a2c757")
    assert abs(v - 220.990919) < 1e-3
