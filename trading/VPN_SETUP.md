# Trading VM VPN on Baymax

The selected deployment is native PIA WireGuard inside Baymax's dedicated
`kronos-trading` Linux VM. The endpoint is **Singapore**, as requested by the
user. No PIA Mac app is needed on the MacBook or Baymax host.

The trading runner remains stopped. No exchange credentials or orders were
involved in VPN setup. The guest shares the baymax host account with Hermes,
which the user explicitly accepted; the VM does not protect secrets from that
host account.

## Active configuration

- Ubuntu 24.04 ARM64 guest, 2 vCPUs, 2 GiB RAM, 20 GiB disk.
- `wg-quick@pia.service` starts the tunnel after `kronos-egress.service`.
- Persistent nftables output policy blocks ordinary network fallback. Only
  loopback, inbound SSH replies, DHCP, the tunnel interface, and marked
  WireGuard packets to the selected PIA endpoint are allowed.
- WireGuard fwmark 51820 identifies its kernel-generated UDP packets.
- Guest DNS uses PIA DNS through the tunnel with the `~.` routing domain.
- Lima host DNS forwarding, host folder mounts, and automatic guest port
  forwarding are disabled.
- Temporary TLS exceptions used for PIA authentication were removed. PIA tokens
  and private keys are not printed by the setup tools.

## Verified behavior

Public egress reported Singapore. HTTPS and a public Coinbase WebSocket upgrade
worked. A forced physical-interface HTTPS connection failed. With PIA stopped,
HTTPS, an uncached DNS lookup, and IPv6 HTTPS were unavailable. Restarting PIA
restored Singapore egress. A guest stop/start cycle also restored both services
and passed HTTPS, WebSocket, and Singapore egress checks as the normal guest
user. These tests exercise the guest connection; they do
not verify the still-unimplemented venue adapters or model pipeline.

Host networking was not reconfigured. Separate remote MCP services do not
inherit this guest's VPN. Only clients running inside this VM use this routing.
A VPN does not establish account eligibility or permission to trade.

## Operations

See [BAYMAX_DEPLOYMENT.md](BAYMAX_DEPLOYMENT.md) for access, credential storage,
checks, and deployment state. From the guest project directory:

```sh
python3 -m trading.check_pia
```

To deliberately disconnect and restore PIA for a firewall test (only when no
runner workload needs the connection):

```sh
sudo python3 -m trading.check_pia --test-disconnect
```

The PIA login is in the guest's private `~/.config/kronos/pia.json` file. The
WireGuard private key is root-owned in `/etc/wireguard/pia.conf` with mode 600.
Never paste either file into chat or add it to Git. The files are protected by
Unix permissions, not an encrypted vault.

No automatic PIA registration renewal, host VM autostart, or production runner
supervisor has been configured. Verify host reboot recovery separately before
relying on unattended operation. Long-lived venue session recovery and any
future feed subprocesses must also be tested inside this VM.

Protocol reference: [PIA's official native connection documentation](https://github.com/pia-foss/manual-connections).
