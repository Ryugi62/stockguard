"""Binance Web3 Token Security Audit (public, no key) — the pre-check the Agentic Wallet skill requires before a swap.

Spec: binance-skills-hub/skills/binance-web3/query-token-audit/SKILL.md (POST, UUID v4 requestId, `source: agent`).
"""
import json
import urllib.request
import uuid
from typing import Callable, Dict, Optional

from stockguard.domain.wallet_gate import AuditResult

AUDIT_URL = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/security/token/audit"
USER_AGENT = "StockGuard/0.5 (+https://github.com/Ryugi62/stockguard) binance-web3/1.4 (Skill)"
HEADERS = {"Content-Type": "application/json", "source": "agent", "Accept-Encoding": "identity",
           "User-Agent": USER_AGENT}


def urllib_post(url: str, payload: Dict, timeout: float = 8.0) -> Dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _num(x) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def parse_audit(raw: Optional[Dict]) -> AuditResult:
    d = (raw or {}).get("data") or {}
    if not (d.get("hasResult") and d.get("isSupported")):
        return AuditResult(available=False)      # skill: do NOT show riskLevel / riskItems in this case
    hits = tuple(x.get("title", "?") for item in d.get("riskItems") or [] for x in item.get("details") or []
                 if x.get("isHit"))
    extra = d.get("extraInfo") or {}
    return AuditResult(True, risk_level=int(d["riskLevel"]) if d.get("riskLevel") is not None else None, hits=hits,
                       buy_tax=_num(extra.get("buyTax")), sell_tax=_num(extra.get("sellTax")))


class TokenAuditClient:
    def __init__(self, post: Callable[[str, Dict], Dict] = urllib_post, chain_id: str = "56"):
        self._post, self.chain_id = post, chain_id

    def audit(self, address: str) -> AuditResult:
        try:
            return parse_audit(self._post(AUDIT_URL, {"binanceChainId": self.chain_id, "contractAddress": address,
                                                      "requestId": str(uuid.uuid4())}))
        except Exception as e:      # skill: unreachable -> tell the user and require acknowledgment
            return AuditResult(available=False, error=type(e).__name__)


class SkippedAudit:
    """--no-audit: the skip is never silent (security.md: "Never silently skip")."""
    def audit(self, address: str) -> AuditResult:
        return AuditResult(available=False, error="skipped")
