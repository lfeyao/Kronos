# Trading setup status

## Update — 2026-10-24: Coinbase spot first

The user selected Coinbase BTC/ETH spot paper research, long/cash, using positive
predicted net return after round-trip costs as the entry baseline. See
[SPOT_PAPER.md](SPOT_PAPER.md) and [GEMINI_SPOT_HANDOFF.md](GEMINI_SPOT_HANDOFF.md).
`spot_config.json` preserves $100 fee-inclusive entries and $1,000 shared paper
cash. The current account fee check returned a 0.009 taker rate on each side;
the paper config also records explicit, unvalidated spread/slippage buffers.

The separate `spot_runner.py` implements timed bid-side exits, persistence,
fee-aware P&L, duplicate prevention, and an exact configuration-hash Gemini gate.
`coinbase_spot_quotes.py` is a public GET-only quote collector. Sources are staged
on Baymax for testing; no collector or runner daemon is enabled. No real-money
activity was submitted.

Verification: 63 relevant tests passed locally, including 19 new spot/quote
tests. Those 19 also passed inside Baymax's guest. Both public spot books were
fetched successfully through Singapore PIA. A one-cycle paper smoke check with
missing forecasts/review opened zero positions and retained $1,000 simulated
cash. HTTPS, public WebSocket, and Singapore egress checks passed afterward.

Public Coinbase quote access initially failed despite an active VPN service.
Refreshing the existing Singapore PIA registration restored access to both
products. Firewall restrictions were retained. This demonstrates that an active
service alone is not proof of healthy egress; automated VPN renewal/monitoring
is still absent.

Actual terminal-price forecast generation, delivery of Gemini's new spot report,
historical quote capture, and continuous deployment remain unfinished. The
existing direction classifier is not a terminal-price forecast adapter. No
performance edge has been established. The earlier binary/Hyperliquid handoff
below is retained as historical context.

## Earlier baseline — 2026-10-23

Recorded from checks performed in this conversation on 2026-10-23 (Pacific).
This file is a recorded handoff, not a live health monitor.

## Implementation baseline

| Component | Recorded status |
| --- | --- |
| Repository | `/Users/daiyu/Documents/Code/Kronos` on the MacBook |
| Host | Baymax Mac mini, Tailscale `100.97.243.70`, SSH user `baymax` |
| Trading guest | Lima `kronos-trading`, Ubuntu 24.04 ARM64, 2 vCPUs, 2 GiB RAM, 20 GiB disk |
| Guest source directory | `/home/baymax.guest/kronos` |
| Media VM | Colima `default`, 1.5 GiB RAM; six containers recovered after resizing |
| Old sandbox | Colima `sandbox` stopped; disk retained |
| VPN | PIA WireGuard Singapore, verified within the trading guest |
| Host networking | Separate egress retained; host public country reported US |
| Runner | Paper engine implemented and staged; not running as a service |
| Offline checks | 44 runner/regime/venue/Polymarket adapter tests passed inside the guest |
| Hyperliquid | Public account checker and setup guide only; no signer or execution adapter |
| Compatible Hyperliquid contracts | BTC/ETH 15-minute Up/Down availability not verified |
| Model inference | Not running in the guest; feed generation still needs wiring |
| Gemini report | JSON specification exists; report delivery and ingestion in a running deployment remain unfinished |
| Live activity | No real-money orders or transfers submitted in this conversation |

## VPN evidence and limits

Verified public Singapore egress, HTTPS, a public WebSocket upgrade, and blocking
of a forced physical-interface HTTPS connection. Stopping PIA blocked HTTPS,
uncached DNS, and IPv6 HTTPS. Starting it restored Singapore egress. A guest
stop/start cycle automatically recovered the firewall and tunnel and passed
public connectivity checks as the normal guest user.

Host folder mounts, automatic guest port forwarding, and Lima host DNS forwarding
are disabled. Existing SSH management and host networking continued to work.
The guest remains accessible to processes running as the `baymax` host user;
this shared access was explicitly accepted.

PIA login credentials are in the guest's private `~/.config/kronos/pia.json`.
The root-owned WireGuard configuration is `/etc/wireguard/pia.conf`, mode 600.
Do not copy either file into this repository or a handoff report.

Guest VPN/firewall services are enabled. Host VM autostart after logout/reboot,
power-failure recovery, ongoing VPN monitoring, PIA registration renewal, and
actual venue-session recovery have not been implemented or fully verified.

## Next development work

Follow [HYPERLIQUID_HANDOFF.md](HYPERLIQUID_HANDOFF.md). Establish whether the
required contracts exist before implementing their adapter. Complete account
approval verification, local credential handling, model/quote/research feeds,
settlement reconciliation, paper/testnet trials, and deployment supervision.

The configuration still lists Coinbase, Robinhood, and Polymarket. It does not
list Hyperliquid, and the presence of a connected account or public quote adapter
does not establish compatible prediction-contract execution capability.

No live execution is enabled by these Markdown files.
