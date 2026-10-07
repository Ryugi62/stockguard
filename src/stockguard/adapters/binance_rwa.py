"""Binance Web3 public RWA endpoints (no API key). Adapter layer: HTTP + retries only, no rules."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Dict, List, Optional, Sequence

from stockguard.domain.issuers import LIST_TYPES

BASE = "https://www.binance.com/bapi/defi"
PATHS = {
    "list": "/v1/public/wallet-direct/buw/wallet/market/token/rwa/stock/detail/list/ai",
    "meta": "/v1/public/wallet-direct/buw/wallet/market/token/rwa/meta/ai",
    "market_status": "/v1/public/wallet-direct/buw/wallet/market/token/rwa/market/status/ai",
    "asset_status": "/v1/public/wallet-direct/buw/wallet/market/token/rwa/asset/market/status/ai",
    "dynamic": "/v2/public/wallet-direct/buw/wallet/market/token/rwa/dynamic/ai",
    "kline": "/v1/public/wallet-direct/buw/wallet/dex/market/token/kline/ai",
}
HEADERS = {"Accept-Encoding": "identity", "User-Agent": "binance-web3/1.1 (Skill)"}


class RwaError(RuntimeError):
    pass


def urllib_get(url: str, timeout: float = 10.0) -> Dict:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class RwaClient:
    def __init__(self, http_get: Callable[[str], Dict] = urllib_get, retries: int = 3, backoff: float = 0.6,
                 sleep: Callable[[float], None] = time.sleep):
        self._get, self.retries, self.backoff, self._sleep = http_get, retries, backoff, sleep
        self.calls = 0

    def _call(self, key: str, **params) -> Dict:
        url = BASE + PATHS[key] + ("?" + urllib.parse.urlencode(params) if params else "")
        last: Optional[Exception] = None
        for attempt in range(self.retries):
            try:
                self.calls += 1
                body = self._get(url)
                if not isinstance(body, dict):
                    raise RwaError(f"{key}: non-JSON-object response")
                if body.get("success") is False or (body.get("code") not in (None, "000000")):
                    raise RwaError(f"{key}: code={body.get('code')} message={body.get('message')}")
                return body.get("data")
            except RwaError:
                raise
            except urllib.error.HTTPError as e:   # 4xx is our request's fault: retrying won't help (429 = slow down)
                if 400 <= e.code < 500 and e.code != 429:
                    raise RwaError(f"{key}: HTTP {e.code} — not retried")
                last = e
                self._sleep(self.backoff * (2 ** attempt) * (4 if e.code == 429 else 1))
            except Exception as e:  # network / decode / WAF HTML page
                last = e
                self._sleep(self.backoff * (2 ** attempt))
        raise RwaError(f"{key}: failed after {self.retries} attempts: {last}")

    def list_tokens(self, chain_id: str = "56", types: Sequence[int] = LIST_TYPES) -> List[Dict]:
        """All issuers: type 1 Ondo (…on), 2 xStocks (…x), 3 bStocks (…B)."""
        out: List[Dict] = []
        for t in types:
            data = self._call("list", type=t) or []
            out += [{**x, "type": x.get("type", t)} for x in data if str(x.get("chainId")) == str(chain_id)]
        return out

    def market_status(self) -> Dict:
        return self._call("market_status") or {}

    def asset_status(self, address: str, chain_id: str = "56") -> Dict:
        return self._call("asset_status", chainId=chain_id, contractAddress=address) or {}

    def dynamic(self, address: str, chain_id: str = "56") -> Dict:
        return self._call("dynamic", chainId=chain_id, contractAddress=address) or {}

    def meta(self, address: str, chain_id: str = "56") -> Dict:
        return self._call("meta", chainId=chain_id, contractAddress=address) or {}

    def kline(self, address: str, interval: str = "1d", limit: int = 10, chain_id: str = "56") -> List:
        data = self._call("kline", chainId=chain_id, contractAddress=address, interval=interval, limit=limit) or {}
        return data.get("klineInfos") or []
