# Hyperliquid integration handoff

**Historical target:** on 2026-10-24 the user selected
[Coinbase spot paper research](SPOT_PAPER.md) first. This document preserves
the earlier Hyperliquid prediction-market specification; it is not the active
spot implementation plan.

This document records the requirements and remaining development work for the
Kronos runner. It is a software integration and testing specification. Initial
validation uses paper trading or testnet; no live-order command is included.

## Current state

See [TRADING_STATUS.md](TRADING_STATUS.md) for the implementation baseline and
[BAYMAX_DEPLOYMENT.md](BAYMAX_DEPLOYMENT.md) for deployment details.

The Hyperliquid adapter, signer, credential loader, and execution integration
have not been implemented. A screenshot showed an authorized API wallet named
`app.hyperliquid.xyz`; it did not establish a dedicated Kronos signer, possession
of its private key, the main account address, or approval on the intended network.
No Hyperliquid account check or order submission has been performed.

## Strategy requirements

| Setting | Requirement |
| --- | --- |
| Assets | BTC and ETH |
| Instruments | Binary Up/Down prediction contracts only |
| Horizon | 900 seconds, with exact contract boundaries verified |
| Normal stake | $100 per trade |
| Initial capital assumption | $1,000 per venue; actual funding unverified |
| Minimum expected ROI | Strictly greater than 0.50 after costs |
| Signal freshness | At most 90 seconds |
| Quote freshness | At most 10 seconds |
| Research gate | Valid, current Gemini report permitting the asset/regime |
| Model identity | Shared forecast ID and model/checkpoint version across venue checks |

The earlier $5 BTC five-minute request was a separate one-off test request; it
did not change the configured strategy. Do not silently reduce the ROI threshold
or stake to manufacture eligible signals. Additional assets require a separate
decision; Gemini's expansion research does not change the asset allowlist.

## 1. Establish whether the required contracts exist

Use current official Hyperliquid documentation and public metadata. HIP-4
documentation alone does not prove that matching live or testnet contracts are
listed. If they are unavailable, return an explicit unsupported/unavailable
result. Do not substitute BTC/ETH spot or perpetual positions.

For each candidate contract, record:

- Network, outcome ID, side/token identifiers, and settlement status.
- Exact start/end times in UTC and the meaning of Up and Down.
- Reference prices, price feed, observation/averaging rules, and tie handling.
- Payout and collateral denomination, fees, tick size, minimum quantity, and
  trading/settlement cutoffs.
- Executable depth for the full configured stake, including slippage and fees.
- Public source and observation time for each relevant rule.

Across venues, treat contracts as equivalent only when their boundaries and
resolution rules match. Cheapest all-in cost is the selection rule within an
equivalent group. Different settlement definitions need their own calibrated
outcome probabilities and cannot be compared using price alone.

## 2. Account and credential integration

Keep the main account public address separate from the agent public address.
Read-only account queries use the actual account address. An empty response is
not proof of ownership, funding, or trading permissions.

Use a dedicated authorized API wallet named `Kronos`. Have the account owner
approve it and retain control of the main wallet. Add a local hidden-input
credential prompt and loader in the guest; they are not implemented yet.
Credentials belong outside Git and reports in an owner-only directory/file
(700/600). Never print private keys, request signatures, authorization headers,
raw authenticated responses, or raw exception messages containing requests.
Do not reuse the Polymarket US credential file or PIA login file.

Verify network, derived agent address, approval, expiry, and supported permissions
using documented non-executing checks. Mainnet/testnet are separate. Do not use
a real-money order as an authentication test.

The shared `baymax` host account can access the guest and its credentials,
including through Hermes; the user explicitly accepted that shared access.

## 3. Forecast, research, and quote adapters

Integrate with the existing feed boundary in `runner.py`; do not replace the
paper accounting engine with an untested execution loop.

- Use one forecast identity/checkpoint and terminal expected USD price for the
  same asset/window across venue comparisons.
- Supply a calibrated probability for each contract side. A terminal mean price
  alone does not determine the probability of finishing Up or Down.
- For a $1-equivalent payout, expected ROI is `p / all_in_unit_cost - 1`. For a
  different payout denomination, normalize payout and cost consistently before
  calculating ROI. Reject unknown fees or conversion assumptions.
- Preserve timestamps and reject stale/future-dated forecasts or quotes.
- Require all configured venues to return a fresh quote or explicit unavailable
  check before selection. A missing feed is not an unavailable check.
- Choose the highest eligible net ROI with sufficient executable depth and
  capital. Prevent duplicate entries for an asset/window across venues.

Gemini already has a nightly research job. Consume its JSON report according to
[GEMINI_HANDOFF.md](GEMINI_HANDOFF.md), validate trading date, analyzed date,
expiry, checkpoint identity, and per-asset regime permission. Missing or invalid
reports block new entries. Weight recommendations are proposals and must not
silently activate a different model. Report delivery to the guest still needs
implementation.

## 4. Network requirements

Run venue clients inside the `kronos-trading` guest on Baymax. PIA WireGuard is
configured for Singapore. Remote MCP connectors do not inherit this VPN.

Preserve the guest's persistent default-deny egress rules. Check HTTPS, public
WebSockets, DNS, endpoint country, and tunnel-loss behavior using
`python3 -m trading.check_pia`. Its `--test-disconnect` option is disruptive and
must only run when no workload relies on the connection. Verify actual adapter
processes, subprocesses, and long-lived sessions as they are implemented.

A VPN connection does not establish venue eligibility or account permissions.
Do not treat network access as proof that a particular account may trade.

## 5. Paper/testnet validation and review deliverables

Validate supported contract discovery, both sides, fee/depth calculations,
precision/minimum-size handling, stale data rejection, paused regimes, missing
venue checks, insufficient balances, duplicate prevention, and restart recovery.
Exercise simulated fills, partial fills, rejected requests, uncertain submission
results, and final settlement without double-counting or blind retries. Record
client identifiers, observed status transitions, and reconciliation results.

If suitable testnet outcome contracts do not exist, report that limitation and
use deterministic paper fixtures for contract/accounting behavior. Do not claim
testnet execution has been verified using a different instrument.

Deliver a Markdown report listing supported/unsupported capabilities, evidence,
test results, remaining gaps, and an order preview for human review. Leave
mainnet execution disabled. Do not add a live schedule as part of this handoff.

## References

- [Existing Hyperliquid setup guide](HYPERLIQUID_SETUP.md)
- [Venue comparison requirements](VENUE_SELECTION.md)
- [VPN configuration and checks](VPN_SETUP.md)
- [Official Hyperliquid API documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api)
- [Official API wallet documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/nonces-and-api-wallets)
- [Official outcome asset encoding](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/asset-ids)
