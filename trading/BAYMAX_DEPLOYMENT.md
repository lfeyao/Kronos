# Baymax deployment

## Coinbase spot update — 2026-10-24

The active development target is [Coinbase spot paper research](SPOT_PAPER.md).
The spot engine, config, public quote collector, tests, and report contract are
staged in the guest. No daemon is started. BTC/ETH public books were fetched
successfully after refreshing the existing Singapore PIA registration when
egress health checks failed. Keep guest clients behind the existing firewall.
Real terminal-price forecast generation and Gemini spot report delivery remain
pending; neither account activity nor a live order endpoint is used.

Target: Baymax Mac mini, Tailscale IP `100.97.243.70`, SSH user `baymax`.
Reach it while strictly checking its existing trusted SSH hostname key:

```sh
ssh -o HostName=100.97.243.70 \
  -o HostKeyAlias=baymaxs-mac-mini \
  -o StrictHostKeyChecking=yes baymax
```

## Verified host state — 2026-10-23

- Apple Silicon, 8 CPU cores, 8 GiB physical RAM, macOS 27.0.1.
- Approximately 86 GiB available disk space at inspection.
- Host sleep disabled; automatic restart after power failure disabled.
- Homebrew, Lima 2.2.1, Colima, and Docker already installed.
- Existing Colima profiles after authorized changes: `default` running,
  4 CPUs / 1.5 GiB RAM / 100 GiB virtual disk; `sandbox` stopped, retaining
  its 2 GiB configuration and 20 GiB virtual disk for recovery.
- `default` previously had 8 GiB configured, then 3 GiB. The user requested
  1.5 GiB on 2026-10-23. Its six containers restarted after resizing; none were
  deleted. Before the latest resize their combined usage was about 930 MiB;
  1.5 GiB leaves limited headroom for Linux, imports, and browser activity.
- No `~/DEV-ENVIRONMENT.md` or `~/AGENTS.md` was found initially. A new host
  `~/DEV-ENVIRONMENT.md` inventory was created for this deployment.
- Existing Hermes emergency controls documented in
  `~/Documents/Baymax-KILLSWITCH.md` and `~/.hermes/security/KILLSWITCH.md`.

The user authorized resizing/stopping both existing profiles and accepted that
the trading VM will share the `baymax` account with Hermes. This is network
isolation, not a security boundary against processes running as that host user.
The separate `kronos-trading` Lima VM is running: Ubuntu 24.04 ARM64,
2 vCPUs, 2 GiB RAM, 20 GiB disk. Sources are staged inside it at
`/home/baymax.guest/kronos`; all 44 offline tests passed using its Python 3.12.3.
PIA WireGuard is connected through Singapore. No runner daemon or exchange
credentials have been deployed.

WireGuard tools are installed. The guest's `kronos-egress.service` loads
`/etc/kronos-egress.nft` before networking. Its default-deny output policy allows
loopback, established inbound SSH replies, DHCP, IPv4 over `pia`, and marked
WireGuard UDP packets to the registered Singapore endpoint. Kernel WireGuard
packets use fwmark 51820; matching their userspace UID does not reliably work.
Temporary root-only TLS access to PIA authentication endpoints was removed
after configuration. Host DNS forwarding is disabled in Lima.

Verified: HTTPS, a public Coinbase WebSocket upgrade, Singapore public egress,
and failure of forced physical-interface HTTPS. Stopping PIA blocked HTTPS,
uncached DNS queries, and IPv6 HTTPS; restarting it restored Singapore egress.
These checks do not establish complete anonymity or venue trading eligibility.
No exchange account or order endpoint was used for these tests.
The guest was then stopped and started: both firewall and WireGuard services
returned active, and an unprivileged public connectivity check again reported
Singapore with working HTTPS and WebSockets.

The VM is not configured to autostart after a host reboot or user logout.
No model inference process, report transfer, venue feed adapters, or runner
daemon has been started.

## Enter PIA credentials locally

On your own terminal, connect to Baymax and run the guest's hidden prompt:

```sh
ssh -t -o HostKeyAlias=baymaxs-mac-mini \
  -o StrictHostKeyChecking=yes baymax@100.97.243.70
/opt/homebrew/bin/limactl shell --workdir /home/baymax.guest/kronos \
  kronos-trading python3 -m trading.save_pia_credentials
```

Use the PIA VPN login username and password, not a wallet key or exchange key.
Both inputs are hidden. The prompt creates `~/.config/kronos/pia.json` in the
guest with permissions 600 inside a private directory. It preserves an existing
file and makes no network request. The file is plaintext protected by Unix
permissions, and remains accessible to the shared host account. Do not paste
its contents into chat. Saving it does not connect PIA; connection setup and
verification are now complete for the saved login. Do not run the prompt again
to replace credentials: it deliberately preserves the existing file.

The generated WireGuard private key is stored in `/etc/wireguard/pia.conf`
(root-owned, mode 600). The PIA login remains in its original private guest file.
Tokens and private keys are never printed by the configuration script. Native
`wg-quick@pia.service` starts after the guest's egress firewall on guest boot.
PIA peer registration may eventually require renewal; no automated credential
renewal or always-on VPN monitor has been deployed.

Read-only public connectivity check from the guest project directory:

```sh
python3 -m trading.check_pia
```

The disruptive test below temporarily stops PIA and must only run when no runner
workload depends on the connection. It restores the tunnel in a finally block:

```sh
sudo python3 -m trading.check_pia --test-disconnect
```

## Selected architecture

Dedicated Linux VM on Baymax -> PIA tunnel -> venue data/API connections.
The MacBook remains an administration/development machine. Gemini supplies its
existing daily report; report delivery still needs wiring. Initial deployment
must remain paper/read-only. The user operates any future live execution system.

Deployed baseline: Ubuntu 24.04 ARM64, 2 vCPUs,
2 GiB RAM, 20 GiB virtual disk, Apple Virtualization framework. This sizes the
execution/data runner only; model inference or training needs a separate memory
assessment. Avoid host-home mounts and unsolicited guest port exposure.

The initial provisioning command, recorded for reference (do not recreate the
existing VM):

```sh
/opt/homebrew/bin/limactl start --yes --name=kronos-trading \
  --vm-type=vz --cpus=2 --memory=2 --disk=20 \
  --mount-none --containerd=none template:ubuntu-24.04
```

## Remaining deployment work

1. Completed: stop empty `sandbox`, resize `default` to 1.5 GiB, restart its media
   stack and Hermes browser containers. Verify service health after restart.
2. Completed: create the guest without host mounts or automatic port forwarding,
   stage runner sources, pass 44 tests, install WireGuard tools, and apply the
   default-deny egress policy. Host DNS forwarding is disabled as well.
3. Completed: configure PIA Singapore, keep credentials outside Git, verify
   HTTPS/WebSockets, VPN-only routing, disconnect blocking, and reconnection.
   Long-lived application-session recovery remains to be tested with actual
   venue adapters. No model/venue runner service exists yet.
4. Copy only the required runner sources/configuration, without host credentials
   or unrelated workspaces. Deliver Gemini JSON atomically and validate freshness.
5. Run offline checks and a supervised paper/read-only trial. Complete venue
   integration checks separately; public account queries do not prove trading
   authorization or compatible Up/Down markets.
6. Add service/VM supervision and test restart behavior. Integrate an explicit
   runner stop with the host's emergency runbook: the existing Hermes kill
   switch must not be assumed to stop a separately supervised VM.
7. Review power-failure restart behavior with the user before changing host
   settings. Verify recovery rather than equating disabled sleep with uptime.

To stop a future VM without deleting its state:

```sh
/opt/homebrew/bin/limactl stop kronos-trading
```

No automatic scheduling or live trading is enabled by this document.
