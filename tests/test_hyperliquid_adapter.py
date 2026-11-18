import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from trading.check_hyperliquid import verify_agent_approval
from trading.credentials import load_hyperliquid_credentials
from trading.hyperliquid import (
    build_feed,
    build_signals,
    discover_15m_outcomes,
    encode_outcome,
    preview_order,
    quote_outcome_book,
)
from trading.runner import ROOT, load_config
from trading.save_hyperliquid_credentials import save_hyperliquid_credentials

WINDOW, NOW = 1800000000, 1800000005


class FakeHyperliquidClient:
    def __init__(self, window_end=WINDOW + 900, closed=False, asks=None):
        self.meta = {
            "outcomes": [
                {
                    "id": 7,
                    "underlying": "BTC",
                    "windowStart": WINDOW,
                    "windowEnd": window_end,
                    "closed": closed,
                    "settled": False,
                    "collateral": "USDC",
                    "feeRate": 0.0,
                    "minOrderSize": 5.0,
                    "sideSpecs": [{"label": "Up"}, {"label": "Down"}],
                }
            ]
        }
        self.asks = asks or [{"px": "0.40", "sz": "500"}]

    def get_outcome_meta(self):
        return self.meta

    def get_l2_book(self, coin):
        return {
            "coin": coin,
            "time": NOW * 1000,
            "levels": [
                [{"px": "0.38", "sz": "500", "n": 2}],
                self.asks,
            ],
        }


class HyperliquidAdapterTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "config.json")
        self.prediction = {
            "asset": "BTC",
            "window_start": WINDOW,
            "horizon_seconds": 900,
            "generated_at": NOW,
            "p_up": 0.70,
            "model_version": "kronos-small:baseline",
            "forecast_id": "BTC-1800000000-001",
            "model_expected_price_usd": 110000.0,
        }

    def test_hip4_outcome_asset_encoding_matches_spec(self):
        side0 = encode_outcome(1, 0)
        side1 = encode_outcome(1, 1)
        self.assertEqual(side0["encoding"], 10)
        self.assertEqual(side0["spot_coin"], "#10")
        self.assertEqual(side0["token_name"], "+10")
        self.assertEqual(side0["asset_id"], 100_000_010)
        self.assertEqual(side1["asset_id"], 100_000_011)

    def test_discovers_matching_15m_contract_and_rejects_daily_contract(self):
        client = FakeHyperliquidClient()
        contract = discover_15m_outcomes(client.get_outcome_meta(), "BTC", WINDOW)
        self.assertEqual(contract["sides"]["up"]["spot_coin"], "#70")
        self.assertEqual(contract["sides"]["down"]["spot_coin"], "#71")

        # Daily 24h outcome (86400s) must be rejected, never substituted for 15m
        daily_client = FakeHyperliquidClient(window_end=WINDOW + 86400)
        with self.assertRaises(ValueError):
            discover_15m_outcomes(daily_client.get_outcome_meta(), "BTC", WINDOW)

    def test_builds_signals_and_order_preview(self):
        signals = build_signals(FakeHyperliquidClient(), self.prediction, self.config, lambda: NOW)
        self.assertEqual(len(signals), 2)
        up_sig = signals[0]
        self.assertEqual(up_sig["venue"], "hyperliquid")
        self.assertEqual(up_sig["instrument_id"], "#70:100000070")
        self.assertAlmostEqual(up_sig["probability"], 0.70)
        self.assertAlmostEqual(up_sig["entry_cost_per_unit"], 0.40)

        preview = preview_order(up_sig, self.config, network="testnet")
        self.assertTrue(preview["preview_only"])
        self.assertFalse(preview["live_execution_enabled"])
        self.assertAlmostEqual(preview["expected_roi"], 0.75)
        self.assertTrue(preview["eligible"])
        order_wire = preview["exchange_action_payload"]["orders"][0]
        self.assertEqual(order_wire["a"], 100000070)
        self.assertEqual(order_wire["p"], "0.4")
        self.assertEqual(order_wire["s"], "250.0")

    def test_unavailable_15m_outcomes_publish_explicit_venue_check(self):
        daily_client = FakeHyperliquidClient(window_end=WINDOW + 86400)
        feed = build_feed(daily_client, [self.prediction], self.config, lambda: NOW)
        self.assertEqual(feed["signals"], [])
        self.assertEqual(len(feed["venue_checks"]), 1)
        self.assertEqual(feed["venue_checks"][0]["venue"], "hyperliquid")
        self.assertEqual(feed["venue_checks"][0]["status"], "unavailable")

    def test_stale_book_and_insufficient_depth_fail_closed(self):
        client = FakeHyperliquidClient(asks=[{"px": "0.40", "sz": "10"}])  # Only $4 depth < $100
        with self.assertRaises(ValueError):
            quote_outcome_book(client.get_l2_book("#70"), 100, NOW, max_age_seconds=10)
        with self.assertRaises(ValueError):
            quote_outcome_book(client.get_l2_book("#70"), 100, NOW + 25, max_age_seconds=10)

    def test_credentials_save_and_load_enforces_separation_and_permissions(self):
        acct = "0x" + "1" * 40
        agent = "0x" + "2" * 40
        priv = "0x" + "a" * 64
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, 0o700)
            path = save_hyperliquid_credentials(acct, agent, priv, network="testnet", directory=tmp)
            loaded = load_hyperliquid_credentials(path)
            self.assertEqual(loaded["account_address"], acct)
            self.assertEqual(loaded["agent_address"], agent)
            self.assertEqual(loaded["network"], "testnet")
            self.assertEqual(loaded["agent_name"], "Kronos")
            # Re-saving over an existing file must fail (preserves existing credentials)
            with self.assertRaises(FileExistsError):
                save_hyperliquid_credentials(acct, agent, priv, directory=tmp)
            # Identical account and agent address must fail
            with self.assertRaises(ValueError):
                save_hyperliquid_credentials(acct, acct, priv, directory=tmp)

    def test_verify_agent_approval_checks_role_extra_agents_and_expiry(self):
        acct = "0x" + "1" * 40
        agent = "0x" + "2" * 40

        def fake_post(payload, network="mainnet", timeout=15):
            if payload["type"] == "userRole":
                return {"role": "agent", "data": {"user": acct}}
            if payload["type"] == "extraAgents":
                return [{"name": "Kronos", "address": agent, "validUntil": 2000000000000}]
            return {}

        with patch("trading.check_hyperliquid.post_info", side_effect=fake_post):
            res = verify_agent_approval(acct, agent, network="mainnet", now_ms=1700000000000)
            self.assertTrue(res["trading_authorization_verified"])
            self.assertTrue(res["expected_name_matches"])


if __name__ == "__main__":
    unittest.main()
