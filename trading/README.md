# 15-minute BTC/ETH runner

**Current target (2026-10-24): Coinbase spot paper trading.** See
[SPOT_PAPER.md](SPOT_PAPER.md), `spot_config.json`, and
[Gemini's spot report contract](GEMINI_SPOT_HANDOFF.md). The sections below
document the preserved binary implementation and its separate configuration;
their 50% ROI rule does not apply to the spot engine.

Configured for **expected ROI strictly above 50%**, **$100 total cost per trade**,
and **$1,000 initial paper capital separately for Coinbase, Robinhood, and
Polymarket**. Change `config.json` to lower the threshold. `0.50` means 50%,
not a 50% win probability. Balances persist in SQLite; restarting does not refill
them. Editing starting capital applies only to newly created venue accounts.

New entries also require a fresh **Gemini nightly regime report** for the active
model and current Pacific trading date. The existing Gemini job should publish
`trading/reports/gemini_latest.json` using the [handoff contract](GEMINI_HANDOFF.md).
Missing/expired reports or asset pause decisions block new entries; settlements
continue. Weight updates are recommendations only. No nightly job was created.

The runner compares venues using one shared forecast and selects the best
eligible net expected ROI. See [venue selection](VENUE_SELECTION.md) for the
forecast fields, full-venue readiness checks, and multi-feed invocation.

This is a runnable **paper execution engine**, awaiting authenticated venue connections.
It neither connects to funded accounts nor submits real orders. The model and
authenticated venue adapters still need to be wired. A read-only Polymarket SDK
quote adapter is available as described below. Do not interpret
paper entries as actual fills. No daemon has been installed or started.

## Run

From the repository root, using Python 3 (standard library only):

```sh
python3 -m trading.runner --feed /absolute/path/to/feed.json
python3 -m trading.runner --feed /absolute/path/to/feed.json --once
python3 -m unittest discover -s tests -p 'test_trading_runner.py'
```

The process polls every two seconds to catch fresh model/quote updates and
settlements. Entries are keyed to UTC quarter-hour windows (`unix // 900 * 900`),
one trade per asset/window across all venues. It evaluates only **Up/Down
prediction contracts** on Coinbase, Robinhood, and Polymarket. Spot crypto,
futures, leverage, and other contract types are rejected.

By default it skips entries more than 90 seconds into a window, predictions older
than 90 seconds, quotes older than 10 seconds, future data, other horizons,
missing liquidity, and insufficient paper capital. Inference latency counts toward
the deadline. Duplicate prevention and capital reservation are atomic in SQLite.
Evaluation and skip decisions are logged in `decisions`; trades in `positions`;
free paper capital in `accounts`.

## Adapter input

The model/venue adapter should atomically replace the feed file (write a temporary
file then rename). Send only complete quotes with fees, depth, and slippage already
accounted for **at the full $100 trade size**. The runner does not fetch or verify
those quotes itself. Timestamp fields are Unix UTC seconds.

Example structure below has illustrative prices and a fixed timestamp outside the
current window; it will not open positions today:

```json
{
  "signals": [
    {
      "venue": "polymarket",
      "asset": "BTC",
      "kind": "binary",
      "side": "up",
      "instrument_id": "actual-outcome-token-or-position-id",
      "window_start": 1800000000,
      "horizon_seconds": 900,
      "model_version": "kronos-small:baseline",
      "forecast_id": "BTC-1800000000-001",
      "model_expected_price_usd": 110000,
      "generated_at": 1800000004,
      "quoted_at": 1800000005,
      "probability": 0.70,
      "entry_cost_per_unit": 0.40,
      "executable_budget_usd": 100
    },
    {
      "venue": "coinbase",
      "asset": "ETH",
      "kind": "binary",
      "side": "down",
      "instrument_id": "actual-coinbase-eth-down-contract-id",
      "window_start": 1800000000,
      "horizon_seconds": 900,
      "model_version": "kronos-small:baseline",
      "forecast_id": "ETH-1800000000-001",
      "model_expected_price_usd": 3035,
      "generated_at": 1800000004,
      "quoted_at": 1800000005,
      "entry_cost_per_unit": 0.40,
      "probability": 0.65,
      "executable_budget_usd": 100
    }
  ],
  "settlements": []
}
```

For a binary contract held to final resolution:

`expected ROI = probability_of_selected_side / all_in_cost_per_share - 1`

The example has 75% expected ROI, or $75 expected profit on $100. This is an
estimate based on model probability. Send Down as its own signal using
`probability = 1 - p_up` and the Down contract's own cost and identifier.

The same formula applies to Up/Down contracts on all three venues. Normalize
Yes/No into Up/Down only after inspecting the contract's rules. The ETH example
has 62.5% expected ROI. Fees and depth must be known for the full stake; otherwise
skip that venue. Expected terminal BTC/ETH price is recorded alongside the
contract-specific probability, not substituted for it.

The existing `live_forecast.py` predicts one **5-minute** candle. It cannot be
relabelled as a 15-minute forecast. A Kronos adapter using the repo's 5-minute
candles must sample **three** future candles, compare each path's final close to
the last completed close at window start, and estimate terminal mean price and
P(up) across separate paths. Do not count averaged paths as independent samples.
Use only complete, contiguous historical candles. Polymarket's resolution price
source can differ from Coinbase, so the adapter must account for that when
estimating outcome probability.

## Settlement input

Keep positions open, and funds reserved, until the adapter supplies actual data.
For every venue supply the final resolved Up/Down outcome using that venue's
settlement rules. Repeated settlements have no effect. Instrument IDs must match
the opened position. Pending resolution keeps funds reserved.

```json
{
  "signals": [],
  "settlements": [
    {
      "venue": "polymarket", "asset": "BTC",
      "instrument_id": "actual-outcome-token-or-position-id",
      "window_start": 1800000000, "observed_at": 1800001000,
      "resolved": true, "winning_side": "up"
    },
    {
      "venue": "coinbase", "asset": "ETH",
      "instrument_id": "actual-coinbase-eth-down-contract-id",
      "window_start": 1800000000, "observed_at": 1800001000,
      "resolved": true, "winning_side": "down"
    }
  ]
}
```

## Polymarket SDK quote adapter

`python3 -m trading.polymarket` uses the official Python `polymarket-client`
package's `PublicClient`. It requires no signing credentials and cannot submit
orders. `trading/requirements.txt` declares the optional dependency; it has not
been installed by this change. Use a project `.venv` managed with uv to install it.

Provide a model-output JSON array, with one object per asset:

```json
[
  {
    "asset": "BTC", "window_start": 1800000000,
    "model_version": "kronos-small:baseline",
    "forecast_id": "BTC-1800000000-001",
    "model_expected_price_usd": 110000,
    "horizon_seconds": 900, "generated_at": 1800000005, "p_up": 0.70
  }
]
```

Replace the illustrative timestamps with the actual current target window and
inference completion time. The adapter looks up `btc-updown-15m-<window>` or its
ETH equivalent. It validates expiry/status, maps outcomes by label, selects CTF
token IDs or V2 position IDs, and reads fresh full-size books. It uses each market's
fee schedule and skips missing fee settings or unsupported fee exponents. It
conservatively charges all shares at the worst ask required for $100, with fee
rounding upward, rather than reporting an optimistic top-of-book fill.

```sh
python3 -m trading.polymarket --predictions /absolute/path/predictions.json --output /absolute/path/polymarket-feed.json
python3 -m trading.runner --feed /absolute/path/polymarket-feed.json
python3 -m unittest discover -s tests -p 'test_polymarket_adapter.py'
```

Use a dedicated output feed: this adapter overwrites it atomically and publishes
only Polymarket entry signals and availability checks. The runner merges venue
feeds when `--feed` is repeated. The adapter does not run inference,
or supply settlements. Until settlement data is provided as described above,
paper positions remain open and their capital stays reserved. Unit checks use
SDK-shaped fixtures; the actual package and live network have not been smoke-tested.

For authenticated execution, use the SDK's `SecureClient` and configure the
account's wallet/signer locally. Deposit Wallet session keys are a documented
option for scoped access; availability depends on the account. No private keys
belong in the feed, repository, or chat. References:
[Python SDK](https://docs.polymarket.com/getting-started/python),
[wallet authentication](https://docs.polymarket.com/trading/wallets-auth),
[session keys](https://docs.polymarket.com/trading/session-keys).

## Pending authenticated venue adapters

Each live venue adapter needs supported instrument discovery, balance/positions,
fresh executable bid/ask depth and fees, minimum sizes and quantity precision,
order submission/status, cancellation, and exit/resolution support. We must
inspect each supplied server's actual capabilities before implementing its calls.
Live execution also needs persisted order intents, order-status reconciliation
after uncertain responses/restarts, and final-outcome/redemption handling. None of those live
capabilities are represented by this paper engine's simulated fills.

Fee and order semantics references for the future Polymarket adapter:
[fees](https://docs.polymarket.com/trading/fees),
[market details](https://docs.polymarket.com/market-data/market-details),
[orders](https://docs.polymarket.com/trading/place-orders).
