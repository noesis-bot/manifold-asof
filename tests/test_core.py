"""Offline tests on recorded real Manifold markets (tests/fixtures, see record_fixtures.py)."""
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from manifold_asof import asof, audit_market, audit_markets, close_is_outcome_dependent, to_ms  # noqa: E402
from manifold_asof.cli import _snapshots  # noqa: E402

FX = ROOT / "tests" / "fixtures"
MARKETS = {m["id"]: m for m in json.loads((FX / "markets.json").read_text())}
BETS = json.loads((FX / "bets.json").read_text())
MULTI = json.loads((FX / "multi.json").read_text())


def codes(flags):
    return {f["code"] for f in flags}


class OutcomeDependentClose(unittest.TestCase):
    def test_early_resolution_yes_and_no_are_flagged(self):
        for mid in ("gGnxdT90w0mxEPTVwD9S", "ylIXgDeMDCYkltnmAlpZ", "VB1RhUVlnNfhclAh4LvR"):
            self.assertTrue(close_is_outcome_dependent(MARKETS[mid]), mid)
            self.assertIn("CLOSE_EQUALS_RESOLUTION", codes(audit_market(MARKETS[mid])), mid)

    def test_resolution_shortly_after_planned_close_is_not_flagged(self):
        # closed as planned, resolved 98 s later: a normal market, no leak without other evidence
        for mid in ("ex1RJ8NMa2JT0zcrPtQg", "Nc8DWWUyYm6CQp6PvOEv"):
            self.assertFalse(close_is_outcome_dependent(MARKETS[mid]), mid)
            self.assertEqual(codes(audit_market(MARKETS[mid])), set(), mid)

    def test_unresolved_market_is_not_flagged(self):
        self.assertFalse(close_is_outcome_dependent(MARKETS["YrQ6jZbI1xhpY2TyQvJ9"]))

    def test_creator_moved_close_needs_a_snapshot(self):
        m = MARKETS["4puVWhIkvQiHnTxbH4NL"]
        self.assertNotIn("CLOSE_EQUALS_RESOLUTION", codes(audit_market(m)))  # 73 min apart: invisible without history
        flags = audit_market(m, snapshot_close="2024-12-31T21:59:00+00:00")  # ForecastBench 2024-07-21
        self.assertIn("CLOSE_MOVED_EARLIER", codes(flags))

    def test_extension_is_a_warning_not_a_leak(self):
        flags = audit_market(MARKETS["YrQ6jZbI1xhpY2TyQvJ9"], snapshot_close="2025-01-01T04:59:00+00:00")
        self.assertEqual([(f["code"], f["severity"]) for f in flags], [("CLOSE_EXTENDED", "warn")])


class Cutoff(unittest.TestCase):
    def test_cutoff_flags(self):
        m = MARKETS["gGnxdT90w0mxEPTVwD9S"]  # created 2022-11, resolved 2024-07-13
        c = codes(audit_market(m, cutoff="2024-07-01"))
        self.assertTrue({"RESOLVED_AFTER_CUTOFF", "CURRENT_STATE_FIELDS", "CLOSE_EQUALS_RESOLUTION"} <= c)
        self.assertIn("CREATED_AFTER_CUTOFF", codes(audit_market(m, cutoff="2022-01-01")))
        self.assertIn("RESOLVED_BEFORE_CUTOFF", codes(audit_market(m, cutoff="2024-08-01")))


class Cohort(unittest.TestCase):
    def test_only_resolved_and_subgroups(self):
        resolved = [m for m in MARKETS.values() if m["isResolved"]]
        rep = audit_markets(resolved)
        self.assertEqual(rep["close_equals_resolution"], 3)
        self.assertEqual(rep["outcomes_close_equals_resolution"], {"YES": 2, "NO": 1})
        self.assertEqual({c["code"] for c in rep["cohort"]}, {"ONLY_RESOLVED", "EARLY_RESOLUTION_SUBGROUP"})
        self.assertNotIn("ONLY_RESOLVED", {c["code"] for c in audit_markets(list(MARKETS.values()))["cohort"]})


class AsOf(unittest.TestCase):
    def test_probability_from_last_bet_before_t(self):
        v = asof(MARKETS["VB1RhUVlnNfhclAh4LvR"], "2024-08-05", BETS["VB1RhUVlnNfhclAh4LvR@2024-08-05T00:00:00Z"])
        self.assertTrue(v["exists"])
        self.assertAlmostEqual(v["probability"], 0.829, places=3)
        self.assertFalse(v["isResolved"])
        self.assertIsNone(v["resolution"])
        self.assertIsNone(v["closeTime"])  # planned close was overwritten by the early resolution
        self.assertIn("closeTime", v["unknown"])

    def test_last_bet_wins(self):
        v = asof(MARKETS["gGnxdT90w0mxEPTVwD9S"], "2024-07-01", BETS["gGnxdT90w0mxEPTVwD9S@2024-07-01T00:00:00Z"])
        self.assertAlmostEqual(v["probability"], 0.458, places=3)

    def test_redemptions_skipped_but_partly_cancelled_limit_orders_count(self):
        bets = BETS["gGnxdT90w0mxEPTVwD9S@2024-07-01T00:00:00Z"][2:]  # two redemptions, then a partly filled limit order
        self.assertTrue(bets[0]["isRedemption"] and bets[1]["isRedemption"] and bets[2]["isCancelled"])
        v = asof(MARKETS["gGnxdT90w0mxEPTVwD9S"], "2024-07-01", bets)
        self.assertEqual(v["probability_from_bet_at"][:19], "2024-06-29T22:34:00")
        self.assertAlmostEqual(v["probability"], 0.48, places=3)

    def test_after_resolution_and_before_creation(self):
        v = asof(MARKETS["VB1RhUVlnNfhclAh4LvR"], "2024-09-01", [])
        self.assertTrue(v["isResolved"])
        self.assertEqual(v["resolution"], "YES")
        self.assertFalse(asof(MARKETS["VB1RhUVlnNfhclAh4LvR"], "2020-01-01")["exists"])

    def test_normal_market_keeps_close_with_caveat(self):
        v = asof(MARKETS["Nc8DWWUyYm6CQp6PvOEv"], "2024-06-01")
        self.assertEqual(v["closeTime"], "2024-12-31T20:59:00Z")
        self.assertIn("closeTime_edits", v["unknown"])
        self.assertIsNone(v["probability"])


class Parsing(unittest.TestCase):
    def test_to_ms(self):
        self.assertEqual(to_ms("2024-08-05"), 1722816000000)
        self.assertEqual(to_ms("2024-08-05T00:00:00Z"), 1722816000000)
        self.assertEqual(to_ms(1722816000000), 1722816000000)

    def test_forecastbench_snapshot(self):
        p = ROOT / "tests" / "fixtures" / "_fb.json"
        p.write_text(json.dumps({"questions": [{"id": "abc", "market_info_close_datetime": "2024-11-05T16:59:59+00:00"},
                                               {"id": ["x", "y"], "market_info_close_datetime": "2024-01-01"},
                                               {"id": "n", "market_info_close_datetime": "N/A"},
                                               {"id": "acled1", "source": "acled", "market_info_close_datetime": "2024-01-01"}]}))
        try:
            self.assertEqual(_snapshots(str(p)), {"abc": to_ms("2024-11-05T16:59:59+00:00")})
        finally:
            p.unlink()


if __name__ == "__main__":
    unittest.main()


class AsofMultipleChoice(unittest.TestCase):
    """Recorded real multiple-choice markets (tests/fixtures/multi.json, a few answers kept per market)."""

    def view(self, key, with_bets=True):
        rec = MULTI[key]
        return asof(rec["market"], key.split("@")[1], rec["bets"] if with_bets else None)

    def test_sum_to_one_market_before_resolution(self):
        v = self.view("Z9uy9T4q4rAfq4sGzPA0@2024-08-30T00:00:00Z")
        self.assertTrue(v["shouldAnswersSumToOne"])
        self.assertFalse(v["isResolved"])
        rows = {r["text"]: r for r in v["answers"]}
        self.assertEqual(set(rows), {"Democratic Party", "Republican Party", "Other"})
        self.assertTrue(all(r["resolution"] is None for r in rows.values()))  # resolved 2024-11-06, after `at`
        self.assertAlmostEqual(rows["Democratic Party"]["probability"], 0.5312, places=4)
        self.assertAlmostEqual(rows["Republican Party"]["probability"], 0.4686, places=4)
        # each value is as of its own last bet, so the sum is close to but not exactly 1, and we say so
        self.assertAlmostEqual(v["probability_sum"], 1.0, delta=0.01)
        self.assertNotEqual(v["probability_sum"], 1.0)
        self.assertIn("probability_sync", v["unknown"])
        # closeTime == resolutionTime today, so the close is not reported at `at`
        self.assertIsNone(v["closeTime"])

    def test_sum_to_one_market_after_resolution(self):
        rec = MULTI["Z9uy9T4q4rAfq4sGzPA0@2024-08-30T00:00:00Z"]
        v = asof(rec["market"], "2024-12-01", None)
        res = {r["text"]: r["resolution"] for r in v["answers"]}
        self.assertEqual(res, {"Democratic Party": "NO", "Republican Party": "YES", "Other": "NO"})
        self.assertIn("probability", v["unknown"])

    def test_independent_answers_resolve_one_by_one(self):
        v = self.view("UU79AmfRkcUW9aVA2jIK@2024-01-10T00:00:00Z")
        self.assertFalse(v["shouldAnswersSumToOne"])
        rows = {r["id"]: r for r in v["answers"]}
        self.assertEqual(rows["6e036a5c16fc"]["resolution"], "YES")   # tech layoffs, resolved 2024-01-03
        self.assertIsNone(rows["2c034b3145a0"]["resolution"])          # Trump primary win, resolved 2024-01-16
        self.assertIsNone(rows["7c1d266ea77f"]["resolution"])          # resolved NO on 2024-01-24
        self.assertAlmostEqual(rows["80176651146a"]["probability"], 0.4071, places=4)
        self.assertNotIn("probability_sum", v)

    def test_answers_added_after_at_are_dropped(self):
        v = self.view("UU79AmfRkcUW9aVA2jIK@2024-01-10T00:00:00Z")
        ids = {r["id"] for r in v["answers"]}
        self.assertEqual(v["answers_added_after_at"], 2)
        self.assertFalse(ids & {"9b7c13aa5998", "bb37edb618e5"})

    def test_flat_bet_list_and_missing_bets(self):
        rec = MULTI["UU79AmfRkcUW9aVA2jIK@2024-01-10T00:00:00Z"]
        flat = [b for bl in rec["bets"].values() for b in bl if b["answerId"] != "7c1d266ea77f"]
        flat.sort(key=lambda b: -b["createdTime"])
        v = asof(rec["market"], "2024-01-10T00:00:00Z", flat)
        rows = {r["id"]: r for r in v["answers"]}
        self.assertAlmostEqual(rows["2c034b3145a0"]["probability"], 0.9654, places=4)
        self.assertIsNone(rows["7c1d266ea77f"]["probability"])
        self.assertIn("probability_missing", v["unknown"])

    def test_bets_after_at_are_ignored(self):
        rec = MULTI["UU79AmfRkcUW9aVA2jIK@2024-01-10T00:00:00Z"]
        v = asof(rec["market"], "2024-01-09T06:00:00Z", rec["bets"])
        rows = {r["id"]: r for r in v["answers"]}
        # the three recorded bets on 80176651146a are all from 2024-01-09 18:23 on, after this earlier `at`
        self.assertIsNone(rows["80176651146a"]["probability"])
        # 7c1d266ea77f: the 08:42 bet is after `at`, the 00:24 bet counts
        self.assertAlmostEqual(rows["7c1d266ea77f"]["probability"], 0.0255, places=4)
        v = asof(rec["market"], "2024-01-09T00:00:00Z", rec["bets"])
        rows = {r["id"]: r for r in v["answers"]}
        # only a redemption is left before this `at`; redemptions never count, so the value is unknown, not 0.0259
        self.assertIsNone(rows["7c1d266ea77f"]["probability"])
