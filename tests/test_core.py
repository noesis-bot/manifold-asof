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
