"""Re-record the test fixtures from the live Manifold API (network). Tests themselves run offline.

  python tests/record_fixtures.py
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from manifold_asof import client, iso, to_ms  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent / "fixtures"
KEEP = ("id", "question", "url", "outcomeType", "mechanism", "createdTime", "closeTime", "resolutionTime", "isResolved",
        "resolution", "probability", "volume", "uniqueBettorCount", "lastUpdatedTime", "lastBetTime")
MARKETS = {
    "gGnxdT90w0mxEPTVwD9S": "resolved YES before planned close (ForecastBench 2024-07-21 had close 2024-11-06)",
    "ylIXgDeMDCYkltnmAlpZ": "resolved NO before planned close (ForecastBench 2024-07-21 had close 2024-12-01)",
    "4puVWhIkvQiHnTxbH4NL": "creator moved close to 2024-09-13 08:00, resolved 09:13 (snapshot had 2024-12-31)",
    "YrQ6jZbI1xhpY2TyQvJ9": "close extended from 2025-01-01 (snapshot) to 2027-01-01",
    "Nc8DWWUyYm6CQp6PvOEv": "closed as planned 2024-12-31, resolved shortly after",
    "ex1RJ8NMa2JT0zcrPtQg": "closed as planned, resolved 98 seconds after close (must not be flagged)",
}
BETS = {("VB1RhUVlnNfhclAh4LvR", "2024-08-05T00:00:00Z"), ("gGnxdT90w0mxEPTVwD9S", "2024-07-01T00:00:00Z")}


def main():
    HERE.mkdir(exist_ok=True)
    markets = []
    for mid, why in MARKETS.items():
        m = client.market(mid)
        markets.append({**{k: m.get(k) for k in KEEP}, "_why": why})
    for mid in {b[0] for b in BETS} - set(MARKETS):
        m = client.market(mid)
        markets.append({**{k: m.get(k) for k in KEEP}, "_why": "asof example"})
    (HERE / "markets.json").write_text(json.dumps(markets, indent=1, ensure_ascii=False) + "\n")
    bets = {}
    for mid, at in sorted(BETS):
        bets[f"{mid}@{at}"] = [{k: b.get(k) for k in ("id", "createdTime", "probBefore", "probAfter", "outcome", "amount",
                                                     "isRedemption", "isCancelled")}
                               for b in client.bets_before(mid, to_ms(at), limit=5)]
    (HERE / "bets.json").write_text(json.dumps(bets, indent=1) + "\n")
    print("recorded", len(markets), "markets and", len(bets), "bet windows;", iso(to_ms("2024-08-05")))


if __name__ == "__main__":
    main()
