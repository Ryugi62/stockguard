"""Read-only BSC JSON-RPC (public node, no key): ERC-20 totalSupply/decimals of a token contract."""
import json
import urllib.request
from typing import Callable, Dict, Optional

DEFAULT_RPC = "https://bsc-dataseed.binance.org"
SEL_TOTAL_SUPPLY, SEL_DECIMALS = "0x18160ddd", "0x313ce567"


def urllib_post(url: str, payload: Dict, timeout: float = 8.0) -> Dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


class BscRpc:
    def __init__(self, url: str = DEFAULT_RPC, post: Callable[[str, Dict], Dict] = urllib_post):
        self.url, self._post = url, post

    def _call(self, to: str, data: str) -> int:
        body = self._post(self.url, {"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                                     "params": [{"to": to, "data": data}, "latest"]})
        if "error" in body:
            raise RuntimeError(f"eth_call failed: {body['error']}")
        return int(body["result"], 16)

    def total_supply(self, token: str) -> Optional[float]:
        dec = self._call(token, SEL_DECIMALS)
        return self._call(token, SEL_TOTAL_SUPPLY) / (10 ** dec)
