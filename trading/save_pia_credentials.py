"""Prompt locally for PIA login credentials; no network requests or VPN changes.

Run inside the trading VM: python3 -m trading.save_pia_credentials
"""
import getpass
import json
import os
from pathlib import Path
import stat
import sys


def save_credentials(username, password, directory=None):
    if not username or not password or any(c in username + password for c in "\r\n\0"):
        raise ValueError("PIA username and password must be nonempty single-line values")
    directory = Path(directory) if directory is not None else Path.home() / ".config" / "kronos"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("Credentials directory must be user-owned and private (700)")
        # Exclusive creation preserves existing credentials and rejects symlinks.
        output = os.open("pia.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=descriptor)
        with os.fdopen(output, "w") as stream:
            json.dump({"username": username, "password": password}, stream)
            stream.write("\n")
    finally:
        os.close(descriptor)
    return directory / "pia.json"


def main():
    if not sys.stdin.isatty():
        print("Run in an interactive terminal; do not pass credentials on the command line.")
        return 1
    try:
        username = getpass.getpass("PIA username (hidden): ").strip()
        password = getpass.getpass("PIA password (hidden): ")
        location = save_credentials(username, password)
    except Exception as error:
        print(f"Credentials were not saved: {type(error).__name__}")
        return 1
    print(f"Saved locally to {location} with permissions 600. VPN is not connected yet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
