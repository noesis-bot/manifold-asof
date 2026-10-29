"""Re-record the test fixtures from the live Manifold API (network). Tests themselves run offline.

  python tests/record_fixtures.py               # all fixtures
  python tests/record_fixtures.py --only-multi  # only tests/fixtures/multi.json
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


# Multiple-choice markets for asof. Only a few answers are kept per market so the fixture stays small.
MULTI = {
    ("Z9uy9T4q4rAfq4sGzPA0", "2024-08-30T00:00:00Z"): (None, "answers sum to one, resolved as a whole after `at`"),
    ("UU79AmfRkcUW9aVA2jIK", "2024-01-10T00:00:00Z"): (
        ["6e036a5c16fc", "2c034b3145a0", "7c1d266ea77f", "80176651146a", "9b7c13aa5998", "bb37edb618e5"],
        "independent answers resolved one by one, answers added after `at`"),
}
ANSWER_KEEP = ("id", "index", "text", "createdTime", "isOther", "resolution", "resolutionTime", "resolutionProbability",
               "probability")


def record_multi():
    HERE.mkdir(exist_ok=True)
    out = {}
    for (mid, at), (keep, why) in sorted(MULTI.items()):
        m = client.market(mid)
        answers = [{k: a.get(k) for k in ANSWER_KEEP} for a in m.get("answers") or [] if keep is None or a["id"] in keep]
        market = {**{k: m.get(k) for k in KEEP}, "shouldAnswersSumToOne": m.get("shouldAnswersSumToOne"),
                  "answers": answers, "_why": why}
        bets = client.answer_bets_before({**m, "answers": answers}, to_ms(at), limit=3)
        bets = {aid: [{k: b.get(k) for k in ("id", "answerId", "createdTime", "probBefore", "probAfter", "outcome",
                                             "amount", "isRedemption", "isCancelled")} for b in bl]
                for aid, bl in bets.items()}
        out[f"{mid}@{at}"] = {"market": market, "bets": bets}
    (HERE / "multi.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print("recorded", len(out), "multiple-choice markets")


def main():
    if "--only-multi" in sys.argv:
        return record_multi()
    record_multi()
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
