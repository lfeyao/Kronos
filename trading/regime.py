"""Validate nightly Gemini reports as data; never apply checkpoint changes."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("America/Los_Angeles")


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("report timestamps must be ISO 8601 strings")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("report timestamps must include a timezone")
    return parsed.timestamp()


def text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"report {field} must be a nonempty string")
    return value


def validate_report(report, config, now):
    if not isinstance(report, dict):
        raise ValueError("nightly report is missing or invalid")
    if type(report["schema_version"]) is not int or report["schema_version"] != 1 or report["source"] != "gemini":
        raise ValueError("unsupported nightly report schema/source")
    text(report["report_id"], "report_id")
    if report["model_version"] != config["model_version"]:
        raise ValueError("nightly report evaluated a different model version")
    if report["horizon_seconds"] != 900:
        raise ValueError("nightly report evaluated a different forecast horizon")
    generated = timestamp(report["generated_at"])
    expires = timestamp(report["expires_at"])
    max_age = float(config["regime_report_max_age_hours"]) * 3600
    if not generated <= now < expires or now - generated > max_age or expires - generated > max_age:
        raise ValueError("nightly report is expired, future-dated, or too old")
    trading_day = datetime.fromtimestamp(now, ZONE).date()
    if date.fromisoformat(report["trading_date"]) != trading_day:
        raise ValueError("nightly report is not for today's Pacific trading date")
    if date.fromisoformat(report["analyzed_date"]) != trading_day - timedelta(days=1):
        raise ValueError("nightly report must review the prior Pacific calendar day")
    if datetime.fromtimestamp(generated, ZONE).date() != trading_day:
        raise ValueError("nightly report must be generated on its trading date")
    if not isinstance(report["assets"], dict):
        raise ValueError("nightly report assets must be an object")
    update = report["weight_update"]
    if not isinstance(update, dict) or type(update["recommended"]) is not bool:
        raise ValueError("weight_update.recommended must be true or false")
    text(update["reason"], "weight_update.reason")
    return report


def allow_asset(report, signal, config):
    if signal.get("model_version") != config["model_version"]:
        raise ValueError("signal is missing the reviewed model version or uses different weights")
    decision = report["assets"].get(signal["asset"])
    if not isinstance(decision, dict) or type(decision.get("trade_allowed")) is not bool:
        raise ValueError("nightly report has no valid decision for this asset")
    text(decision.get("regime"), "asset regime")
    reason = text(decision.get("reason"), "asset reason")
    if decision["trade_allowed"] is not True:
        raise ValueError(f"Gemini paused {signal['asset']}: {reason}")
    return report["report_id"]
