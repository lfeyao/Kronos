"""Load local Polymarket US and Hyperliquid credentials without logging values."""
import json
import os
from pathlib import Path
import re
import stat


POLYMARKET_US_CREDENTIALS = (
    Path.home() / "Library" / "Application Support" / "Kronos" / "polymarket-us.json"
)
HYPERLIQUID_CREDENTIALS = (
    Path.home() / ".config" / "kronos" / "hyperliquid.json"
)
HEX_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
HEX_PRIVATE_KEY_RE = re.compile(r"^(?:0x)?[0-9a-fA-F]{64}$")


def _read_private_json(path):
    path = Path(path)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor) as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError("Credentials file must be user-owned with permissions 600")
            values = json.load(stream)
    except (OSError, json.JSONDecodeError):
        raise ValueError("Credentials file is unavailable or is not valid JSON") from None
    if not isinstance(values, dict):
        raise ValueError("Credentials file must contain a JSON object")
    return values


def load_polymarket_us_credentials(path=POLYMARKET_US_CREDENTIALS):
    """Return SDK arguments from a user-owned private JSON file.

    This does not authenticate, submit orders, or modify the process environment.
    """
    values = _read_private_json(path)
    if any(
        not isinstance(values.get(key), str) or not values[key].strip()
        for key in ("key_id", "secret_key")
    ):
        raise ValueError("Fill in key_id and secret_key in the local credentials file")
    return {key: values[key].strip() for key in ("key_id", "secret_key")}


def load_hyperliquid_credentials(path=HYPERLIQUID_CREDENTIALS):
    """Load separated main account address, agent address, and agent private key.

    Never prints private keys or modifies process environment.
    """
    values = _read_private_json(path)
    for key in ("account_address", "agent_address", "agent_private_key", "network"):
        if not isinstance(values.get(key), str) or not values[key].strip():
            raise ValueError(f"Missing or empty {key} in Hyperliquid credentials file")
    account = values["account_address"].strip()
    agent = values["agent_address"].strip()
    private_key = values["agent_private_key"].strip()
    network = values["network"].strip().lower()
    if not HEX_ADDRESS_RE.fullmatch(account):
        raise ValueError("account_address must be a 42-character 0x hex address")
    if not HEX_ADDRESS_RE.fullmatch(agent):
        raise ValueError("agent_address must be a 42-character 0x hex address")
    if account.lower() == agent.lower():
        raise ValueError("account_address and agent_address must be separate addresses")
    if not HEX_PRIVATE_KEY_RE.fullmatch(private_key):
        raise ValueError("agent_private_key must be a 32-byte hex private key")
    if network not in ("mainnet", "testnet"):
        raise ValueError("network must be 'mainnet' or 'testnet'")
    normalized_key = private_key if private_key.startswith("0x") else f"0x{private_key}"
    return {
        "account_address": account,
        "agent_address": agent,
        "agent_private_key": normalized_key,
        "network": network,
        "agent_name": str(values.get("agent_name", "Kronos")).strip() or "Kronos",
    }
