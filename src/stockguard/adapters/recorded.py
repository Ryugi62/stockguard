"""Offline mode: serve recorded real responses (fixtures/recorded/*.json) through the same ports as the live client.

Judges can run the whole product with no key, no wallet and no network. Recorded with scripts/record_demo_fixtures.py.
"""
import json
import os
from typing import Dict, List, Optional

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DEFAULT_RECORDING = os.path.join(ROOT, "fixtures", "recorded", "demo-2026-10-04.json")


def _load(path: Optional[str]) -> Dict:
    with open(path or DEFAULT_RECORDING) as f:
        return json.load(f)


class RecordedRwaClient:
    def __init__(self, path: Optional[str] = None):
        self.rec = _load(path)
        self.captured_at = self.rec.get("captured_at_utc")

    def list_tokens(self, chain_id: str = "56") -> List[Dict]:
        return [t for t in self.rec["list"] if str(t.get("chainId")) == str(chain_id)]

    def market_status(self) -> Dict:
        return self.rec["market_status"]

    def dynamic(self, address: str, chain_id: str = "56") -> Dict:
        try:
            return self.rec["dynamic"][address]
        except KeyError:
            raise LookupError(f"{address} is not in the offline recording — run without --offline for live data")

    def meta(self, address: str, chain_id: str = "56") -> Dict:
        return self.rec["meta"].get(address) or {}

    def kline(self, address: str, interval: str = "1d", limit: int = 10, chain_id: str = "56") -> List:
        return (self.rec.get("kline") or {}).get(address, [])


class RecordedSupply:
    def __init__(self, path: Optional[str] = None):
        self.supply = _load(path).get("supply", {})

    def total_supply(self, token: str) -> Optional[float]:
        return self.supply.get(token)
