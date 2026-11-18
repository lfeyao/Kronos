# Hyperliquid Integration & Validation Report

Generated in accordance with [`trading/HYPERLIQUID_HANDOFF.md`](HYPERLIQUID_HANDOFF.md) and [`trading/HYPERLIQUID_SETUP.md`](HYPERLIQUID_SETUP.md). Mainnet order execution remains disabled.

## 1. HIP-4 Contract Availability & Equivalence Evidence

Per official [Hyperliquid HIP-4 Outcome Markets documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/hip-4-outcome-markets) and [Asset IDs specification](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/asset-ids):

* **HIP-4 Outcome Encoding**:
  * Derived from integer `outcome_id` and binary `side` (`0` or `1`): `encoding = 10 * outcome_id + side`.
  * Spot coin symbol: `#<encoding>` (e.g., `#10` for outcome `1`, side `0`).
  * Token name: `+<encoding>` (e.g., `+10`).
  * Exchange action asset ID: `100_000_000 + encoding` (e.g., `100000010`).
* **15-Minute BTC/ETH Up/Down Availability**:
  * Hyperliquid's initial HIP-4 rollout defines a recurring binary outcome that settles **daily at 06:00 UTC** to the BTC mark price on HyperCore (`86,400s` horizon), with additional outcome markets rolling out in stages.
  * Because our strategy strictly requires **15-minute (`900s`) binary Up/Down contracts** and forbids substituting 24-hour outcomes, spot crypto, or perpetual futures, `trading/hyperliquid.py` (`discover_15m_outcomes`) checks `outcomeMeta` for exact `900s` UTC window alignment (`window_end == window_start + 900`) and publishes an explicit `status: "unavailable"` venue check whenever matching 15-minute BTC/ETH contracts are not listed.

## 2. Supported vs. Unsupported Capabilities

| Capability | Module / Entrypoint | Status | Notes |
| :--- | :--- | :--- | :--- |
| **HIP-4 Outcome Asset Encoding** | `trading.hyperliquid.encode_outcome` | **Supported & Verified** | Implements `#<encoding>`, `+<encoding>`, and `100_000_000 + encoding` |
| **15m Contract Discovery** | `trading.hyperliquid.discover_15m_outcomes` | **Supported & Verified** | Rejects 24h daily outcomes, spot, and perps; requires exact `900s` window |
| **Full-$100 Depth & Fee Quoting** | `trading.hyperliquid.quote_outcome_book` | **Supported & Verified** | Walks `l2Book` asks for `#<encoding>`, rounds fees up, rejects stale books ($>10\text{s}$) |
| **Explicit Unavailable Venue Check** | `trading.hyperliquid.build_feed` | **Supported & Verified** | Emits runner-compatible `venue_checks` when 15m outcomes are absent |
| **Separated Credential Storage** | `trading.save_hyperliquid_credentials` | **Supported & Verified** | Saves `account_address`, `agent_address`, and hidden `agent_private_key` to `~/.config/kronos/hyperliquid.json` (`0600`) |
| **Non-Executing Agent Verification** | `trading.check_hyperliquid` | **Supported & Verified** | Verifies `userRole` (`role == "agent"`) and `extraAgents` (`name == "Kronos"`, `validUntil`) via `/info` with 0 orders |
| **Deterministic Order Preview** | `trading.hyperliquid.preview_order` | **Supported & Verified** | Produces human-reviewable `/exchange` IOC limit order wire payload |
| **Live Order Submission** | Disabled by design | **Disabled** | Mainnet/testnet signing and `/exchange` submission remain disabled pending user-approved live 15m listings |

## 3. Deterministic Order Preview (Human Review)

For a qualifying 15-minute BTC Up outcome (`outcome_id = 7`, `side = 0` $\rightarrow$ `spot_coin = "#70"`, `asset_id = 100000070`) with calibrated $P(\text{up}) = 0.70$, worst-ask full-$100 depth price $0.40$, and expected ROI $+75.0\%$ ($> 50\%$ threshold), `trading.hyperliquid.preview_order` generates:

```json
{
  "preview_only": true,
  "live_execution_enabled": false,
  "network": "testnet",
  "venue": "hyperliquid",
  "asset": "BTC",
  "side": "up",
  "window_start": 1800000000,
  "spot_coin": "#70",
  "hyperliquid_asset_id": 100000070,
  "model_probability": 0.7,
  "expected_roi": 0.75,
  "eligible": true,
  "exchange_action_payload": {
    "type": "order",
    "orders": [
      {
        "a": 100000070,
        "b": true,
        "p": "0.4",
        "s": "250.0",
        "r": false,
        "t": {
          "limit": {
            "tif": "Ioc"
          }
        },
        "c": "0x00000000000000000000000000000001"
      }
    ],
    "grouping": "na"
  }
}
```

## 4. How to Connect & Verify Your `Kronos` Agent Wallet

1. **Save Your Separated Account & Agent Credentials Locally** (inside the `kronos-trading` guest or local terminal):
   ```sh
   python3 -m trading.save_hyperliquid_credentials
   ```
   *(Prompts for your main public `0x` address, your dedicated `Kronos` agent public `0x` address, and hidden agent private key; saves to `~/.config/kronos/hyperliquid.json` with mode `600`).*
2. **Verify Public Account Balances & Non-Executing Agent Approval**:
   ```sh
   python3 -m trading.check_hyperliquid --from-saved
   ```
   *(Queries `/info` `openOrders`, `spotClearinghouseState`, `userRole`, and `extraAgents` to confirm your `Kronos` agent wallet is authorized and un-expired, with `orders_submitted: 0`).*
3. **Inspect Live HIP-4 Outcome Listings**:
   ```sh
   python3 -m trading.hyperliquid --discover-only --network mainnet
   python3 -m trading.hyperliquid --discover-only --network testnet
   ```
4. **Run the Unit Test Suite**:
   ```sh
   python3 -m unittest discover -s tests -p 'test_hyperliquid_adapter.py'
   ```
