"""Check guest VPN egress. --test-disconnect briefly stops/restarts PIA.

No credentials or exchange accounts are accessed. Run only inside the guest.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
from urllib.request import ProxyHandler, build_opener


def command(arguments):
    return subprocess.run(arguments, capture_output=True, text=True, timeout=20)


def https_probe(*extra):
    return command(["curl", "--noproxy", "*", "-4", "-fsS", "--connect-timeout", "3",
                    "--max-time", "5", *extra, "-o", "/dev/null", "https://1.1.1.1"]).returncode == 0


def egress():
    opener = build_opener(ProxyHandler({}))
    with opener.open("https://ipinfo.io/json", timeout=15) as response:
        value = json.load(response)
    return {key: value.get(key) for key in ("ip", "city", "country")}


def websocket():
    host = "ws-feed.exchange.coinbase.com"
    nonce = base64.b64encode(os.urandom(16)).decode()
    with socket.create_connection((host, 443), timeout=10) as raw:
        with ssl.create_default_context().wrap_socket(raw, server_hostname=host) as stream:
            stream.sendall((f"GET / HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n"
                            f"Connection: Upgrade\r\nSec-WebSocket-Key: {nonce}\r\n"
                            "Sec-WebSocket-Version: 13\r\n\r\n").encode())
            response = b""
            while b"\r\n\r\n" not in response and len(response) < 16384:
                part = stream.recv(4096)
                if not part:
                    break
                response += part
    expected = base64.b64encode(hashlib.sha1((nonce + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
    headers = response.split(b"\r\n\r\n", 1)[0].split(b"\r\n")
    values = {line.split(b":", 1)[0].lower(): line.split(b":", 1)[1].strip()
              for line in headers[1:] if b":" in line}
    return b" 101 " in headers[0] and values.get(b"sec-websocket-accept") == expected


def check(disconnect=False):
    result = {"egress": egress(), "https": https_probe(), "websocket_upgrade": websocket(), "orders_submitted": 0}
    result["singapore_egress"] = result["egress"].get("country") == "SG"
    if not disconnect:
        return result
    if os.geteuid() != 0:
        raise PermissionError("Disconnect tests require guest root")
    # Keep the packet mark stable across future guest boots.
    path = Path("/etc/wireguard/pia.conf")
    config = path.read_text()
    if "FwMark = " not in config:
        path.write_text(config.replace("MTU = ", "FwMark = 51820\nMTU = ", 1))
    result["forced_physical_interface_blocked"] = not https_probe("--interface", "eth0")
    if command(["systemctl", "stop", "wg-quick@pia.service"]).returncode:
        raise RuntimeError("Could not stop test tunnel")
    try:
        result["https_blocked_without_vpn"] = not https_probe()
        command(["resolvectl", "flush-caches"])
        try:
            query = subprocess.run(["resolvectl", "query", "--cache=no", "example.com"],
                                   capture_output=True, timeout=6)
            result["dns_unavailable_without_vpn"] = query.returncode != 0
        except subprocess.TimeoutExpired:
            result["dns_unavailable_without_vpn"] = True
        probe = command(["curl", "--noproxy", "*", "-6", "-fsS", "--connect-timeout", "3",
                         "--max-time", "5", "-o", "/dev/null", "https://[2606:4700:4700::1111]"])
        result["ipv6_unavailable_without_vpn"] = probe.returncode != 0
    finally:
        if command(["systemctl", "start", "wg-quick@pia.service"]).returncode:
            raise RuntimeError("Tunnel restoration failed; egress remains blocked")
    result["restored_egress"] = egress()
    result["singapore_egress_restored"] = result["restored_egress"].get("country") == "SG"
    result["https_restored"] = https_probe()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-disconnect", action="store_true")
    args = parser.parse_args()
    try:
        result = check(args.test_disconnect)
        print(json.dumps(result))
        checks = [value for key, value in result.items() if isinstance(value, bool)]
        return 0 if checks and all(checks) else 1
    except Exception as error:
        print(json.dumps({"check_failed": True, "error_type": type(error).__name__, "orders_submitted": 0}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
