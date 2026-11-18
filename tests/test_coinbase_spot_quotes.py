from datetime import datetime, timezone
import io
import json
import unittest
from unittest.mock import patch

from trading.coinbase_spot_quotes import collect, fetch_quote

NOW = 900005


def response(**changes):
    value = dict(product_id="BTC-USD", time=datetime.fromtimestamp(NOW, timezone.utc).isoformat(),
                 bids=[dict(price="99", size="2")], asks=[dict(price="100", size="3")])
    return {"pricebook": dict(value, **changes)}


class CoinbaseQuotesTests(unittest.TestCase):
    def fetch(self, payload):
        def opener(request, timeout):
            self.assertEqual(request.get_method(), "GET")
            self.assertIn("/brokerage/market/product_book?", request.full_url)
            self.assertNotIn("Authorization", request.headers)
            self.assertNotIn("orders", request.full_url)
            return io.BytesIO(json.dumps(payload).encode())
        return fetch_quote("BTC", opener=opener, clock=lambda: NOW)

    def test_public_snapshot_uses_exchange_timestamp_and_size(self):
        book = self.fetch(response())
        self.assertEqual(book["quoted_at"], NOW)
        self.assertEqual(book["bid_size"], 2)
        self.assertEqual(book["ask_usd"], 100)

    def test_mismatched_stale_future_crossed_and_empty_books(self):
        for payload in (response(product_id="ETH-USD"), response(time="1970-01-01T00:00:00Z"),
                        response(time="2100-01-01T00:00:00Z"), response(bids=[dict(price="101", size="1")]),
                        response(asks=[])):
            with self.subTest(payload=payload):
                with self.assertRaises((ValueError, IndexError)):
                    self.fetch(payload)

    def test_partial_outage_does_not_reuse_old_snapshot(self):
        with patch("trading.coinbase_spot_quotes.fetch_quote", side_effect=[ValueError(), {"asset": "ETH"}]):
            feed = collect()
        self.assertEqual(feed["quotes"], [{"asset": "ETH"}])
        self.assertEqual(feed["errors"][0]["asset"], "BTC")


if __name__ == "__main__":
    unittest.main()
