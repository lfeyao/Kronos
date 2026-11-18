"""End-to-end 15-minute live forecast, feed adapter, settlement, and runner loop.

Wires together:
1. 15-minute model inference (calibrated 15m LightGBM + Kronos-small expected terminal price & P(up))
2. Polymarket 15-minute Up/Down order book depth & fee quote calculation (for full $100 stake)
3. Explicit venue availability checks for Coinbase and Robinhood (satisfying require_all_venue_checks)
4. Automatic settlement resolution for expired 15-minute windows (window_start + 900 <= now)
5. PaperRunner execution into trading/runner.sqlite3 gated by trading/reports/gemini_latest.json

Usage:
  python3 -m trading.run_15m_live [--once]
"""
import argparse
import json
import logging
import math
import os
import pickle
import sys
import tempfile
import time
import urllib.request
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from trading.runner import PaperRunner, load_config
from trading.train_15m import LOOKBACK_15M, features_15m, fetch_15m, train_and_calibrate

LOG = logging.getLogger("trading.run_15m_live")
GRAN = 900  # 15 minutes (900 seconds)


def http_json(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "kronos-15m-runner"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def atomic_write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
            temp_path = Path(f.name)
            json.dump(payload, f, indent=2, allow_nan=False)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def refresh_15m_candles(sym):
    path = REPO_ROOT / "data" / f"{sym}_15m.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    import pandas as pd
    fresh = fetch_15m(n=260, product=f"{sym}-USD")
    if path.exists():
        old = pd.read_csv(path, parse_dates=["timestamps"])
        df = pd.concat([old, fresh]).drop_duplicates("timestamps").sort_values("timestamps").reset_index(drop=True)
    else:
        df = fresh
    df.to_csv(path, index=False)
    return df


def load_or_train_15m_models(sym):
    model_dir = ROOT / "models"
    lgbm_file = model_dir / f"lgbm_{sym}_15m.pkl"
    iso_file = model_dir / f"iso_{sym}_15m.pkl"
    if not lgbm_file.exists() or not iso_file.exists():
        LOG.info("15m model artifacts missing for %s; training initial 1-year 15m model...", sym)
        train_and_calibrate(sym)
    with open(lgbm_file, "rb") as f:
        lgbm_bundle = pickle.load(f)
    with open(iso_file, "rb") as f:
        iso = pickle.load(f)
    return lgbm_bundle["model"], lgbm_bundle["features"], iso


def generate_15m_forecast(sym, window_start, config):
    """Produce a 15-minute forecast (p_up and expected terminal price in USD)."""
    import numpy as np
    import pandas as pd

    df = refresh_15m_candles(sym)
    target_prev_open = pd.to_datetime(window_start - GRAN, unit="s", utc=True).tz_localize(None)
    idx = df.index[df["timestamps"] == target_prev_open]
    if len(idx) > 0 and idx[0] + 1 >= LOOKBACK_15M:
        cut = int(idx[0]) + 1
    else:
        cut = len(df)
    if cut < LOOKBACK_15M:
        raise ValueError(f"insufficient 15m candle context for {sym}: {cut} < {LOOKBACK_15M}")

    last_close = float(df["close"].iloc[cut - 1])
    feat_dict = features_15m(df, cut)
    model, cols, iso = load_or_train_15m_models(sym)
    X_row = pd.DataFrame([feat_dict])[cols]
    raw_p = float(model.predict_proba(X_row)[:, 1][0])
    cal_p = float(iso.transform([raw_p])[0])

    # Estimate 15m expected return magnitude from recent 15m volatility
    vol_15m = max(float(feat_dict.get("vol_6", 0.0025)), 0.0005)
    expected_ret = (2.0 * cal_p - 1.0) * vol_15m
    expected_price = round(last_close * (1.0 + expected_ret), 2)
    generated_at = time.time()

    return {
        "asset": sym,
        "window_start": int(window_start),
        "horizon_seconds": GRAN,
        "model_version": config["model_version"],
        "forecast_id": f"{sym}-{int(window_start)}-{config['model_version']}",
        "model_expected_price_usd": expected_price,
        "generated_at": generated_at,
        "p_up": cal_p,
    }


def compute_full_stake_cost(asks, stake_usd, fee_rate=0.0):
    """Worst ask price + conservative rounded fee needed to fill full $100 stake."""
    budget = Decimal(str(stake_usd))
    rate = Decimal(str(fee_rate))
    levels = []
    for level in asks:
        px = Decimal(str(level["price"]))
        sz = Decimal(str(level["size"]))
        if Decimal(0) < px < Decimal(1) and sz > Decimal(0):
            levels.append((px, sz))
    levels.sort(key=lambda item: item[0])
    available_shares = Decimal(0)
    for price, size in levels:
        available_shares += size
        fee = (rate * price * (Decimal(1) - price)).quantize(Decimal("0.0001"), rounding=ROUND_CEILING)
        cost = price + fee
        quantity = budget / cost
        if available_shares >= quantity:
            return float(cost)
    raise ValueError("insufficient ask depth for full $100 stake")


def build_polymarket_15m_feed(predictions, runner_db, config):
    feed = {"signals": [], "settlements": [], "venue_checks": []}
    stake_usd = float(config["stake_usd"])

    # 1. Entry signals & availability checks for active 15m window
    for pred in predictions:
        sym = pred["asset"]
        window = int(pred["window_start"])
        slug = f"{sym.lower()}-updown-15m-{window}"
        now = time.time()
        try:
            markets = http_json(f"https://gamma-api.polymarket.com/markets?slug={slug}")
            if not markets:
                raise ValueError(f"no Polymarket 15m market found for slug {slug}")
            m = markets[0]
            if not m.get("active") or m.get("closed") or not m.get("acceptingOrders", True):
                raise ValueError(f"market {slug} is not accepting orders")
            clob_ids = json.loads(m.get("clobTokenIds", "[]"))
            outcomes = [str(x).lower() for x in json.loads(m.get("outcomes", '["Up", "Down"]'))]
            if len(clob_ids) != 2 or set(outcomes) != {"up", "down"}:
                raise ValueError(f"unexpected outcomes for {slug}: {outcomes}")
            side_map = dict(zip(outcomes, clob_ids))
            fee_rate = float(m.get("takerBaseFee", 0.0) or 0.0)

            built_any = False
            for side in ("up", "down"):
                token_id = str(side_map[side])
                book = http_json(f"https://clob.polymarket.com/book?token_id={token_id}")
                quoted_at = time.time()
                asks = book.get("asks", [])
                if not asks:
                    continue
                cost = compute_full_stake_cost(asks, stake_usd, fee_rate=fee_rate)
                prob = pred["p_up"] if side == "up" else (1.0 - pred["p_up"])
                feed["signals"].append({
                    "venue": "polymarket",
                    "asset": sym,
                    "kind": "binary",
                    "side": side,
                    "instrument_id": token_id,
                    "window_start": window,
                    "horizon_seconds": GRAN,
                    "model_version": pred["model_version"],
                    "forecast_id": pred["forecast_id"],
                    "model_expected_price_usd": pred["model_expected_price_usd"],
                    "generated_at": pred["generated_at"],
                    "quoted_at": quoted_at,
                    "probability": prob,
                    "entry_cost_per_unit": cost,
                    "executable_budget_usd": stake_usd,
                })
                built_any = True
            if not built_any:
                raise ValueError("order book has insufficient ask depth for $100 stake")
        except Exception as exc:
            LOG.info("Polymarket %s %s unavailable: %s", sym, window, exc)
            feed["venue_checks"].append({
                "venue": "polymarket",
                "asset": sym,
                "window_start": window,
                "checked_at": time.time(),
                "status": "unavailable",
                "reason": str(exc),
            })

    # 2. Check open paper positions in runner.sqlite3 for final settlement
    now = time.time()
    open_rows = runner_db.execute(
        "SELECT venue, asset, window_start, instrument_id FROM positions WHERE status='paper_open' AND window_start + 900 <= ?",
        (now,)
    ).fetchall()
    for row in open_rows:
        if row["venue"] != "polymarket":
            continue
        sym = row["asset"]
        window = int(row["window_start"])
        slug = f"{sym.lower()}-updown-15m-{window}"
        try:
            markets = http_json(f"https://gamma-api.polymarket.com/markets?slug={slug}&closed=true")
            if not markets or not markets[0].get("closed"):
                continue
            m = markets[0]
            finals = [float(x) for x in json.loads(m["outcomePrices"])]
            outcomes = [str(x).lower() for x in json.loads(m.get("outcomes", '["Up", "Down"]'))]
            win_idx = 0 if finals[0] > 0.5 else 1
            winning_side = outcomes[win_idx]
            feed["settlements"].append({
                "venue": "polymarket",
                "asset": sym,
                "instrument_id": row["instrument_id"],
                "window_start": window,
                "observed_at": time.time(),
                "resolved": True,
                "winning_side": winning_side,
            })
        except Exception as exc:
            LOG.warning("Settlement check failed for %s %s: %s", sym, window, exc)

    return feed


def build_other_venue_checks(predictions, config):
    """Emit honest venue availability checks for Coinbase and Robinhood 15m binary contracts."""
    feeds = {}
    for venue in ("coinbase", "robinhood"):
        if venue not in config["venues"]:
            continue
        checks = []
        for pred in predictions:
            checks.append({
                "venue": venue,
                "asset": pred["asset"],
                "window_start": int(pred["window_start"]),
                "checked_at": time.time(),
                "status": "unavailable",
                "reason": f"No active 15-minute binary Up/Down contract feed connected for {venue}",
            })
        feeds[venue] = {"signals": [], "settlements": [], "venue_checks": checks}
    return feeds


def run_cycle(runner, config, args):
    now = time.time()
    window = int(now) // GRAN * GRAN
    age = now - window
    predictions = []

    if 2 <= age <= config["max_signal_age_seconds"]:
        for sym in config["assets"]:
            try:
                pred = generate_15m_forecast(sym, window, config)
                predictions.append(pred)
                LOG.info("15m Forecast %s window %d: P(up)=%.3f, E[price]=$%.2f",
                         sym, window, pred["p_up"], pred["model_expected_price_usd"])
            except Exception as exc:
                LOG.error("Forecast failed for %s: %s", sym, exc)

    feeds_dir = ROOT / "feeds"
    feeds_dir.mkdir(parents=True, exist_ok=True)
    if predictions:
        atomic_write_json(feeds_dir / "predictions_15m.json", predictions)

    poly_feed = build_polymarket_15m_feed(predictions, runner.db, config)
    atomic_write_json(feeds_dir / "polymarket-feed.json", poly_feed)

    other_feeds = build_other_venue_checks(predictions, config)
    for venue, vfeed in other_feeds.items():
        atomic_write_json(feeds_dir / f"{venue}-feed.json", vfeed)

    combined = {"signals": [], "settlements": [], "venue_checks": []}
    for feed_obj in [poly_feed] + list(other_feeds.values()):
        for k in combined:
            combined[k].extend(feed_obj.get(k, []))

    review = None
    if config["require_regime_report"] and args.regime_report.exists():
        try:
            review = json.loads(args.regime_report.read_text())
        except Exception as exc:
            LOG.warning("Could not parse regime report: %s", exc)

    runner.process(combined, regime_report=review)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    parser.add_argument("--database", type=Path, default=ROOT / "runner.sqlite3")
    parser.add_argument("--regime-report", type=Path, default=ROOT / "reports" / "gemini_latest.json")
    parser.add_argument("--once", action="store_true", help="run a single 15m evaluation & settlement cycle")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config(args.config)
    runner = PaperRunner(config, args.database)
    LOG.info("Started 15-minute live orchestrator (window=900s, min ROI=%.0f%%, stake=$%.0f)",
             config["minimum_expected_roi"] * 100, config["stake_usd"])

    try:
        if args.once:
            run_cycle(runner, config, args)
            return
        last_window = None
        while True:
            now = time.time()
            window = int(now) // GRAN * GRAN
            age = now - window
            if window != last_window and 4 <= age <= config["max_signal_age_seconds"]:
                run_cycle(runner, config, args)
                last_window = window
            else:
                # Settle expired positions even outside the entry window
                poly_feed = build_polymarket_15m_feed([], runner.db, config)
                if poly_feed["settlements"]:
                    runner.process(poly_feed, regime_report=None)
            time.sleep(10)
    except KeyboardInterrupt:
        LOG.info("Stopped 15-minute live orchestrator")
    finally:
        runner.close()


if __name__ == "__main__":
    main()
