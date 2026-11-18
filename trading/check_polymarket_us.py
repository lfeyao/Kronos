"""Verify saved Polymarket US credentials with GET /v1/account/balances only.

Run: .venv/bin/python -m trading.check_polymarket_us
No order, transfer, cancellation, or payment endpoints are called.
"""
import json
import sys

from trading.credentials import load_polymarket_us_credentials


def check_connection():
    from polymarket_us import PolymarketUS

    client = PolymarketUS(**load_polymarket_us_credentials(), timeout=15, max_retries=0)
    try:
        balances = client.account.balances()
    finally:
        client.close()
    if not isinstance(balances, dict) or not isinstance(balances.get("balances"), list):
        raise ValueError("Unexpected balance response")
    result = {"authenticated": True, "read_only": True, "orders_submitted": 0}
    # Only documented balance fields may be displayed; never dump API responses,
    # request headers, credential dictionaries, or exception messages.
    result["balances"] = []
    for balance in balances["balances"]:
        if not isinstance(balance, dict):
            raise ValueError("Unexpected balance record")
        summary = {}
        for field in ("currency", "currentBalance", "buyingPower"):
            value = balance.get(field)
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                summary[field] = value
        result["balances"].append(summary)
    return result


def main():
    try:
        print(json.dumps(check_connection(), allow_nan=False))
    except Exception as error:
        result = {"authenticated": False, "error_type": type(error).__name__, "orders_submitted": 0}
        status = getattr(error, "status_code", None)
        if isinstance(status, int):
            result["http_status"] = status
        print(json.dumps(result))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
