import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from trading.regime import ZONE
from trading.spot_runner import SpotPaperRunner, config_hash, load_config, plan

WINDOW, NOW = 900000, 900005


def config():
    value = load_config()
    value.update(minimum_expected_net_return=0, buy_fee_rate=0.01, sell_fee_rate=0.01,
                 entry_slippage_bps=10, exit_slippage_bps=10,
                 expected_exit_half_spread_bps=10, cost_assumption_source="fictional test assumptions")
    return value


def book(asset="BTC", now=NOW, **changes):
    return dict(venue="coinbase", asset=asset, product_id=f"{asset}-USD", quoted_at=now,
                **dict(dict(bid_usd=99, ask_usd=100, bid_size=10, ask_size=10), **changes))


def forecast(asset="BTC", now=NOW, **changes):
    value = dict(asset=asset, product_id=f"{asset}-USD", price_basis="mid", window_start=now // 900 * 900,
                 horizon_seconds=900, generated_at=now, forecast_id=f"{asset}-{now // 900}",
                 model_version="kronos-small:baseline", model_expected_price_usd=110)
    return dict(value, **changes)


def report(configuration=None):
    day = datetime.fromtimestamp(NOW, ZONE).date()
    return dict(schema_version=1, source="gemini", strategy="coinbase_spot_15m", report_id="spot-review-1",
                strategy_config_hash=config_hash(configuration or config()),
                model_version="kronos-small:baseline", horizon_seconds=900,
                generated_at=datetime.fromtimestamp(NOW, timezone.utc).isoformat(),
                expires_at=datetime.fromtimestamp(NOW + 3600, timezone.utc).isoformat(),
                trading_date=str(day), analyzed_date=str(day - timedelta(days=1)),
                weight_update=dict(recommended=False, reason="Keep checkpoint"),
                assets={asset: dict(trade_allowed=True, regime="range", reason="Spot paper review") for asset in ("BTC", "ETH")})


class SpotRunnerTests(unittest.TestCase):
    def setUp(self):
        self.config = config()
        self.runner = SpotPaperRunner(self.config, ":memory:")

    def tearDown(self):
        self.runner.close()

    def process(self, forecasts=None, quotes=None, review=None, now=NOW):
        self.runner.process(dict(forecasts=[forecast()] if forecasts is None else forecasts,
                                 quotes=[book()] if quotes is None else quotes), now, report(self.config) if review is None else review)

    def positions(self):
        return self.runner.db.execute("SELECT * FROM spot_positions").fetchall()

    def cash(self):
        return self.runner.db.execute("SELECT usd FROM spot_cash").fetchone()[0]

    def test_round_trip_costs_and_fee_inclusive_stake(self):
        item = plan(forecast(), book(), self.config, NOW)
        quantity = 100 / (100 * 1.001 * 1.01)
        expected = quantity * 110 * .999 * .999 * .99
        self.assertAlmostEqual(item["quantity"], quantity)
        self.assertAlmostEqual(item["expected_profit_usd"], expected - 100)
        self.assertAlmostEqual(item["expected_net_return"], expected / 100 - 1)
        self.assertTrue(item["eligible"])

    def test_strict_threshold_and_unset_threshold(self):
        value = plan(forecast(), book(), self.config, NOW)["expected_net_return"]
        self.config["minimum_expected_net_return"] = value
        self.assertFalse(plan(forecast(), book(), self.config, NOW)["eligible"])
        self.config["minimum_expected_net_return"] = None
        self.process()
        self.assertEqual(len(self.positions()), 0)

    def test_unset_costs_and_provenance_block_entries(self):
        for change in (dict(buy_fee_rate=None), dict(exit_slippage_bps=None), dict(cost_assumption_source="")):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    plan(forecast(), book(), dict(self.config, **change), NOW)

    def test_direction_probability_is_not_terminal_price_forecast(self):
        value = forecast()
        value.pop("model_expected_price_usd")
        value["probability_up"] = .99
        self.process(forecasts=[value])
        self.assertEqual(len(self.positions()), 0)

    def test_bad_forecasts_and_stale_books_are_rejected(self):
        cases = [forecast(model_expected_price_usd=float("nan")), forecast(price_basis="last"),
                 forecast(horizon_seconds=300), forecast(window_start=WINDOW + 1),
                 forecast(model_version="other"), forecast(generated_at=NOW + 1),
                 forecast(generated_at=WINDOW - 1), forecast(product_id="BTC-PERP")]
        for item in cases:
            with self.subTest(item=item):
                self.process(forecasts=[item])
                self.assertEqual(len(self.positions()), 0)
        self.process(quotes=[book(now=NOW - 11)])
        self.process(quotes=[book(ask_size=.01)])
        self.assertEqual(len(self.positions()), 0)

    def test_long_cash_and_round_trip_loss(self):
        self.process()
        self.assertEqual(self.cash(), 900)
        self.assertEqual(len(self.positions()), 1)
        self.process(forecasts=[], quotes=[book(now=WINDOW + 899)], now=WINDOW + 899)
        self.assertEqual(self.positions()[0]["status"], "open")
        self.runner.process(dict(quotes=[book(now=WINDOW + 900, bid_usd=90, ask_usd=91)]), WINDOW + 900, None)
        position = self.positions()[0]
        proceeds = position["quantity"] * 90 * .999 * .99
        self.assertEqual(position["status"], "closed")
        self.assertAlmostEqual(position["realized_pnl_usd"], proceeds - 100)
        self.assertAlmostEqual(self.cash(), 900 + proceeds)

    def test_repeat_entry_and_exit_are_idempotent(self):
        self.process()
        self.process()
        self.assertEqual(len(self.positions()), 1)
        feed = dict(quotes=[book(now=WINDOW + 900, bid_usd=120, ask_usd=121)])
        self.runner.process(feed, WINDOW + 900, None)
        cash = self.cash()
        self.runner.process(feed, WINDOW + 900, None)
        self.assertEqual(self.cash(), cash)

    def test_missing_paused_binary_and_modified_reports_block_entries(self):
        cases = [None, {**report(), "strategy": "binary"}, {**report(), "model_version": "other"}]
        paused = report()
        paused["assets"]["BTC"]["trade_allowed"] = False
        cases.append(paused)
        for review in cases:
            self.runner.process(dict(forecasts=[forecast()], quotes=[book()]), NOW, review)
        self.assertEqual(len(self.positions()), 0)
        # The paused report ID is immutable; changing it to allow the asset is rejected.
        self.process()
        self.assertEqual(len(self.positions()), 0)

    def test_bad_forecast_container_does_not_block_exit(self):
        self.process()
        self.runner.process(dict(quotes=[book(now=WINDOW + 900)], forecasts="invalid"), WINDOW + 900, None)
        self.assertEqual(self.positions()[0]["status"], "closed")

    def test_exit_requires_post_deadline_fresh_full_size_bid(self):
        self.process()
        self.process(forecasts=[], quotes=[book(now=WINDOW + 899)], now=WINDOW + 900)
        self.assertEqual(self.positions()[0]["status"], "open")
        self.process(forecasts=[], quotes=[book(now=WINDOW + 900, bid_size=.01)], now=WINDOW + 900)
        self.assertEqual(self.positions()[0]["status"], "open")
        self.assertEqual(self.cash(), 900)

    def test_one_open_per_asset_and_overdue_exit_blocks_other_entries(self):
        self.process()
        now = WINDOW + 905
        self.process(forecasts=[forecast("ETH", now=now)], quotes=[book("ETH", now=now)], now=now)
        self.assertEqual(len(self.positions()), 1)

    def test_shared_cash_prevents_leverage(self):
        self.runner.close()
        self.config["starting_balance_usd"] = 100
        self.runner = SpotPaperRunner(self.config, ":memory:")
        self.process(forecasts=[forecast(), forecast("ETH")], quotes=[book(), book("ETH")])
        self.assertEqual(len(self.positions()), 1)
        self.assertEqual(self.cash(), 0)

    def test_conflicting_quotes_and_forecasts_cannot_select_favorable_copy(self):
        self.process(quotes=[book(), book(ask_usd=101), book()])
        self.assertEqual(len(self.positions()), 0)
        self.process(forecasts=[forecast(), forecast(model_expected_price_usd=120)])
        self.assertEqual(len(self.positions()), 0)

    def test_restart_preserves_cash_positions_and_original_exit_costs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper.sqlite3"
            first = SpotPaperRunner(self.config, path)
            first.process(dict(quotes=[book()], forecasts=[forecast()]), NOW, report())
            first.close()
            altered = dict(self.config, starting_balance_usd=5000, sell_fee_rate=.5)
            second = SpotPaperRunner(altered, path)
            self.assertEqual(second.db.execute("SELECT usd FROM spot_cash").fetchone()[0], 900)
            second.process(dict(quotes=[book(now=WINDOW + 900)]), WINDOW + 900, None)
            position = second.db.execute("SELECT * FROM spot_positions").fetchone()
            self.assertAlmostEqual(position["proceeds_usd"], position["quantity"] * 99 * .999 * .99)
            second.close()

    def test_live_mode_and_futures_configuration_rejected(self):
        for change in (dict(execution_mode="live"), dict(strategy="futures"), dict(assets=["SOL"])):
            with self.assertRaises(ValueError):
                SpotPaperRunner(dict(self.config, **change), ":memory:")

    def test_report_must_review_exact_fee_and_strategy_configuration(self):
        review = report()
        review["strategy_config_hash"] = config_hash(dict(self.config, buy_fee_rate=0))
        self.process(review=review)
        self.assertEqual(len(self.positions()), 0)


if __name__ == "__main__":
    unittest.main()
