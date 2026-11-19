"""Accounting and timing checks for the source-inspired offline simulation."""
import unittest

from test_vault_competition import (
    CAPITAL, END, START, Ledger, average_run, trend_run,
)


class VaultAccountingTests(unittest.TestCase):
    def test_futures_marks_and_fees_reconcile(self):
        l = Ledger('accounting', 0)
        l.trade(.01, 70000, .001)
        l.mark(71000)
        l.trade(0, 71000, .001)
        expected = CAPITAL + 10 - .01*(70000+71000)*.0012
        self.assertAlmostEqual(l.equity, expected)
        self.assertAlmostEqual(l.turnover, 1410)
        self.assertEqual(l.q, 0)

    def test_funding_drag_tracks_held_notional_and_elapsed_time(self):
        l = Ledger('funding', 5)
        l.q, l.last = .01, 70000
        l.close_bar(dict(start=START, close=70000), 86400)
        self.assertAlmostEqual(l.funding, .35)
        self.assertAlmostEqual(l.equity, CAPITAL-.35)

    def test_future_indicator_cannot_change_current_execution(self):
        b = dict(start=START+6300, open=70000, high=70100, low=69900, close=70000)
        available = dict(time=START+3600, trend=.02, participation=1, variance=.25)
        future = dict(time=END+3600, trend=-100, participation=3, variance=.01)
        a = trend_run([b], [available], 'inverse_variance', 5, 10)
        c = trend_run([b], [available, future], 'inverse_variance', 5, 10)
        self.assertEqual(a.summary(), c.summary())

    def test_underwater_inventory_is_closed_and_included(self):
        bars = [dict(start=START, open=70000, high=70000, low=69000, close=69000)]
        l, extra = average_run(bars, [dict(time=START, ema14=70000)], .003, 'high_low', 5, False)
        self.assertEqual(l.q, 0)
        self.assertEqual(extra['terminal_open_contracts'], 1)
        self.assertLess(extra['terminal_unrealized_before_exit_usd'], 0)
        self.assertLess(l.equity, CAPITAL)

    def test_price_winner_can_lose_after_fees(self):
        bars = [dict(start=START, open=70000, high=70000, low=69400, close=69900)]
        l, extra = average_run(bars, [dict(time=START, ema14=70000)], .001, 'low_high', 0, False)
        self.assertEqual(extra['price_profitable_cycles'], 1)
        self.assertLess(l.equity, CAPITAL)


if __name__ == '__main__':
    unittest.main()
