"""Coinbase BTC/ETH spot PAPER engine. No keys, account APIs, or order submission.

Buy/hold cash only. Timed exits use fresh executable bids after the UTC window
ends. Missing quotes defer exits; forecasts and regime decisions never defer them.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time

from trading.regime import allow_asset, validate_report
from trading.runner import number, positive

ROOT = Path(__file__).resolve().parent
STRATEGY = "coinbase_spot_15m"


def config_hash(config):
    """Bind research approval to the exact costs, sizing, model, and entry rules."""
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def validate_config(config):
    if (config["execution_mode"] != "paper" or config["strategy"] != STRATEGY
            or config["venue"] != "coinbase" or config["interval_seconds"] != 900):
        raise ValueError("Only Coinbase 15-minute spot paper mode is supported")
    if not config["assets"] or not set(config["assets"]) <= {"BTC", "ETH"}:
        raise ValueError("Only BTC/ETH spot products are supported")
    if positive(config["stake_usd"], "stake") > positive(config["starting_balance_usd"], "balance"):
        raise ValueError("stake exceeds initial cash")
    for key in ("max_signal_age_seconds", "max_quote_age_seconds"):
        number(config[key], key, maximum=899)
    positive(config["regime_report_max_age_hours"], "report age")
    if not isinstance(config["model_version"], str) or not config["model_version"].strip():
        raise ValueError("model_version is required")
    if config["minimum_expected_net_return"] is not None:
        number(config["minimum_expected_net_return"], "minimum_expected_net_return")
    # Null costs deliberately pause entries until assumptions are supplied.
    for key in ("buy_fee_rate", "sell_fee_rate", "entry_slippage_bps",
                "exit_slippage_bps", "expected_exit_half_spread_bps"):
        if config[key] is not None:
            value = number(config[key], key)
            if value >= (1 if key.endswith("fee_rate") else 10000):
                raise ValueError("fee/spread/slippage must be below 100%")
    return config


def load_config(path=ROOT / "spot_config.json"):
    return validate_config(json.loads(Path(path).read_text()))


def quote(value, config, now):
    asset = value["asset"]
    if (asset not in config["assets"] or value["venue"] != "coinbase"
            or value["product_id"] != f"{asset}-USD"):
        raise ValueError("quote is not for an enabled Coinbase spot product")
    observed = number(value["quoted_at"], "quoted_at")
    if not observed <= now or now - observed > config["max_quote_age_seconds"]:
        raise ValueError("quote is stale or future-dated")
    bid = positive(value["bid_usd"], "bid_usd")
    ask = positive(value["ask_usd"], "ask_usd")
    if bid > ask:
        raise ValueError("crossed order book")
    return dict(value, bid_usd=bid, ask_usd=ask, quoted_at=observed,
                bid_size=positive(value["bid_size"], "bid_size"),
                ask_size=positive(value["ask_size"], "ask_size"))


def plan(forecast, book, config, now):
    validate_config(config)
    book = quote(book, config, now)
    if forecast["asset"] != book["asset"] or forecast["product_id"] != book["product_id"]:
        raise ValueError("forecast/quote product mismatch")
    if forecast.get("price_basis") != "mid" or forecast["horizon_seconds"] != 900:
        raise ValueError("forecast must estimate the 15-minute terminal midpoint")
    if forecast["model_version"] != config["model_version"]:
        raise ValueError("forecast checkpoint differs from configuration")
    if not isinstance(forecast["forecast_id"], str) or not forecast["forecast_id"].strip():
        raise ValueError("forecast_id is required")
    window = number(forecast["window_start"], "window_start")
    generated = number(forecast["generated_at"], "generated_at")
    if window % 900 or not window <= generated <= now < window + 900:
        raise ValueError("forecast does not describe the current UTC quarter-hour")
    if now - window > config["max_signal_age_seconds"] or now - generated > config["max_signal_age_seconds"]:
        raise ValueError("forecast is stale or entry is too late")
    terminal = positive(forecast["model_expected_price_usd"], "model_expected_price_usd")
    if config["minimum_expected_net_return"] is None:
        raise ValueError("spot return threshold is unset; entries paused")
    costs = {}
    for key in ("buy_fee_rate", "sell_fee_rate", "entry_slippage_bps",
                "exit_slippage_bps", "expected_exit_half_spread_bps"):
        if config[key] is None:
            raise ValueError("spot cost assumptions are unset; entries paused")
        costs[key] = float(config[key])
    if not isinstance(config["cost_assumption_source"], str) or not config["cost_assumption_source"].strip():
        raise ValueError("cost assumption provenance is required")
    stake = float(config["stake_usd"])
    entry_price = book["ask_usd"] * (1 + costs["entry_slippage_bps"] / 10000)
    quantity = stake / (entry_price * (1 + costs["buy_fee_rate"]))
    if quantity > book["ask_size"]:
        raise ValueError("insufficient ask depth for full stake")
    expected_bid = terminal * (1 - costs["expected_exit_half_spread_bps"] / 10000)
    expected_net = quantity * expected_bid * (1 - costs["exit_slippage_bps"] / 10000) * (1 - costs["sell_fee_rate"])
    net_return = expected_net / stake - 1
    if not all(math.isfinite(x) and x > 0 for x in (entry_price, quantity, expected_bid, expected_net)):
        raise ValueError("non-finite trade economics")
    return dict(asset=forecast["asset"], product_id=book["product_id"],
                window_start=int(window), exit_due_at=int(window + 900),
                quantity=quantity, stake_usd=stake, entry_price_usd=entry_price,
                entry_fee_usd=stake - quantity * entry_price,
                expected_net_return=net_return, expected_profit_usd=expected_net - stake,
                forecast=dict(forecast), quote=dict(book), costs=costs,
                cost_assumption_source=config["cost_assumption_source"],
                eligible=net_return > float(config["minimum_expected_net_return"]))


class SpotPaperRunner:
    def __init__(self, config, database):
        self.config = validate_config(config)
        self.db = sqlite3.connect(database, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS spot_cash(id INTEGER PRIMARY KEY CHECK(id=1), usd REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS spot_positions(
                id INTEGER PRIMARY KEY, asset TEXT NOT NULL, window_start INTEGER NOT NULL,
                exit_due_at REAL NOT NULL, status TEXT NOT NULL, opened_at REAL NOT NULL,
                closed_at REAL, quantity REAL NOT NULL, invested_usd REAL NOT NULL,
                proceeds_usd REAL, realized_pnl_usd REAL, entry TEXT NOT NULL, exit TEXT,
                UNIQUE(asset, window_start));
            CREATE UNIQUE INDEX IF NOT EXISTS spot_one_open_per_asset ON spot_positions(asset) WHERE status='open';
            CREATE TABLE IF NOT EXISTS spot_reports(report_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS spot_decisions(id INTEGER PRIMARY KEY, evaluated_at REAL, payload TEXT);
        """)
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO spot_cash VALUES(1, ?)", (config["starting_balance_usd"],))

    def close(self):
        self.db.close()

    def record(self, now, payload):
        with self.db:
            self.db.execute("INSERT INTO spot_decisions(evaluated_at,payload) VALUES(?,?)",
                            (now, json.dumps(payload, sort_keys=True, allow_nan=False)))

    def close_due(self, books, now):
        # Separate transaction per asset. Repeated quotes/restarts cannot credit twice.
        rows = self.db.execute("SELECT * FROM spot_positions WHERE status='open' AND exit_due_at<=?", (now,)).fetchall()
        for position in rows:
            book = books.get(position["asset"])
            if (book is None or book["quoted_at"] < position["exit_due_at"]
                    or book["bid_size"] < position["quantity"]):
                self.record(now, {"decision": "exit_deferred", "position_id": position["id"],
                                  "reason": "fresh full-size post-deadline bid required"})
                continue
            entry = json.loads(position["entry"])
            price = book["bid_usd"] * (1 - entry["costs"]["exit_slippage_bps"] / 10000)
            fee = position["quantity"] * price * entry["costs"]["sell_fee_rate"]
            proceeds = position["quantity"] * price - fee
            if not math.isfinite(proceeds) or proceeds < 0:
                raise ValueError("invalid exit economics")
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                changed = self.db.execute("""UPDATE spot_positions SET status='closed',closed_at=?,
                    proceeds_usd=?,realized_pnl_usd=?,exit=? WHERE id=? AND status='open'""",
                    (now, proceeds, proceeds - position["invested_usd"],
                     json.dumps(dict(quote=book, fill_price_usd=price, fee_usd=fee), allow_nan=False), position["id"])).rowcount
                if changed:
                    self.db.execute("UPDATE spot_cash SET usd=usd+? WHERE id=1", (proceeds,))
            if changed:
                self.record(now, {"decision": "paper_closed", "position_id": position["id"],
                                  "realized_pnl_usd": proceeds - position["invested_usd"]})

    def enter(self, candidate, report_id, now):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if self.db.execute("SELECT 1 FROM spot_positions WHERE asset=? AND (status='open' OR window_start=?)",
                               (candidate["asset"], candidate["window_start"])).fetchone():
                return "duplicate_or_already_long"
            if self.db.execute("SELECT 1 FROM spot_positions WHERE status='open' AND exit_due_at<=?", (now,)).fetchone():
                return "overdue_exit_blocks_entries"
            if self.db.execute("SELECT usd FROM spot_cash WHERE id=1").fetchone()[0] < candidate["stake_usd"]:
                return "insufficient_cash"
            payload = dict(candidate, regime_report_id=report_id)
            self.db.execute("""INSERT INTO spot_positions(asset,window_start,exit_due_at,status,opened_at,
                quantity,invested_usd,entry) VALUES(?,?,?,'open',?,?,?,?)""",
                (candidate["asset"], candidate["window_start"], candidate["exit_due_at"], now,
                 candidate["quantity"], candidate["stake_usd"], json.dumps(payload, sort_keys=True, allow_nan=False)))
            self.db.execute("UPDATE spot_cash SET usd=usd-? WHERE id=1", (candidate["stake_usd"],))
        return "paper_opened"

    def process(self, feed, now=None, regime_report=None):
        now = time.time() if now is None else number(now, "now")
        if (not isinstance(feed, dict) or not isinstance(feed.get("quotes", []), list)
                or any(not isinstance(item, dict) for item in feed.get("quotes", []))):
            raise ValueError("feed must contain a quote object array")
        books = {}
        rejected_books = set()
        for item in feed.get("quotes", []):
            try:
                book = quote(item, self.config, now)
                prior = books.get(book["asset"])
                if prior is None or book["quoted_at"] > prior["quoted_at"]:
                    books[book["asset"]] = book
                elif book["quoted_at"] == prior["quoted_at"] and book != prior:
                    raise ValueError("conflicting quotes at the same timestamp")
            except (ValueError, TypeError, KeyError) as error:
                if isinstance(item.get("asset"), str):
                    rejected_books.add(item["asset"])
                self.record(now, {"decision": "quote_rejected", "reason": str(error)})
        for asset in rejected_books:
            books.pop(asset, None)
        self.close_due(books, now)
        try:
            validate_report(regime_report, self.config, now)
            if regime_report.get("strategy") != STRATEGY:
                raise ValueError("Gemini must explicitly review the Coinbase spot strategy")
            if regime_report.get("strategy_config_hash") != config_hash(self.config):
                raise ValueError("Gemini evaluated different spot costs, sizing, model, or rules")
            payload = json.dumps(regime_report, sort_keys=True, allow_nan=False)
            with self.db:
                prior = self.db.execute("SELECT payload FROM spot_reports WHERE report_id=?", (regime_report["report_id"],)).fetchone()
                if prior and prior[0] != payload:
                    raise ValueError("report ID reused with changed contents")
                self.db.execute("INSERT OR IGNORE INTO spot_reports VALUES(?,?)", (regime_report["report_id"], payload))
        except (ValueError, KeyError, TypeError) as error:
            self.record(now, {"decision": "regime_blocked", "reason": str(error)})
            return
        candidates = {}
        rejected = set()
        forecasts = feed.get("forecasts", [])
        if not isinstance(forecasts, list):
            self.record(now, {"decision": "forecast_rejected", "reason": "forecasts must be an array"})
            return
        for item in forecasts:
            try:
                if not isinstance(item, dict):
                    raise ValueError("forecast must be an object")
                report_id = allow_asset(regime_report, item, self.config)
                candidate = plan(item, books[item["asset"]], self.config, now)
                asset = candidate["asset"]
                if asset in candidates and candidates[asset][0] != candidate:
                    rejected.add(asset)
                    raise ValueError("conflicting forecasts for the same asset")
                candidates[asset] = (candidate, report_id)
            except (ValueError, KeyError, TypeError) as error:
                self.record(now, {"decision": "forecast_rejected", "asset": item.get("asset") if isinstance(item, dict) else None,
                                  "reason": str(error)})
        for candidate, report_id in sorted(candidates.values(), key=lambda x: (-x[0]["expected_net_return"], x[0]["asset"])):
            if candidate["asset"] in rejected:
                continue
            decision = self.enter(candidate, report_id, now) if candidate["eligible"] else "below_net_return_threshold"
            self.record(now, {"decision": decision, "candidate": candidate, "regime_report_id": report_id})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "spot_config.json")
    parser.add_argument("--feed", type=Path, help="JSON containing quotes and optional forecasts")
    parser.add_argument("--print-config-hash", action="store_true")
    parser.add_argument("--forecasts", type=Path, help="optional separate JSON object containing forecasts")
    parser.add_argument("--regime-report", type=Path, default=ROOT / "reports/gemini_spot_latest.json")
    parser.add_argument("--database", type=Path, default=ROOT / "spot_paper.sqlite3")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.print_config_hash:
        print(config_hash(config))
        return
    if args.feed is None:
        parser.error("--feed is required unless --print-config-hash is used")
    runner = SpotPaperRunner(config, args.database)
    print("PAPER ONLY: Coinbase spot, long/cash, 15-minute timed exits; no live orders.")
    try:
        while True:
            # Forecast/report failures must never stop valid quotes from closing positions.
            try:
                feed = json.loads(args.feed.read_text())
                if not isinstance(feed, dict):
                    raise ValueError("feed must be an object")
            except (OSError, ValueError):
                if args.once:
                    raise
                print("Quote feed unavailable; no fills this cycle.")
                time.sleep(2)
                continue
            if not isinstance(feed.get("forecasts", []), list):
                feed["forecasts"] = []
            else:
                feed.setdefault("forecasts", [])
            if args.forecasts:
                try:
                    forecasts = json.loads(args.forecasts.read_text())["forecasts"]
                    if not isinstance(forecasts, list):
                        raise ValueError("forecasts must be an array")
                    feed["forecasts"].extend(forecasts)
                except (OSError, ValueError, KeyError, TypeError):
                    feed["forecasts"] = []
            try:
                report = json.loads(args.regime_report.read_text())
            except (OSError, ValueError):
                report = None
            runner.process(feed, regime_report=report)
            if args.once:
                break
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        runner.close()


if __name__ == "__main__":
    main()
