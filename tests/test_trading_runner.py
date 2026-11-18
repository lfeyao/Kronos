import copy
import json
import tempfile
import unittest
from pathlib import Path

from trading.runner import PaperRunner, ROOT, load_config, plan


WINDOW = 900000
NOW = WINDOW + 5


def signal(**changes):
    value = dict(venue="polymarket", asset="BTC", kind="binary", side="up",
                 instrument_id="btc-up", window_start=WINDOW, horizon_seconds=900,
                 generated_at=NOW, quoted_at=NOW, probability=0.70,
                 forecast_id="forecast-1", model_version="kronos-small:baseline",
                 model_expected_price_usd=110000,
                 entry_cost_per_unit=0.40, executable_budget_usd=100)
    value.update(changes)
    return value


class TradingRunnerTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "config.json")
        self.config["require_regime_report"] = False  # These tests isolate accounting and ROI.
        self.config["require_all_venue_checks"] = False
        self.runner = PaperRunner(self.config, ":memory:")

    def tearDown(self):
        self.runner.close()

    def balance(self, venue="polymarket"):
        return self.runner.db.execute("SELECT available_usd FROM accounts WHERE venue=?", (venue,)).fetchone()[0]

    def count(self):
        return self.runner.db.execute("SELECT COUNT(*) FROM positions").fetchone()[0]

    def test_binary_expected_roi_is_return_on_capital(self):
        result = plan(signal(), self.config, NOW)
        self.assertAlmostEqual(result["expected_roi"], 0.75)
        self.assertAlmostEqual(result["expected_profit_usd"], 75)
        self.assertTrue(result["eligible"])

    def test_threshold_is_strict_and_includes_costs(self):
        self.assertFalse(plan(signal(probability=0.75, entry_cost_per_unit=0.5), self.config, NOW)["eligible"])
        self.assertTrue(plan(signal(probability=0.8, entry_cost_per_unit=0.5), self.config, NOW)["eligible"])
        self.assertFalse(plan(signal(probability=0.8, entry_cost_per_unit=0.54), self.config, NOW)["eligible"])

    def test_up_down_supported_on_all_venues(self):
        for venue in self.config["venues"]:
            for side in ("up", "down"):
                with self.subTest(venue=venue, side=side):
                    result = plan(signal(venue=venue, side=side), self.config, NOW)
                    self.assertAlmostEqual(result["expected_roi"], 0.75)
                    self.assertTrue(result["eligible"])

    def test_spot_and_other_instruments_rejected_on_all_venues(self):
        for venue in self.config["venues"]:
            for kind, side in (("spot", "buy"), ("future", "up"), ("binary", "buy"), ("binary", "yes")):
                with self.subTest(venue=venue, kind=kind, side=side), self.assertRaises(ValueError):
                    plan(signal(venue=venue, kind=kind, side=side), self.config, NOW)

    def test_invalid_and_stale_signals_fail_closed(self):
        for changes in (dict(probability=float("nan")), dict(probability=1.1),
                        dict(entry_cost_per_unit=0), dict(executable_budget_usd=99),
                        dict(generated_at=NOW + 1), dict(quoted_at=NOW - 11),
                        dict(window_start=WINDOW - 900), dict(horizon_seconds=300),
                        dict(instrument_id=""), dict(side="short"), dict(venue="unknown")):
            with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
                plan(signal(**changes), self.config, NOW)
        with self.assertRaises(ValueError):
            plan(signal(generated_at=WINDOW + 100, quoted_at=WINDOW + 100), self.config, WINDOW + 100)

    def test_highest_roi_side_selected_and_no_duplicates(self):
        self.runner.process({"signals": [signal(), signal(side="down", instrument_id="btc-down",
                                                         probability=0.30, entry_cost_per_unit=0.10)]}, NOW)
        self.runner.process({"signals": [signal()]}, NOW)
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.runner.db.execute("SELECT side FROM positions").fetchone()[0], "down")
        self.assertEqual(self.balance(), 900)

    def test_capital_is_separate_and_cannot_be_overspent(self):
        for index in range(11):
            start = WINDOW + index * 900
            self.runner.process({"signals": [signal(window_start=start, generated_at=start + 5, quoted_at=start + 5)]}, start + 5)
        self.assertEqual(self.count(), 10)
        self.assertEqual(self.balance(), 0)
        self.assertEqual(self.balance("coinbase"), 1000)

    def test_binary_settlement_credits_actual_proceeds_once(self):
        self.runner.process({"signals": [signal()]}, NOW)
        item = dict(venue="polymarket", asset="BTC", instrument_id="btc-up", window_start=WINDOW,
                    observed_at=WINDOW + 901, resolved=True, winning_side="up")
        self.runner.process({"settlements": [item]}, WINDOW + 902)
        self.runner.process({"settlements": [item]}, WINDOW + 903)
        self.assertEqual(self.balance(), 1150)
        self.assertEqual(self.runner.db.execute("SELECT realized_profit_usd FROM positions").fetchone()[0], 150)

    def test_unresolved_or_wrong_instrument_cannot_settle(self):
        self.runner.process({"signals": [signal()]}, NOW)
        item = dict(venue="polymarket", asset="BTC", instrument_id="btc-up", window_start=WINDOW,
                    observed_at=WINDOW + 901, resolved=False, winning_side="up")
        self.runner.process({"settlements": [item]}, WINDOW + 902)
        self.runner.process({"settlements": [{**item, "resolved": True, "instrument_id": "other"}]}, WINDOW + 902)
        self.assertEqual(self.balance(), 900)

    def test_robinhood_down_contract_settles_actual_outcome(self):
        self.runner.process({"signals": [signal(venue="robinhood", side="down", instrument_id="BTC-down")]}, NOW)
        item = dict(venue="robinhood", asset="BTC", instrument_id="BTC", window_start=WINDOW,
                    observed_at=WINDOW + 901, resolved=True, winning_side="up")
        item["instrument_id"] = "BTC-down"
        self.runner.process({"settlements": [item]}, WINDOW + 902)
        self.assertEqual(self.balance("robinhood"), 900)

    def test_restart_preserves_balance_and_window_key(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "paper.sqlite3"
            first = PaperRunner(self.config, path)
            first.process({"signals": [signal()]}, NOW)
            first.close()
            second = PaperRunner(self.config, path)
            try:
                second.process({"signals": [signal()]}, NOW)
                self.assertEqual(second.db.execute("SELECT COUNT(*) FROM positions").fetchone()[0], 1)
                self.assertEqual(second.db.execute("SELECT available_usd FROM accounts WHERE venue='polymarket'").fetchone()[0], 900)
            finally:
                second.close()

    def test_bad_feed_shapes_rejected(self):
        for feed in ([], {"signals": {}}, {"settlements": [None]}):
            with self.assertRaises(ValueError):
                self.runner.process(feed, NOW)

    def test_invalid_configuration_rejected(self):
        config = copy.deepcopy(self.config)
        config["stake_usd"] = 1001
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text(json.dumps(config))
            with self.assertRaises(ValueError):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
