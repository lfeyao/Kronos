# Hyperliquid access setup

For the development specification, see [HYPERLIQUID_HANDOFF.md](HYPERLIQUID_HANDOFF.md).
For the recorded deployment baseline, see [TRADING_STATUS.md](TRADING_STATUS.md).

Status: setup instructions and a public account checker are available. No account
has been connected or agent approval verified. No Hyperliquid trading adapter or
live runner is enabled. Hyperliquid is not in the runner's configured venues.

## Approve access yourself

1. Open the official [Hyperliquid API page](https://app.hyperliquid.xyz/API)
   and connect the account you intend to use. Confirm the domain yourself.
2. Create a dedicated API/agent wallet named `Kronos`. Review and sign the
   approval in your own wallet. Never share your main wallet's private key or
   recovery phrase. Use a new dedicated agent for each trading process.
3. Keep the agent private key in your local password manager for now. Do not
   paste it into chat, commit it, or add it to Gemini reports. This project does
   not yet have a Hyperliquid signer or credential loader; no secret is needed
   for the account check below.
4. Retain the public account address and public agent address separately. Account
   queries use the actual account address; the agent address is for signing.
   An empty public response does not prove that an address belongs to you or that
   an agent has permission to trade.

Mainnet and testnet are separate. Approval and funds on one do not establish
access on the other. Follow the platform's account eligibility requirements.

## Check public account data

Run from the repository root, replacing the example with your **public account
address**, not a private key or the agent wallet address:

```sh
.venv/bin/python -m trading.check_hyperliquid --address 0xYOUR_PUBLIC_ACCOUNT_ADDRESS
```

For testnet, add `--network testnet`.

The checker uses only public `/info` queries (`openOrders` and
`spotClearinghouseState`). It prints the open-order count and spot balances.
It cannot verify trading authorization, ownership, outcome balances, or complete
portfolio equity. It does not access `/exchange`, sign, trade, cancel, or move
funds. No dependency installation is required.

## Requirements before adding this venue

Our strategy still permits only BTC/ETH 15-minute Up/Down prediction contracts,
$100 stakes, and expected ROI strictly above 50%. Do not substitute spot or
perpetual positions. Official documentation describes HIP-4 outcome assets, but
that alone does not verify suitable live contracts.

Before including Hyperliquid in comparisons, implement and verify live outcome
discovery, exact start/end times, reference prices, settlement feed, tie rules,
side mapping, collateral/payout denomination, fees, full-stake order-book depth,
and settlement ingestion. Agent approval must be checked separately without
using a real order as a connectivity test. Keep it excluded until these checks
pass. Any execution software is user-operated; the assistant does not submit
real-money orders on your behalf.

Sources:

- [Official API/agent wallet documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/nonces-and-api-wallets)
- [Official information endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)
- [Official outcome asset encoding](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/asset-ids)
