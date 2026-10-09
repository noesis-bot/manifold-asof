"""Minimal read-only client for the public Manifold API (no key needed)."""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

API = "https://api.manifold.markets/v0"
UA = "manifold-asof/0.1 (+https://github.com/noesis-bot/manifold-asof)"


def _get(path: str, params: dict | None = None, retries: int = 3):
    url = f"{API}/{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))


def market(market_id: str) -> dict:
    return _get(f"market/{market_id}")


def bets_before(market_id: str, at_ms: int, limit: int = 20) -> list[dict]:
    """Most recent bets strictly before `at_ms`, newest first."""
    bets = _get("bets", {"contractId": market_id, "beforeTime": at_ms, "limit": limit, "order": "desc"})
    return [b for b in bets if b.get("createdTime", 0) < at_ms]
