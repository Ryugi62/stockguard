import json, os
FX = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def load(n):
    with open(os.path.join(FX, n)) as f:
        return json.load(f)["data"]


class FakeClient:
    def __init__(self):
        self.n = 0
    def list_tokens(self, chain_id="56"):
        return load("list_sample.json")
    def market_status(self):
        return load("market_status_weekend.json")
    def dynamic(self, address, chain_id="56"):
        self.n += 1
        if address.lower() == "0x7048f5227b032326cc8dbc53cf3fddd947a2c757":
            return load("dynamic_nflx_weekend.json")
        raise RuntimeError("no fixture")


