"""Hyperliquid HIP-4 outcome market discovery, quote adapter, and order preview.

Strictly enforces BTC/ETH 15-minute (900-second) binary Up/Down contract rules.
Never substitutes BTC/ETH spot or perpetual contracts when 15m outcomes are unavailable.
Leaves live mainnet order execution disabled.
"""
import argparse
from decimal import Decimal, ROUND_CEILING
import json
import logging
from pathlib import Path
import time

from trading.check_hyperliquid import ENDPOINTS, post_info
from trading.polymarket import write_feed
from trading.runner import ROOT, load_config, number, plan, positive

LOG = logging.getLogger("trading.hyperliquid")
OUTCOME_ASSET_OFFSET = 100_000_000


def encode_outcome(outcome_id, side_index):
    """Official Hyperliquid HIP-4 outcome asset encoding.

    encoding = 10 * outcome + side (side in {0, 1})
    spot coin = #<encoding>
    token name = +<encoding>
    asset ID = 100_000_000 + encoding
    """
    if isinstance(outcome_id, bool) or not isinstance(outcome_id, int) or outcome_id < 0:
        raise ValueError("outcome_id must be a non-negative integer")
    if isinstance(side_index, bool) or side_index not in (0, 1):
        raise ValueError("side_index must be 0 or 1")
    encoding = 10 * outcome_id + side_index
    return {
        "outcome_id": outcome_id,
        "side_index": side_index,
        "encoding": encoding,
        "spot_coin": f"#{encoding}",
        "token_name": f"+{encoding}",
        "asset_id": OUTCOME_ASSET_OFFSET + encoding,
    }


def discover_15m_outcomes(outcome_meta, asset, window_start):
    """Inspect outcomeMeta response for an exact 15-minute (900s) binary Up/Down contract.

    Returns a normalized contract descriptor or raises ValueError if unavailable.
    Never substitutes daily (24h) outcomes, spot, or perpetuals.
    """
    if not isinstance(outcome_meta, dict):
        raise ValueError("outcomeMeta response must be a JSON object")
    outcomes = outcome_meta.get("outcomes")
    if not isinstance(outcomes, list) or not outcomes:
        raise ValueError("No HIP-4 outcome contracts returned in outcomeMeta")

    window_start = int(window_start)
    expected_end = window_start + 900
    for item in outcomes:
        if not isinstance(item, dict):
            continue
        if str(item.get("underlying", item.get("asset", ""))).upper() != asset.upper():
            continue
        start_ts = item.get("windowStart", item.get("startTime"))
        end_ts = item.get("windowEnd", item.get("endTime", item.get("expiry")))
        # Convert milliseconds if > 1e11
        if isinstance(start_ts, (int, float)) and start_ts > 1e11:
            start_ts = int(start_ts // 1000)
        if isinstance(end_ts, (int, float)) and end_ts > 1e11:
            end_ts = int(end_ts // 1000)
        if start_ts != window_start or end_ts != expected_end:
            continue
        if item.get("closed") is True or item.get("settled") is True:
            raise ValueError("Hyperliquid 15m outcome contract is already closed or settled")

        side_specs = item.get("sideSpecs", [])
        if not isinstance(side_specs, list) or len(side_specs) != 2:
            raise ValueError("Expected binary sideSpecs with 2 sides")
        labels = [str(spec.get("label", spec.get("name", ""))).strip().lower() for spec in side_specs]
        side_map = {}
        for idx, label in enumerate(labels):
            if label in ("up", "yes"):
                side_map["up"] = encode_outcome(int(item["id"]), idx)
            elif label in ("down", "no"):
                side_map["down"] = encode_outcome(int(item["id"]), idx)
        if set(side_map) != {"up", "down"}:
            raise ValueError(f"Unsupported HIP-4 outcome labels: {labels}")

        return {
            "outcome_id": int(item["id"]),
            "asset": asset.upper(),
            "window_start": window_start,
            "window_end": expected_end,
            "reference_price": item.get("referencePrice"),
            "settlement_source": item.get("settlementSource", "HyperCore mark price"),
            "collateral": item.get("collateral", "USDC"),
            "fee_rate": float(item.get("feeRate", 0.0) or 0.0),
            "min_order_size": float(item.get("minOrderSize", 1.0) or 1.0),
            "sides": side_map,
        }
    raise ValueError(
        f"No matching 15-minute ({window_start}..{expected_end}) {asset} binary Up/Down HIP-4 outcome contract listed on Hyperliquid"
    )


def quote_outcome_book(l2_book, stake_usd, now, max_age_seconds=10, fee_rate=0.0, min_order_size=1.0):
    """Compute conservative all-in cost per $1-payout share for full $100 stake from Hyperliquid l2Book."""
    if not isinstance(l2_book, dict) or not isinstance(l2_book.get("levels"), list) or len(l2_book["levels"]) < 2:
        raise ValueError("Malformed Hyperliquid l2Book response")
    book_time_ms = l2_book.get("time")
    if not isinstance(book_time_ms, (int, float)):
        raise ValueError("Missing l2Book timestamp")
    quoted_at = float(book_time_ms) / 1000.0 if book_time_ms > 1e11 else float(book_time_ms)
    if not 0 <= now - quoted_at <= max_age_seconds:
        raise ValueError("Stale or future Hyperliquid l2Book snapshot")

    budget = Decimal(str(positive(stake_usd, "stake_usd")))
    minimum = Decimal(str(positive(min_order_size, "min_order_size")))
    if budget < minimum:
        raise ValueError("Stake is below minimum order notional")
    rate = Decimal(str(number(fee_rate, "fee_rate", minimum=0, maximum=1)))

    asks = l2_book["levels"][1]
    if not isinstance(asks, list) or not asks:
        raise ValueError("Empty ask book for Hyperliquid outcome")
    parsed_asks = []
    for level in asks:
        px = Decimal(str(positive(level["px"], "ask px")))
        sz = Decimal(str(positive(level["sz"], "ask sz")))
        if px >= Decimal(1):
            raise ValueError("Outcome ask price must be < 1.0")
        parsed_asks.append((px, sz))
    parsed_asks.sort(key=lambda item: item[0])

    available_shares = Decimal(0)
    for price, size in parsed_asks:
        available_shares += size
        fee = (rate * price).quantize(Decimal("0.0001"), rounding=ROUND_CEILING)
        cost = price + fee
        if cost >= Decimal(1):
            raise ValueError("All-in outcome cost must be < 1.0")
        quantity = budget / cost
        if quantity * price < minimum:
            continue
        if available_shares >= quantity:
            return float(cost), quoted_at
    raise ValueError("Insufficient ask depth for full stake on Hyperliquid outcome book")


def build_signals(info_client, prediction, config, clock=time.time):
    """Build runner-compatible binary signals for Hyperliquid 15m outcomes."""
    now = clock()
    asset = prediction["asset"]
    if asset not in config["assets"]:
        raise ValueError("asset is not enabled")
    window = int(number(prediction["window_start"], "window_start"))
    generated = number(prediction["generated_at"], "generated_at")
    probability = number(prediction["p_up"], "p_up", maximum=1)
    expected_price = positive(prediction["model_expected_price_usd"], "model_expected_price_usd")
    for field in ("forecast_id", "model_version"):
        if not isinstance(prediction.get(field), str) or not prediction[field].strip():
            raise ValueError(f"prediction requires {field}")
    if prediction["horizon_seconds"] != 900 or window % 900:
        raise ValueError("prediction must target an aligned 15-minute window")
    if not window <= generated <= now or not 0 <= now - window <= config["max_signal_age_seconds"]:
        raise ValueError("prediction is future or too late for entry")

    meta = info_client.get_outcome_meta()
    contract = discover_15m_outcomes(meta, asset, window)
    signals = []
    hl_config = {**config, "venues": list(set(config["venues"]) | {"hyperliquid"})}

    for side in ("up", "down"):
        try:
            side_info = contract["sides"][side]
            book = info_client.get_l2_book(side_info["spot_coin"])
            if book.get("coin") != side_info["spot_coin"]:
                raise ValueError("l2Book coin does not match requested outcome spot_coin")
            cost, quoted_at = quote_outcome_book(
                book,
                stake_usd=config["stake_usd"],
                now=clock(),
                max_age_seconds=config["max_quote_age_seconds"],
                fee_rate=contract["fee_rate"],
                min_order_size=contract["min_order_size"],
            )
            signal = {
                "venue": "hyperliquid",
                "asset": asset,
                "kind": "binary",
                "side": side,
                "instrument_id": f"{side_info['spot_coin']}:{side_info['asset_id']}",
                "window_start": window,
                "horizon_seconds": 900,
                "generated_at": generated,
                "quoted_at": quoted_at,
                "model_version": prediction["model_version"],
                "forecast_id": prediction["forecast_id"],
                "model_expected_price_usd": expected_price,
                "probability": probability if side == "up" else 1.0 - probability,
                "entry_cost_per_unit": cost,
                "executable_budget_usd": config["stake_usd"],
            }
            plan(signal, hl_config, clock())
            signals.append(signal)
        except ValueError as error:
            LOG.warning("Skipped Hyperliquid %s %s: %s", asset, side, error)

    return [
        s for s in signals
        if 0 <= clock() - s["quoted_at"] <= config["max_quote_age_seconds"]
        and clock() - window <= config["max_signal_age_seconds"]
    ]


def build_feed(info_client, predictions, config, clock=time.time):
    """Build signals or explicit unavailability checks for Hyperliquid."""
    feed = {"signals": [], "settlements": [], "venue_checks": []}
    for prediction in predictions:
        try:
            signals = build_signals(info_client, prediction, config, clock)
            feed["signals"].extend(signals)
            if signals:
                continue
            reason = "No fresh executable 15m outcome book with sufficient depth"
        except Exception as exc:
            LOG.warning("Hyperliquid 15m outcome unavailable: %s", exc)
            reason = str(exc)

        try:
            window = int(number(prediction["window_start"], "window_start"))
            generated = number(prediction["generated_at"], "generated_at")
            now = clock()
            if (prediction["asset"] not in config["assets"] or window % 900
                    or prediction["horizon_seconds"] != 900
                    or not window <= generated <= now
                    or not 0 <= now - window <= config["max_signal_age_seconds"]):
                continue
            positive(prediction["model_expected_price_usd"], "model_expected_price_usd")
            number(prediction["p_up"], "p_up", maximum=1)
            for field in ("forecast_id", "model_version"):
                if not isinstance(prediction.get(field), str) or not prediction[field].strip():
                    raise ValueError(f"invalid {field}")
            feed["venue_checks"].append({
                "venue": "hyperliquid",
                "asset": prediction["asset"],
                "window_start": window,
                "checked_at": now,
                "status": "unavailable",
                "reason": reason,
            })
        except (ValueError, TypeError, KeyError):
            continue
    return feed


def preview_order(signal, config, network="testnet", cloid="0x00000000000000000000000000000001"):
    """Construct a deterministic human-reviewable HIP-4 order preview without signing or sending."""
    hl_config = {**config, "venues": list(set(config["venues"]) | {"hyperliquid"})}
    planned = plan(signal, hl_config, signal["quoted_at"])
    spot_coin, asset_id_str = str(signal["instrument_id"]).split(":")
    asset_id = int(asset_id_str)
    limit_px = round(float(signal["entry_cost_per_unit"]), 4)
    sz = round(float(planned["quantity"]), 2)
    return {
        "preview_only": True,
        "live_execution_enabled": False,
        "network": network,
        "venue": "hyperliquid",
        "asset": planned["asset"],
        "side": planned["side"],
        "window_start": planned["window_start"],
        "spot_coin": spot_coin,
        "hyperliquid_asset_id": asset_id,
        "model_probability": round(planned["model_probability"], 4),
        "expected_roi": round(planned["expected_roi"], 4),
        "eligible": planned["eligible"],
        "exchange_action_payload": {
            "type": "order",
            "orders": [
                {
                    "a": asset_id,
                    "b": True,
                    "p": str(limit_px),
                    "s": str(sz),
                    "r": False,
                    "t": {"limit": {"tif": "Ioc"}},
                    "c": cloid,
                }
            ],
            "grouping": "na",
        },
    }


class LiveInfoClient:
    def __init__(self, network="mainnet"):
        self.network = network

    def get_outcome_meta(self):
        return post_info({"type": "outcomeMeta"}, network=self.network)

    def get_l2_book(self, coin):
        return post_info({"type": "l2Book", "coin": coin}, network=self.network)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", choices=tuple(ENDPOINTS), default="mainnet")
    parser.add_argument("--discover-only", action="store_true", help="Inspect live outcomeMeta for 15m BTC/ETH contracts")
    parser.add_argument("--predictions", type=Path, help="Input predictions JSON")
    parser.add_argument("--output", type=Path, help="Output Hyperliquid feed JSON")
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    args = parser.parse_args()

    client = LiveInfoClient(network=args.network)
    if args.discover_only:
        try:
            meta = client.get_outcome_meta()
            outcomes = meta.get("outcomes", []) if isinstance(meta, dict) else []
            print(json.dumps({
                "network": args.network,
                "outcome_count": len(outcomes),
                "outcomes_sample": outcomes[:5],
            }, indent=2))
        except Exception as exc:
            print(json.dumps({
                "network": args.network,
                "status": "unavailable",
                "error_type": type(exc).__name__,
                "reason": str(exc),
            }, indent=2))
        return 0

    if not args.predictions or not args.output:
        parser.error("Provide --discover-only or both --predictions and --output")
    config = load_config(args.config)
    predictions = json.loads(args.predictions.read_text())
    feed = build_feed(client, predictions, config)
    write_feed(args.output, feed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
