"""Paper runner. The JSON feed is the boundary for future model/MCP adapters.

No credentials, account mutations, or live order submission occur here.
Run from the repository root: python3 -m trading.runner --help
"""
import argparse
import json
import logging
import math
import sqlite3
import time
from pathlib import Path

from trading.regime import allow_asset, validate_report

LOG = logging.getLogger("trading.runner")
ROOT = Path(__file__).resolve().parent


def number(value, name, minimum=0, maximum=None):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    value = float(value)
    if not math.isfinite(value) or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"invalid {name}: {value}")
    return value


def positive(value, name):
    value = number(value, name)
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def load_config(path):
    config = json.loads(Path(path).read_text())
    if config["interval_seconds"] != 900:
        raise ValueError("this runner requires 900-second windows")
    number(config["minimum_expected_roi"], "minimum_expected_roi")
    stake = positive(config["stake_usd"], "stake_usd")
    balance = positive(config["starting_balance_usd"], "starting_balance_usd")
    if stake > balance:
        raise ValueError("stake exceeds starting balance")
    for key in ("max_signal_age_seconds", "max_quote_age_seconds"):
        number(config[key], key, maximum=899)
    if type(config["require_regime_report"]) is not bool:
        raise ValueError("require_regime_report must be true or false")
    if type(config["require_all_venue_checks"]) is not bool:
        raise ValueError("require_all_venue_checks must be true or false")
    positive(config["regime_report_max_age_hours"], "regime_report_max_age_hours")
    if not isinstance(config["model_version"], str) or not config["model_version"].strip():
        raise ValueError("model_version must be a nonempty string")
    if not config["venues"] or not set(config["venues"]) <= {"coinbase", "robinhood", "polymarket"}:
        raise ValueError("unsupported venues")
    if not config["assets"] or not set(config["assets"]) <= {"BTC", "ETH"}:
        raise ValueError("unsupported assets")
    return config


def plan(signal, config, now):
    """Evaluate a 15-minute Up/Down prediction contract held to resolution.

    `entry_cost_per_unit` includes the ask, depth/slippage, and applicable fees.
    Binary payout is one dollar on a win, zero on a loss.
    """
    venue, asset = signal["venue"], signal["asset"]
    if venue not in config["venues"] or asset not in config["assets"]:
        raise ValueError("venue or asset is not enabled")
    window = number(signal["window_start"], "window_start")
    if window % 900 or not window <= now < window + 900:
        raise ValueError("signal is not for the current 15-minute window")
    if now - window > config["max_signal_age_seconds"]:
        raise ValueError("too late to enter a full-window forecast")
    if signal["horizon_seconds"] != 900:
        raise ValueError("model horizon must be 15 minutes")
    generated = number(signal["generated_at"], "generated_at")
    quoted = number(signal["quoted_at"], "quoted_at")
    if not window <= generated <= now or now - generated > config["max_signal_age_seconds"]:
        raise ValueError("stale or future model signal")
    if not window <= quoted <= now or now - quoted > config["max_quote_age_seconds"]:
        raise ValueError("stale or future quote")
    stake = float(config["stake_usd"])
    if positive(signal["executable_budget_usd"], "executable_budget_usd") < stake:
        raise ValueError("insufficient executable liquidity at the quoted cost")
    cost = positive(signal["entry_cost_per_unit"], "entry_cost_per_unit")
    expected_price = positive(signal["model_expected_price_usd"], "model_expected_price_usd")
    if not isinstance(signal["forecast_id"], str) or not signal["forecast_id"].strip():
        raise ValueError("forecast_id must identify the common model forecast")
    if not isinstance(signal.get("model_version"), str) or not signal["model_version"].strip():
        raise ValueError("model_version must identify the forecast checkpoint")
    kind, side = signal["kind"], signal["side"]
    if not isinstance(signal["instrument_id"], str) or not signal["instrument_id"].strip():
        raise ValueError("instrument_id must be a nonempty string")
    if kind != "binary" or side not in ("up", "down"):
        raise ValueError("only Up/Down prediction contracts are supported")
    probability = number(signal["probability"], "probability", maximum=1)
    payout = probability
    if cost >= 1:
        raise ValueError("binary entry cost must be less than its winning payout")
    quantity = stake / cost
    expected_profit = quantity * payout - stake
    roi = expected_profit / stake
    if not all(math.isfinite(value) for value in (quantity, expected_profit, roi)):
        raise ValueError("non-finite trade economics")
    return {
        "venue": venue, "asset": asset, "window_start": int(window),
        "kind": kind, "side": side, "instrument_id": str(signal["instrument_id"]),
        "quantity": quantity, "stake_usd": stake,
        "entry_cost_per_unit": cost, "expected_profit_usd": expected_profit,
        "expected_roi": roi,
        "forecast_id": signal["forecast_id"], "model_version": signal.get("model_version"),
        "model_expected_price_usd": expected_price, "generated_at": generated,
        "quoted_at": quoted, "model_probability": probability,
        "eligible": roi > float(config["minimum_expected_roi"]),
    }


class PaperRunner:
    def __init__(self, config, database):
        self.config = config
        self.db = sqlite3.connect(database, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS accounts(
                venue TEXT PRIMARY KEY, available_usd REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS positions(
                id INTEGER PRIMARY KEY, venue TEXT, asset TEXT, window_start INTEGER,
                kind TEXT, side TEXT, instrument_id TEXT, quantity REAL,
                stake_usd REAL, entry_cost_per_unit REAL, expected_profit_usd REAL,
                expected_roi REAL, status TEXT, opened_at REAL, closed_at REAL,
                realized_profit_usd REAL,
                UNIQUE(venue, asset, window_start));
            CREATE TABLE IF NOT EXISTS decisions(
                id INTEGER PRIMARY KEY, evaluated_at REAL, payload TEXT);
            CREATE TABLE IF NOT EXISTS regime_reports(
                report_id TEXT PRIMARY KEY, first_seen_at REAL, payload TEXT);
        """)
        if "regime_report_id" not in {row[1] for row in self.db.execute("PRAGMA table_info(positions)")}:
            self.db.execute("ALTER TABLE positions ADD COLUMN regime_report_id TEXT")
        existing_columns = {row[1] for row in self.db.execute("PRAGMA table_info(positions)")}
        for column, sqltype in (("forecast_id", "TEXT"), ("model_version", "TEXT"),
                                ("model_expected_price_usd", "REAL")):
            if column not in existing_columns:
                self.db.execute(f"ALTER TABLE positions ADD COLUMN {column} {sqltype}")
        with self.db:
            for venue in config["venues"]:
                self.db.execute("INSERT OR IGNORE INTO accounts VALUES (?, ?)",
                                (venue, config["starting_balance_usd"]))

    def close(self):
        self.db.close()

    def process(self, feed, now=None, regime_report=None):
        """Compare venues using a common forecast; enter once per asset/window."""
        now = time.time() if now is None else now
        if not isinstance(feed, dict) or any(not isinstance(feed.get(key, []), list) for key in ("signals", "settlements", "venue_checks")):
            raise ValueError("feed must contain signals/settlements arrays")
        if any(not isinstance(item, dict) for key in ("signals", "settlements", "venue_checks") for item in feed.get(key, [])):
            raise ValueError("feed entries must be objects")
        self.settle(feed.get("settlements", []), now)
        report_error = None
        if self.config["require_regime_report"]:
            try:
                validate_report(regime_report, self.config, now)
                payload = json.dumps(regime_report, sort_keys=True, allow_nan=False)
                with self.db:
                    prior = self.db.execute("SELECT payload FROM regime_reports WHERE report_id=?",
                                            (regime_report["report_id"],)).fetchone()
                    if prior and prior[0] != payload:
                        raise ValueError("nightly report ID was reused with changed contents")
                    self.db.execute("INSERT OR IGNORE INTO regime_reports VALUES (?,?,?)",
                                    (regime_report["report_id"], now, payload))
            except (ValueError, TypeError, KeyError) as error:
                report_error = str(error)
        candidates = {}
        checked = {}
        for check in feed.get("venue_checks", []):
            try:
                if check["venue"] not in self.config["venues"] or check["status"] != "unavailable":
                    raise ValueError("venue checks must describe an enabled, unavailable venue")
                if not isinstance(check["reason"], str) or not check["reason"].strip():
                    raise ValueError("unavailable venue requires a reason")
                age = now - number(check["checked_at"], "checked_at")
                if not 0 <= age <= self.config["max_quote_age_seconds"]:
                    raise ValueError("stale venue availability check")
                key = (check["asset"], number(check["window_start"], "window_start"))
                checked.setdefault(key, set()).add(check["venue"])
                self.record(now, {"decision": "venue_unavailable", **check})
            except (ValueError, TypeError, KeyError) as error:
                self.record(now, {"decision": "invalid_venue_check", "reason": str(error)})
        for signal in feed.get("signals", []):
            report_id = None
            if self.config["require_regime_report"]:
                try:
                    if report_error:
                        raise ValueError(report_error)
                    report_id = allow_asset(regime_report, signal, self.config)
                except (ValueError, TypeError, KeyError) as error:
                    self.record(now, {"decision": "regime_blocked", "asset": signal.get("asset"),
                                      "venue": signal.get("venue"), "reason": str(error)})
                    continue
            try:
                candidate = plan(signal, self.config, now)
                candidate["regime_report_id"] = report_id
                key = (candidate["asset"], candidate["window_start"])
                candidates.setdefault(key, []).append(candidate)
                checked.setdefault(key, set()).add(candidate["venue"])
                self.record(now, {"decision": "evaluated", **candidate})
            except (ValueError, TypeError, KeyError) as error:
                self.record(now, {"decision": "invalid", "reason": str(error)})
                LOG.warning("Skipped signal: %s", error)
        selections = []
        for key, alternatives in candidates.items():
            missing = set(self.config["venues"]) - checked.get(key, set())
            if self.config["require_all_venue_checks"] and missing:
                self.record(now, {"decision": "awaiting_venues", "asset": key[0],
                                  "window_start": key[1], "missing": sorted(missing)})
                continue
            identities = {(item["forecast_id"], item["model_version"], item["model_expected_price_usd"], item["generated_at"])
                          for item in alternatives}
            if len(identities) != 1:
                self.record(now, {"decision": "forecast_mismatch", "asset": key[0], "window_start": key[1]})
                continue
            alternatives.sort(key=lambda item: (-item["expected_roi"], item["venue"], item["side"]))
            self.record(now, {"decision": "venue_comparison", "asset": key[0],
                              "window_start": key[1], "alternatives": alternatives})
            selections.append(alternatives)
        # Prioritize higher-ROI opportunities when assets compete for a venue's cash.
        selections.sort(key=lambda items: -items[0]["expected_roi"])
        for alternatives in selections:
            for candidate in alternatives:
                if not candidate["eligible"]:
                    break
                result = self.enter(candidate, now)
                if result != "insufficient_balance":
                    break

    def record(self, now, payload):
        with self.db:
            self.db.execute("INSERT INTO decisions(evaluated_at,payload) VALUES (?,?)",
                            (now, json.dumps(payload, allow_nan=False)))

    def enter(self, candidate, now):
        # Serialize the duplicate check, balance reservation, and insert together.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            key = (candidate["venue"], candidate["asset"], candidate["window_start"])
            exists = self.db.execute("SELECT 1 FROM positions WHERE asset=? AND window_start=?", key[1:]).fetchone()
            balance = self.db.execute("SELECT available_usd FROM accounts WHERE venue=?", (key[0],)).fetchone()[0]
            if exists or balance < candidate["stake_usd"]:
                self.db.rollback()
                self.record(now, {"decision": "skipped", "reason": "duplicate" if exists else "insufficient_balance", **candidate})
                return "duplicate" if exists else "insufficient_balance"
            fields = ("venue", "asset", "window_start", "kind", "side", "instrument_id",
                      "quantity", "stake_usd", "entry_cost_per_unit", "expected_profit_usd", "expected_roi",
                      "regime_report_id", "forecast_id", "model_version", "model_expected_price_usd")
            self.db.execute(
                "INSERT INTO positions(" + ",".join(fields) + ",status,opened_at) VALUES (" +
                ",".join("?" for _ in fields) + ",?,?)",
                [candidate[field] for field in fields] + ["paper_open", now])
            self.db.execute("UPDATE accounts SET available_usd=available_usd-? WHERE venue=?",
                            (candidate["stake_usd"], key[0]))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        LOG.info("PAPER %s %s %s $%.2f; expected ROI %.2f%%",
                 key[0], key[1], candidate["side"], candidate["stake_usd"], 100 * candidate["expected_roi"])
        self.record(now, {"decision": "venue_selected", **candidate})
        return "opened"

    def settle(self, settlements, now):
        """Apply final Up/Down outcomes. Missing outcomes keep capital reserved."""
        for settlement in settlements:
            try:
                window = number(settlement["window_start"], "window_start")
                observed = number(settlement["observed_at"], "observed_at")
                if not window + 900 <= observed <= now:
                    raise ValueError("settlement precedes expiry or is in the future")
                with self.db:
                    # UPDATE below is conditional, making repeated feed reads idempotent.
                    self.db.execute("BEGIN IMMEDIATE")
                    row = self.db.execute(
                        "SELECT * FROM positions WHERE venue=? AND asset=? AND window_start=? AND status='paper_open'",
                        (settlement["venue"], settlement["asset"], window)).fetchone()
                    if row is None:
                        continue
                    if settlement["instrument_id"] != row["instrument_id"]:
                        raise ValueError("settlement instrument mismatch")
                    if row["kind"] != "binary" or row["side"] not in ("up", "down"):
                        raise ValueError("legacy non-prediction position requires separate reconciliation")
                    if settlement["resolved"] is not True or settlement["winning_side"] not in ("up", "down"):
                        raise ValueError("binary outcome is not final")
                    payout = float(row["side"] == settlement["winning_side"])
                    proceeds = row["quantity"] * payout
                    self.db.execute("UPDATE positions SET status='paper_closed', closed_at=?, realized_profit_usd=? WHERE id=?",
                                    (observed, proceeds - row["stake_usd"], row["id"]))
                    self.db.execute("UPDATE accounts SET available_usd=available_usd+? WHERE venue=?", (proceeds, row["venue"]))
            except (ValueError, TypeError, KeyError) as error:
                self.record(now, {"decision": "invalid_settlement", "reason": str(error)})
                LOG.warning("Skipped settlement: %s", error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    parser.add_argument("--feed", required=True, action="append", type=Path,
                        help="repeat for each venue's JSON feed; all are compared together")
    parser.add_argument("--database", type=Path, default=ROOT / "runner.sqlite3")
    parser.add_argument("--regime-report", type=Path, default=ROOT / "reports" / "gemini_latest.json")
    parser.add_argument("--once", action="store_true", help="process current feed once")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    runner = PaperRunner(load_config(args.config), args.database)
    LOG.info("PAPER ONLY: ROI > %.0f%%, $%.2f/trade; live MCP adapters are not connected",
             runner.config["minimum_expected_roi"] * 100, runner.config["stake_usd"])
    try:
        while True:
            try:
                review = None
                if runner.config["require_regime_report"]:
                    try:
                        review = json.loads(args.regime_report.read_text())
                    except (OSError, ValueError):
                        pass  # Missing/invalid review blocks new entries, never settlements.
                combined = {"signals": [], "settlements": [], "venue_checks": []}
                for path in args.feed:
                    try:
                        incoming = json.loads(path.read_text())
                        if not isinstance(incoming, dict) or any(not isinstance(incoming.get(key, []), list)
                                                                for key in combined):
                            raise ValueError("invalid venue feed")
                        for key in combined:
                            combined[key].extend(incoming.get(key, []))
                    except (OSError, ValueError):
                        LOG.warning("Feed %s unavailable; its venue cannot count as checked", path)
                runner.process(combined, regime_report=review)
            except (OSError, ValueError, TypeError, KeyError):
                LOG.exception("Feed unavailable/invalid; no new entries from this cycle")
                if args.once:
                    raise
            if args.once:
                break
            # Poll for fresh quotes/settlements; entries remain keyed to UTC quarter-hours.
            time.sleep(2)
    except KeyboardInterrupt:
        LOG.info("Stopped")
    finally:
        runner.close()


if __name__ == "__main__":
    main()
