from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace as NS
import unittest

from trading.polymarket import build_feed, build_signals, quote_cost
from trading.runner import ROOT, load_config

WINDOW, NOW = 900000, 900005


def timestamp(value):
    return datetime.fromtimestamp(value, timezone.utc)


def book(asset="up-token", asks=None):
    return NS(asset_id=asset, condition_id="condition", timestamp=timestamp(NOW),
              min_order_size=Decimal("5"), asks=[NS(price=Decimal(p), size=Decimal(s))
              for p, s in (asks or [("0.4", "1000")])])


def trading():
    return NS(fees_enabled=True, fee_schedule=NS(rate=Decimal("0.07"), exponent=1))


class Client:
    def __init__(self):
        self.market = NS(slug=f"btc-updown-15m-{WINDOW}", version="v1", condition_id="condition",
            state=NS(active=True, closed=False, accepting_orders=True, end_date=timestamp(WINDOW + 900)),
            trading=trading(), outcomes=NS(
                yes=NS(label="Down", token_id="down-token", position_id="down-position"),
                no=NS(label="Up", token_id="up-token", position_id="up-position")))

    def get_market(self, slug):
        assert slug == self.market.slug
        return self.market

    def get_order_book(self, asset_id):
        return book(asset=asset_id)


class PolymarketAdapterTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "config.json")
        self.prediction = dict(asset="BTC", window_start=WINDOW, horizon_seconds=900,
                               generated_at=NOW, p_up=0.7, model_version="kronos-small:baseline",
                               forecast_id="forecast-1", model_expected_price_usd=110000)

    def test_depth_and_fees_affect_cost(self):
        cost, quoted = quote_cost(book(asks=[("0.5", "300"), ("0.4", "100")]), trading(), 100, NOW, 10)
        self.assertAlmostEqual(cost, 0.5175)
        self.assertEqual(quoted, NOW)

    def test_maps_labels_and_probability_for_each_side(self):
        signals = build_signals(Client(), self.prediction, self.config, lambda: NOW)
        self.assertEqual([s["instrument_id"] for s in signals], ["up-token", "down-token"])
        self.assertEqual(signals[0]["probability"], 0.7)
        self.assertAlmostEqual(signals[1]["probability"], 0.3)
        self.assertEqual(signals[0]["model_expected_price_usd"], 110000)
        self.assertEqual(signals[0]["forecast_id"], "forecast-1")

    def test_closed_market_publishes_explicit_unavailability(self):
        client = Client()
        client.market.state.closed = True
        with self.assertLogs("trading.polymarket", level="ERROR"):
            feed = build_feed(client, [self.prediction], self.config, lambda: NOW)
        self.assertEqual(feed["signals"], [])
        self.assertEqual(feed["venue_checks"][0]["status"], "unavailable")

    def test_missing_model_input_cannot_count_as_a_checked_venue(self):
        prediction = dict(self.prediction)
        del prediction["model_expected_price_usd"]
        with self.assertLogs("trading.polymarket", level="ERROR"):
            feed = build_feed(Client(), [prediction], self.config, lambda: NOW)
        self.assertEqual(feed["signals"], [])
        self.assertEqual(feed["venue_checks"], [])

    def test_v2_uses_position_id(self):
        client = Client()
        client.market.version = "v2"
        signals = build_signals(client, self.prediction, self.config, lambda: NOW)
        self.assertEqual(signals[0]["instrument_id"], "up-position")

    def test_unknown_fees_stale_books_and_insufficient_depth_fail_closed(self):
        for mode in ("missing_fee", "exponent", "stale", "depth", "timestamp", "minimum"):
            with self.subTest(mode=mode):
                data, fees = book(), trading()
                if mode == "missing_fee":
                    fees.fees_enabled = None
                elif mode == "exponent":
                    fees.fee_schedule.exponent = 2
                elif mode == "stale":
                    data.timestamp = timestamp(NOW - 11)
                elif mode == "depth":
                    data.asks = [NS(price=Decimal("0.4"), size=Decimal("1"))]
                elif mode == "timestamp":
                    data.timestamp = None
                elif mode == "minimum":
                    data.min_order_size = Decimal("101")
                with self.assertRaises(ValueError):
                    quote_cost(data, fees, 100, NOW, 10)

    def test_market_status_and_horizon_must_match(self):
        for mode in ("closed", "expiry", "labels", "version"):
            with self.subTest(mode=mode):
                client = Client()
                if mode == "closed":
                    client.market.state.closed = True
                elif mode == "expiry":
                    client.market.state.end_date = timestamp(WINDOW + 300)
                elif mode == "labels":
                    client.market.outcomes.yes.label = "Yes"
                elif mode == "version":
                    client.market.version = "unknown"
                with self.assertRaises(ValueError):
                    build_signals(client, self.prediction, self.config, lambda: NOW)

    def test_mismatched_book_not_published(self):
        client = Client()
        client.get_order_book = lambda asset_id: book(asset="wrong")
        self.assertEqual(build_signals(client, self.prediction, self.config, lambda: NOW), [])

    def test_five_minute_model_output_is_rejected(self):
        with self.assertRaises(ValueError):
            build_signals(Client(), {**self.prediction, "horizon_seconds": 300}, self.config, lambda: NOW)


if __name__ == "__main__":
    unittest.main()
