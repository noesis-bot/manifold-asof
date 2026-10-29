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


def bets_before(market_id: str, at_ms: int, limit: int = 20, answer_id: str | None = None) -> list[dict]:
    """Most recent bets strictly before `at_ms`, newest first (optionally only those on one answer)."""
    params = {"contractId": market_id, "beforeTime": at_ms, "limit": limit, "order": "desc"}
    if answer_id:
        params["answerId"] = answer_id
    bets = _get("bets", params)
    return [b for b in bets if b.get("createdTime", 0) < at_ms]


def answer_bets_before(m: dict, at_ms: int, limit: int = 5) -> dict[str, list[dict]]:
    """For a multiple-choice market: {answerId: recent bets before at_ms}, one request per answer that existed then."""
    return {a["id"]: bets_before(m["id"], at_ms, limit, answer_id=a["id"])
            for a in m.get("answers") or [] if (a.get("createdTime") or 0) <= at_ms}
