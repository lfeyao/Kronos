"""Prompt locally for Hyperliquid account & Kronos API-wallet credentials.

No network requests or order submissions occur here.
Run interactively: python3 -m trading.save_hyperliquid_credentials
"""
import getpass
import json
import os
from pathlib import Path
import re
import stat
import sys


HEX_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
HEX_PRIVATE_KEY_RE = re.compile(r"^(?:0x)?[0-9a-fA-F]{64}$")


def save_hyperliquid_credentials(account_address, agent_address, agent_private_key,
                                 network="mainnet", agent_name="Kronos", directory=None):
    account_address = (account_address or "").strip()
    agent_address = (agent_address or "").strip()
    agent_private_key = (agent_private_key or "").strip()
    network = (network or "mainnet").strip().lower()
    agent_name = (agent_name or "Kronos").strip()

    if not HEX_ADDRESS_RE.fullmatch(account_address):
        raise ValueError("account_address must be a 42-character 0x hex address")
    if not HEX_ADDRESS_RE.fullmatch(agent_address):
        raise ValueError("agent_address must be a 42-character 0x hex address")
    if account_address.lower() == agent_address.lower():
        raise ValueError("account_address and agent_address must be distinct")
    if not HEX_PRIVATE_KEY_RE.fullmatch(agent_private_key):
        raise ValueError("agent_private_key must be a 64-hex-character (32-byte) key")
    if network not in ("mainnet", "testnet"):
        raise ValueError("network must be 'mainnet' or 'testnet'")

    normalized_key = agent_private_key if agent_private_key.startswith("0x") else f"0x{agent_private_key}"
    directory = Path(directory) if directory is not None else Path.home() / ".config" / "kronos"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("Credentials directory must be user-owned and private (700)")
        output = os.open("hyperliquid.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=descriptor)
        with os.fdopen(output, "w") as stream:
            json.dump({
                "account_address": account_address,
                "agent_address": agent_address,
                "agent_private_key": normalized_key,
                "agent_name": agent_name,
                "network": network,
            }, stream)
            stream.write("\n")
    finally:
        os.close(descriptor)
    return directory / "hyperliquid.json"


def main():
    if not sys.stdin.isatty():
        print("Run in an interactive terminal; do not pass credentials on the command line.")
        return 1
    try:
        account_address = input("Main account public 0x address: ").strip()
        agent_address = input("Dedicated 'Kronos' agent public 0x address: ").strip()
        agent_private_key = getpass.getpass("Dedicated 'Kronos' agent private key (hidden): ").strip()
        network = (input("Network [mainnet/testnet] (default: mainnet): ").strip() or "mainnet").lower()
        location = save_hyperliquid_credentials(
            account_address=account_address,
            agent_address=agent_address,
            agent_private_key=agent_private_key,
            network=network,
            agent_name="Kronos",
        )
    except Exception as error:
        print(f"Credentials were not saved: {type(error).__name__}")
        return 1
    print(f"Saved locally to {location} with permissions 600. No network request was made.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
