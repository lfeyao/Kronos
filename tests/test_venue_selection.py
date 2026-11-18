import json
import unittest

from trading.runner import ROOT, PaperRunner, load_config

WINDOW, NOW = 900000, 900005


def signal(venue="polymarket", **changes):
    item = dict(venue=venue, asset="BTC", kind="binary", side="up", instrument_id="btc-up",
        window_start=WINDOW, horizon_seconds=900, generated_at=NOW, quoted_at=NOW,
        forecast_id="shared-forecast", model_version="kronos-small:baseline",
        model_expected_price_usd=160000, probability=0.7, entry_cost_per_unit=0.4,
        executable_budget_usd=100)
    if venue != "polymarket":
        item.update(instrument_id=f"{venue}-btc-up", entry_cost_per_unit=0.44 if venue == "coinbase" else 0.46)
    return {**item, **changes}


def unavailable(venue):
    return dict(venue=venue, asset="BTC", window_start=WINDOW, checked_at=NOW,
                status="unavailable", reason="No executable market")


class VenueSelectionTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "config.json")
        self.config["require_regime_report"] = False
        self.runner = PaperRunner(self.config, ":memory:")

    def tearDown(self):
        self.runner.close()

    def count(self):
        return self.runner.db.execute("SELECT count(*) FROM positions").fetchone()[0]

    def process(self, signals, checks=()):
        self.runner.process(dict(signals=signals, venue_checks=list(checks)), NOW)

    def selected(self):
        return self.runner.db.execute("SELECT venue FROM positions").fetchone()[0]

    def test_selects_best_net_roi_across_venues(self):
        self.process([signal("coinbase"), signal("robinhood"), signal()])
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.selected(), "polymarket")
        row = self.runner.db.execute("SELECT model_expected_price_usd, forecast_id FROM positions").fetchone()
        self.assertEqual(tuple(row), (160000, "shared-forecast"))

    def test_best_prediction_contract_price_wins(self):
        self.process([signal(), signal("coinbase", entry_cost_per_unit=0.38),
                      signal("robinhood", entry_cost_per_unit=0.35)])
        self.assertEqual(self.selected(), "robinhood")

    def test_waits_for_all_venues_before_selecting(self):
        self.process([signal()])
        self.assertEqual(self.count(), 0)
        self.process([signal(), signal("coinbase"), signal("robinhood")])
        self.assertEqual(self.count(), 1)

    def test_unavailable_venue_counts_only_if_explicit_and_fresh(self):
        checks = [unavailable("coinbase"), {**unavailable("robinhood"), "checked_at": NOW - 11}]
        self.process([signal()], checks)
        self.assertEqual(self.count(), 0)
        self.process([signal()], [unavailable("coinbase"), unavailable("robinhood")])
        self.assertEqual(self.count(), 1)

    def test_conflicting_forecasts_block_comparison(self):
        for change in (dict(forecast_id="other"), dict(model_expected_price_usd=170000),
                       dict(model_version="other-model"), dict(generated_at=NOW - 1)):
            with self.subTest(change=change):
                self.process([signal(), signal("coinbase", **change), signal("robinhood")])
                self.assertEqual(self.count(), 0)

    def test_unfunded_best_venue_falls_back_to_next_eligible(self):
        with self.runner.db:
            self.runner.db.execute("UPDATE accounts SET available_usd=0 WHERE venue='polymarket'")
        self.process([signal(), signal("coinbase"), signal("robinhood")])
        self.assertEqual(self.selected(), "coinbase")

    def test_same_asset_window_cannot_enter_on_another_venue_later(self):
        self.process([signal(), signal("coinbase"), signal("robinhood")])
        self.process([signal(), signal("coinbase", entry_cost_per_unit=0.2), signal("robinhood")])
        self.assertEqual(self.count(), 1)

    def test_low_roi_never_fills_even_when_best_available(self):
        self.process([signal(probability=0.5), signal("coinbase", probability=0.5),
                      signal("robinhood", probability=0.5)])
        self.assertEqual(self.count(), 0)

    def test_down_contract_can_win_across_all_venues(self):
        self.process([signal(), signal("coinbase", side="down", instrument_id="coinbase-btc-down",
                                     probability=0.75, entry_cost_per_unit=0.3), signal("robinhood")])
        self.assertEqual(self.selected(), "coinbase")
        self.assertEqual(self.runner.db.execute("SELECT side FROM positions").fetchone()[0], "down")

    def test_better_probability_can_outweigh_a_cheaper_contract(self):
        self.process([signal(probability=0.65), signal("coinbase", probability=0.85), signal("robinhood")])
        self.assertEqual(self.selected(), "coinbase")

    def test_all_alternatives_are_auditable(self):
        self.process([signal(), signal("coinbase"), signal("robinhood")])
        decisions = [json.loads(row[0]) for row in self.runner.db.execute("SELECT payload FROM decisions")]
        comparison = next(item for item in decisions if item["decision"] == "venue_comparison")
        self.assertEqual(len(comparison["alternatives"]), 3)
        self.assertTrue(any(item["decision"] == "venue_selected" for item in decisions))

    def test_model_expected_price_is_required(self):
        item = signal()
        del item["model_expected_price_usd"]
        self.process([item, signal("coinbase"), signal("robinhood")])
        self.assertEqual(self.count(), 0)


if __name__ == "__main__":
    unittest.main()
