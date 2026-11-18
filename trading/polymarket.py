"""Read-only Polymarket SDK adapter producing inputs for the paper runner.

Install the optional dependency in trading/requirements.txt in a project venv.
This module never creates a secure client, signs, or submits an order.
"""
import argparse
from datetime import datetime
from decimal import Decimal, ROUND_CEILING
import json
import logging
import os
from pathlib import Path
import tempfile
import time

from trading.runner import ROOT, load_config, number, plan, positive

LOG = logging.getLogger("trading.polymarket")


def epoch(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("SDK timestamp must be a timezone-aware datetime")
    return value.timestamp()


def decimal(value, name, maximum=None):
    positive(value, name)
    result = Decimal(str(value))
    if maximum is not None and result >= maximum:
        raise ValueError(f"invalid {name}")
    return result


def quote_cost(book, trading, stake, now, max_age):
    """Conservative all-in cost using the worst ask required for full size.

    Fee rounding is rounded UP to $0.0001 per share, conservatively overestimating
    an aggregate cash fee. No last-price fallback. Supports the documented linear
    fee curve only; unknown fee curves fail closed.
    """
    quoted_at = epoch(book.timestamp)
    if not 0 <= now - quoted_at <= max_age:
        raise ValueError("stale or future order book")
    if trading.fees_enabled is False:
        rate = Decimal(0)
    elif trading.fees_enabled is True and trading.fee_schedule is not None:
        schedule = trading.fee_schedule
        if schedule.exponent != 1:
            raise ValueError("unsupported fee exponent")
        rate = Decimal(str(number(schedule.rate, "fee rate", maximum=1)))
    else:
        raise ValueError("fee configuration is unavailable")
    minimum = decimal(book.min_order_size, "minimum order size")
    budget = decimal(stake, "stake")
    if budget < minimum:
        raise ValueError("stake is below the market minimum notional")
    levels = sorted((decimal(level.price, "ask price", Decimal(1)),
                     decimal(level.size, "ask size")) for level in book.asks)
    available_shares = Decimal(0)
    for price, size in levels:
        available_shares += size
        fee = (rate * price * (1 - price)).quantize(Decimal("0.0001"), rounding=ROUND_CEILING)
        cost = price + fee
        # Charge every share at the worst ask, even though some can fill cheaper.
        # For rate <= 1 this cost increases monotonically with the price.
        quantity = budget / cost
        if quantity * price < minimum:
            continue
        if available_shares >= quantity:
            return float(cost), quoted_at
    raise ValueError("insufficient ask depth for the full stake")


def build_signals(client, prediction, config, clock=time.time):
    """One model prediction -> fresh Up and Down signals, mapped by label.

    Prediction fields: asset, window_start, horizon_seconds, generated_at, p_up,
    forecast_id, model_version, model_expected_price_usd.
    Caller must provide calibrated probability for the market's resolution rule.
    """
    now = clock()
    asset = prediction["asset"]
    if asset not in config["assets"]:
        raise ValueError("asset is not enabled")
    window = number(prediction["window_start"], "window_start")
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
    slug = f"{asset.lower()}-updown-15m-{int(window)}"
    market = client.get_market(slug=slug)
    if market.slug != slug or market.version not in ("v1", "v2"):
        raise ValueError("unsupported or mismatched market")
    state = market.state
    if state.active is not True or state.closed is not False or state.accepting_orders is not True:
        raise ValueError("market is not accepting orders")
    if epoch(state.end_date) != window + 900:
        raise ValueError("market expiry does not match the model horizon")
    outcomes = {outcome.label.lower(): outcome for outcome in (market.outcomes.yes, market.outcomes.no)}
    if set(outcomes) != {"up", "down"}:
        raise ValueError("expected exactly Up/Down outcomes")
    signals = []
    for side in ("up", "down"):
        try:
            outcome = outcomes[side]
            instrument = outcome.position_id if market.version == "v2" else outcome.token_id
            if not instrument:
                raise ValueError("missing outcome instrument ID")
            book = client.get_order_book(asset_id=instrument)
            if str(book.asset_id) != str(instrument) or str(book.condition_id) != str(market.condition_id):
                raise ValueError("order book does not match the market outcome")
            cost, quoted_at = quote_cost(book, market.trading, config["stake_usd"], clock(), config["max_quote_age_seconds"])
            signal = dict(venue="polymarket", asset=asset, kind="binary", side=side,
                          instrument_id=str(instrument), window_start=int(window), horizon_seconds=900,
                          generated_at=generated, quoted_at=quoted_at,
                          model_version=prediction.get("model_version"),
                          forecast_id=prediction["forecast_id"], model_expected_price_usd=expected_price,
                          probability=probability if side == "up" else 1 - probability,
                          entry_cost_per_unit=cost, executable_budget_usd=config["stake_usd"])
            plan(signal, config, clock())  # Recheck freshness after SDK requests.
            signals.append(signal)
        except ValueError as error:
            LOG.warning("Skipped %s %s: %s", asset, side, error)
    # Both reads consume time; ensure earlier book is still fresh at publication.
    return [signal for signal in signals
            if 0 <= clock() - signal["quoted_at"] <= config["max_quote_age_seconds"]
            and clock() - window <= config["max_signal_age_seconds"]]


def build_feed(client, predictions, config, clock=time.time):
    feed = {"signals": [], "settlements": [], "venue_checks": []}
    for prediction in predictions:
        try:
            signals = build_signals(client, prediction, config, clock)
            feed["signals"].extend(signals)
            if signals:
                continue
            reason = "No fresh executable book with supported fees and sufficient depth"
        except Exception:
            LOG.exception("Prediction/market unavailable; skipping")
            reason = "Prediction or public market data unavailable"
        # Record a completed availability check only for a valid current model
        # target. Missing/stale inputs must not authorize another venue's entry.
        try:
            window = number(prediction["window_start"], "window_start")
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
                if not isinstance(prediction[field], str) or not prediction[field].strip():
                    raise ValueError(f"invalid {field}")
            feed["venue_checks"].append(dict(venue="polymarket", asset=prediction["asset"],
                window_start=window, checked_at=now, status="unavailable", reason=reason))
        except (ValueError, TypeError, KeyError):
            continue
    return feed


def write_feed(path, feed):
    """Publish atomically so the runner cannot read a partially written file."""
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(feed, stream, allow_nan=False)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="dedicated Polymarket feed; do not share with other writers")
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    config = load_config(args.config)
    if "polymarket" not in config["venues"]:
        parser.error("Polymarket is disabled in config")
    if args.output.resolve() == args.predictions.resolve():
        parser.error("predictions and output paths must differ")
    try:
        from polymarket import PublicClient
    except ImportError:
        parser.error("install the optional polymarket-client dependency from trading/requirements.txt")
    with PublicClient() as client:
        while True:
            feed = {"signals": [], "settlements": [], "venue_checks": []}
            try:
                predictions = json.loads(args.predictions.read_text())
                if not isinstance(predictions, list):
                    raise ValueError("predictions must be a JSON array")
                feed = build_feed(client, predictions, config)
            except (OSError, ValueError, TypeError):
                LOG.exception("Predictions unavailable; publishing empty feed")
            write_feed(args.output, feed)
            if args.once:
                return
            time.sleep(2)


if __name__ == "__main__":
    main()
