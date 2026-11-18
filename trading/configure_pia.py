"""Configure native PIA WireGuard in the dedicated Linux guest.

Run as root in that guest only. Secrets remain in memory or root-private files.
Public bootstrap metadata and the PIA API CA certificate are supplied separately.
"""
import argparse
import base64
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import stat
import subprocess
import tempfile
from urllib.parse import urlencode


def run(arguments, *, data=None):
    result = subprocess.run(arguments, input=data, text=True, capture_output=True, timeout=45)
    if result.returncode:
        raise RuntimeError("Local VPN command failed")
    return result.stdout.strip()


def ipv4(value):
    return str(ipaddress.IPv4Address(value))


def atomic_write(path, contents, mode=0o600):
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".kronos-")
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def private_json(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor) as stream:
        info = os.fstat(stream.fileno())
        caller_uid = int(os.environ.get("SUDO_UID", os.getuid()))
        if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077
                or info.st_uid not in (0, caller_uid)):
            raise ValueError("Credentials file must be private and owned by caller or root")
        values = json.load(stream)
    if not isinstance(values, dict) or any(
        not isinstance(values.get(key), str) or not values[key]
        for key in ("username", "password")
    ):
        raise ValueError("Missing PIA login")
    return values


class PinnedHTTPS(http.client.HTTPSConnection):
    """TLS validates the hostname while the TCP connection uses a known IP."""
    def __init__(self, hostname, address, port=443, *, context=None):
        super().__init__(hostname, port, timeout=20, context=context)
        self.address = ipv4(address)

    def connect(self):
        raw = socket.create_connection((self.address, self.port), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def request_json(hostname, address, path, *, port=443, context=None, body=None, headers=None):
    connection = PinnedHTTPS(hostname, address, port, context=context)
    try:
        connection.request("POST" if body is not None else "GET", path, body=body, headers=headers or {})
        response = connection.getresponse()
        payload = response.read(1024 * 1024)
        if response.status != 200:
            raise RuntimeError("PIA request was unsuccessful")
        return json.loads(payload)
    finally:
        connection.close()


def validate_bootstrap(config):
    hostname = config["server_hostname"]
    if not re.fullmatch(r"[A-Za-z0-9.-]+", hostname):
        raise ValueError("Invalid server hostname")
    address = ipv4(config["server_ip"])
    addresses = [ipv4(item) for item in config["auth_ips"]]
    if not addresses or any(not ipaddress.ip_address(item).is_global for item in [address, *addresses]):
        raise ValueError("Bootstrap requires public server addresses")
    return hostname, address, addresses


def configure(args):
    stage = "preflight"
    bootstrap_open = False
    try:
        if os.geteuid() != 0:
            raise PermissionError("Run in the guest as root")
        config = json.loads(Path(args.bootstrap).read_text())
        hostname, address, auth_addresses = validate_bootstrap(config)
        credentials = private_json(args.credentials)
        run(["systemctl", "is-active", "kronos-egress.service"])
        # Remove any expired temporary bootstrap rule left by an interrupted run.
        run(["nft", "-f", "/etc/kronos-egress.nft"])

        stage = "temporary_authentication_route"
        # This short-lived set permits only root TLS to PIA. No DNS bypass.
        rule = """add set inet kronos_egress pia_bootstrap { type ipv4_addr . inet_service; flags timeout; timeout 120s; }
insert rule inet kronos_egress output meta skuid 0 ip daddr . tcp dport @pia_bootstrap accept
"""
        run(["nft", "-f", "-"], data=rule)
        bootstrap_open = True
        pairs = [f"{item} . 443" for item in auth_addresses] + [f"{address} . 1337"]
        run(["nft", "-f", "-"], data="add element inet kronos_egress pia_bootstrap { " + ", ".join(pairs) + " }\n")

        stage = "pia_authentication"
        boundary = "KronosPIAAuthBoundary"
        body = "".join(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{credentials[name]}\r\n'
            for name in ("username", "password")
        ) + f"--{boundary}--\r\n"
        token = None
        for auth_address in auth_addresses:
            try:
                response = request_json(
                    "www.privateinternetaccess.com", auth_address, "/api/client/v2/token",
                    body=body.encode(), headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                )
                value = response.get("token")
                if isinstance(value, str) and value and value != "null":
                    token = value
                    break
            except (OSError, RuntimeError, ValueError):
                continue
        if token is None:
            raise RuntimeError("PIA authentication failed")
        del credentials, body

        stage = "wireguard_registration"
        private_key = run(["wg", "genkey"])
        public_key = run(["wg", "pubkey"], data=private_key + "\n")
        response = request_json(
            hostname, address, "/addKey?" + urlencode({"pt": token, "pubkey": public_key}),
            port=1337, context=ssl.create_default_context(cafile=args.ca),
        )
        del token
        if response.get("status") != "OK":
            raise RuntimeError("WireGuard registration failed")
        server_key = response["server_key"]
        if len(base64.b64decode(server_key, validate=True)) != 32:
            raise ValueError("Invalid WireGuard server key")
        peer_ip = ipv4(response["peer_ip"])
        dns = ipv4(response["dns_servers"][0])
        port = int(response["server_port"])
        if not 1 <= port <= 65535:
            raise ValueError("Invalid WireGuard port")

        stage = "persistent_configuration"
        directory = Path("/etc/wireguard")
        directory.mkdir(mode=0o700, exist_ok=True)
        directory.chmod(0o700)
        atomic_write(directory / "pia.conf", f"""[Interface]
Address = {peer_ip}/32
PrivateKey = {private_key}
FwMark = 51820
MTU = 1420
PostUp = resolvectl dns %i {dns}; resolvectl domain %i '~.'; resolvectl default-route %i yes
PostDown = resolvectl revert %i || true

[Peer]
PublicKey = {server_key}
AllowedIPs = 0.0.0.0/0
Endpoint = {address}:{port}
PersistentKeepalive = 25
""")
        del private_key
        policy = Path("/etc/kronos-egress.nft")
        text = policy.read_text()
        text, count = re.subn(
            r"(set pia_endpoints\s*\{\s*type ipv4_addr \. inet_service\s*)(?:elements\s*=\s*\{[^}]*\}\s*)?(\})",
            lambda match: match[1] + f"elements = {{ {address} . {port} }}\n    " + match[2],
            text, count=1,
        )
        if count != 1:
            raise ValueError("Unexpected firewall policy")
        run(["nft", "--check", "-f", "-"], data=text)
        atomic_write(policy, text, 0o644)
        run(["nft", "-f", str(policy)])
        bootstrap_open = False  # Reload removed the temporary bootstrap set/rule.
        dropin = Path("/etc/systemd/system/wg-quick@pia.service.d")
        dropin.mkdir(parents=True, exist_ok=True)
        atomic_write(dropin / "kronos.conf", "[Unit]\nRequires=kronos-egress.service\nAfter=kronos-egress.service network-online.target\n", 0o644)
        run(["systemctl", "daemon-reload"])
        stage = "tunnel_start"
        run(["systemctl", "enable", "wg-quick@pia.service"])
        run(["systemctl", "restart", "wg-quick@pia.service"])
        return {"configured": True, "region": config["region"], "interface": "pia", "orders_submitted": 0}
    except Exception as error:
        # Never emit raw HTTP responses, exception messages, keys, or subprocess logs.
        return {"configured": False, "stage": stage, "error_type": type(error).__name__, "orders_submitted": 0}
    finally:
        if bootstrap_open:
            try:
                run(["nft", "flush", "set", "inet", "kronos_egress", "pia_bootstrap"])
            except Exception:
                pass  # Individual elements also expire after 120 seconds.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", required=True)
    parser.add_argument("--bootstrap", required=True)
    parser.add_argument("--ca", required=True)
    result = configure(parser.parse_args())
    print(json.dumps(result))
    return 0 if result["configured"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
