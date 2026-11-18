"""Read public Hyperliquid account data, verify non-executing agent approval, and inspect HIP-4 outcomes.

No private keys are transmitted; no /exchange calls or orders are submitted.
"""
import argparse
import json
import re
import sys
import time
from urllib.request import Request, urlopen


ENDPOINTS = {
    "mainnet": "https://api.hyperliquid.xyz/info",
    "testnet": "https://api.hyperliquid-testnet.xyz/info",
}


def post_info(payload, network="mainnet", timeout=15):
    endpoint = ENDPOINTS[network]
    request = Request(
        endpoint,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def verify_agent_approval(account_address, agent_address, network="mainnet", expected_name="Kronos", now_ms=None):
    """Verify via /info whether agent_address is an approved non-expired API wallet for account_address."""
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}", account_address):
        raise ValueError("Invalid main account 0x address")
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}", agent_address):
        raise ValueError("Invalid agent 0x address")
    if account_address.lower() == agent_address.lower():
        raise ValueError("Account address and agent address must be distinct")

    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    role_resp = post_info({"type": "userRole", "user": agent_address}, network=network)
    extra_agents = post_info({"type": "extraAgents", "user": account_address}, network=network)

    role_matches_master = (
        isinstance(role_resp, dict)
        and role_resp.get("role") == "agent"
        and isinstance(role_resp.get("data"), dict)
        and str(role_resp["data"].get("user", "")).lower() == account_address.lower()
    )

    matched_entry = None
    if isinstance(extra_agents, list):
        for entry in extra_agents:
            if isinstance(entry, dict) and str(entry.get("address", "")).lower() == agent_address.lower():
                matched_entry = entry
                break

    valid_until = matched_entry.get("validUntil") if matched_entry else None
    not_expired = valid_until is None or int(valid_until) > now_ms
    agent_name = matched_entry.get("name") if matched_entry else None
    name_matches = expected_name is None or agent_name == expected_name

    approved = bool(role_matches_master and matched_entry is not None and not_expired)
    return {
        "network": network,
        "account": account_address[:6] + "..." + account_address[-4:],
        "agent": agent_address[:6] + "..." + agent_address[-4:],
        "agent_role_verified": role_matches_master,
        "listed_in_extra_agents": matched_entry is not None,
        "agent_name": agent_name,
        "expected_name_matches": bool(name_matches),
        "valid_until_ms": valid_until,
        "not_expired": bool(not_expired),
        "trading_authorization_verified": approved,
        "orders_submitted": 0,
    }


def account_summary(address, network="mainnet", agent_address=None):
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}", address):
        raise ValueError("Use the account's public 0x address (42 characters)")

    orders = post_info({"type": "openOrders", "user": address}, network=network)
    spot = post_info({"type": "spotClearinghouseState", "user": address}, network=network)
    if not isinstance(orders, list) or not isinstance(spot, dict):
        raise ValueError("Unexpected account response")
    balances = spot.get("balances")
    if not isinstance(balances, list) or any(not isinstance(row, dict) for row in balances):
        raise ValueError("Unexpected balance response")

    summary = {
        "network": network,
        "account": address[:6] + "..." + address[-4:],
        "public_data_only": True,
        "trading_authorization_verified": False,
        "orders_submitted": 0,
        "open_order_count": len(orders),
        "spot_balances": [
            {key: row[key] for key in ("coin", "total", "hold") if key in row}
            for row in balances
        ],
    }
    if agent_address:
        approval = verify_agent_approval(address, agent_address, network=network)
        summary["agent_verification"] = approval
        summary["trading_authorization_verified"] = approval["trading_authorization_verified"]
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", help="Public main account 0x address")
    parser.add_argument("--agent-address", help="Optional dedicated Kronos agent public 0x address to verify")
    parser.add_argument("--from-saved", action="store_true", help="Load addresses from ~/.config/kronos/hyperliquid.json")
    parser.add_argument("--network", choices=tuple(ENDPOINTS), default="mainnet")
    args = parser.parse_args()
    try:
        address = args.address
        agent_address = args.agent_address
        network = args.network
        if args.from_saved:
            from trading.credentials import load_hyperliquid_credentials
            creds = load_hyperliquid_credentials()
            address = creds["account_address"]
            agent_address = creds["agent_address"]
            network = creds["network"]
        if not address:
            raise ValueError("Provide --address or --from-saved")
        print(json.dumps(account_summary(address, network, agent_address=agent_address), allow_nan=False))
    except Exception as error:
        print(json.dumps({"error_type": type(error).__name__, "orders_submitted": 0}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
