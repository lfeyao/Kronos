import copy
from datetime import datetime, timedelta, timezone
import json
import unittest

from trading.regime import ZONE, validate_report
from trading.runner import ROOT, PaperRunner, load_config

WINDOW, NOW = 900000, 900005


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def report():
    today = datetime.fromtimestamp(NOW, ZONE).date()
    return dict(schema_version=1, source="gemini", report_id="review-1",
                model_version="kronos-small:baseline", horizon_seconds=900,
                generated_at=iso(NOW), expires_at=iso(NOW + 3600),
                analyzed_date=str(today - timedelta(days=1)), trading_date=str(today),
                assets={asset: dict(trade_allowed=True, regime="range", reason="Review supports this regime")
                        for asset in ("BTC", "ETH")},
                weight_update=dict(recommended=False, reason="Retain current checkpoint"))


def signal():
    return dict(venue="polymarket", asset="BTC", kind="binary", side="up",
                instrument_id="btc-up", window_start=WINDOW, horizon_seconds=900,
                model_version="kronos-small:baseline", generated_at=NOW, quoted_at=NOW,
                probability=0.7, entry_cost_per_unit=0.4, executable_budget_usd=100,
                forecast_id="forecast-1", model_expected_price_usd=110000)


class RegimeGateTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "config.json")
        self.config["require_all_venue_checks"] = False  # Isolate the review gate.
        self.runner = PaperRunner(self.config, ":memory:")

    def tearDown(self):
        self.runner.close()

    def count(self):
        return self.runner.db.execute("SELECT count(*) FROM positions").fetchone()[0]

    def process(self, review, item=None):
        self.runner.process({"signals": [item or signal()]}, NOW, regime_report=review)

    def test_valid_report_allows_trade_and_is_audited(self):
        self.process(report())
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.runner.db.execute("SELECT regime_report_id FROM positions").fetchone()[0], "review-1")
        self.assertEqual(self.runner.db.execute("SELECT count(*) FROM regime_reports").fetchone()[0], 1)

    def test_missing_report_blocks_even_high_roi(self):
        self.process(None)
        self.assertEqual(self.count(), 0)
        payload = json.loads(self.runner.db.execute("SELECT payload FROM decisions").fetchone()[0])
        self.assertEqual(payload["decision"], "regime_blocked")

    def test_asset_pause_and_missing_decision_block(self):
        review = report()
        review["assets"]["BTC"]["trade_allowed"] = False
        self.process(review)
        review["report_id"] = "review-2"
        del review["assets"]["BTC"]
        self.process(review)
        self.assertEqual(self.count(), 0)

    def test_future_expired_wrong_date_and_wrong_model_block(self):
        changes = [dict(generated_at=iso(NOW + 1)), dict(expires_at=iso(NOW)),
                   dict(analyzed_date="2000-01-01"), dict(trading_date="2000-01-01"),
                   dict(model_version="other-model"), dict(horizon_seconds=300),
                   dict(expires_at=iso(NOW + 27 * 3600))]
        for change in changes:
            with self.subTest(change=change):
                self.process({**report(), **change})
                self.assertEqual(self.count(), 0)

    def test_signal_must_use_reviewed_model(self):
        self.process(report(), {**signal(), "model_version": "new-unreviewed-weights"})
        item = signal()
        del item["model_version"]
        self.process(report(), item)
        self.assertEqual(self.count(), 0)

    def test_weight_recommendation_never_changes_active_model(self):
        review = report()
        review["weight_update"] = dict(recommended=True, reason="Evaluate candidate", candidate_version="candidate-v2")
        before = copy.deepcopy(self.config)
        self.process(review)
        self.assertEqual(self.config, before)
        self.assertEqual(self.count(), 1)  # Regime decision is independent of a recommendation.

    def test_report_cannot_override_roi_rule(self):
        self.process(report(), {**signal(), "probability": 0.5})
        self.assertEqual(self.count(), 0)

    def test_changed_report_id_is_rejected(self):
        review = report()
        self.process(review, {**signal(), "probability": 0.1})
        review["assets"]["BTC"]["reason"] = "Changed contents require a new report ID"
        self.process(review)
        self.assertEqual(self.count(), 0)

    def test_settlement_still_works_without_report(self):
        self.process(report())
        item = dict(venue="polymarket", asset="BTC", instrument_id="btc-up", window_start=WINDOW,
                    observed_at=WINDOW + 901, resolved=True, winning_side="up")
        self.runner.process({"settlements": [item]}, WINDOW + 902, regime_report=None)
        self.assertEqual(self.runner.db.execute("SELECT status FROM positions").fetchone()[0], "paper_closed")

    def test_pacific_day_boundary_expires_previous_report(self):
        next_day = datetime.fromtimestamp(NOW, ZONE).replace(hour=0, minute=0, second=0) + timedelta(days=1)
        review = report()
        review["expires_at"] = iso(next_day.timestamp() + 60)
        with self.assertRaises(ValueError):
            validate_report(review, self.config, next_day.timestamp())


if __name__ == "__main__":
    unittest.main()
