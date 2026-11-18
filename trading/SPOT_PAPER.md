# Coinbase spot paper runner

Active development target: BTC/ETH USD spot, long or cash, 15-minute forecasts.
The user chose positive predicted net return after costs for paper research.
This engine does not submit orders, use account keys, borrow, short, or trade
futures. Binary code/configuration/history are preserved separately.

## Strategy and cost model

`spot_config.json` sets $100 total simulated entry cost including the buy fee,
$1,000 shared simulated Coinbase cash, and at most one position per asset.
Enter within the first 90 seconds of a UTC quarter-hour; exit at its end. Late
entry therefore has less than 15 minutes of remaining holding time.

The paper threshold is **net expected return strictly above zero**. It is a
research baseline, not validated profitability. The old binary 50% ROI rule
does not apply. Set `minimum_expected_net_return` to `null` to pause entries.

The Coinbase SPOT fee tool returned maker 0.005 / taker 0.009 on 2026-10-24.
The paper config uses the **0.9% taker rate on each side**, roughly 1.8% round
trip before spread/slippage. There is no automatic account fee refresh.
Additional research assumptions are 5 bps adverse slippage per side and a 1 bp
half-spread at the expected terminal midpoint. These are explicit assumptions,
not measured fill guarantees. Current entry spread is already included by using
the ask; actual simulated exits use the bid.

```text
entry_price = ask * (1 + entry_slippage_bps / 10000)
quantity = stake / (entry_price * (1 + buy_fee_rate))
expected_exit_bid = predicted_midpoint * (1 - expected_exit_half_spread_bps / 10000)
expected_net_proceeds = quantity * expected_exit_bid * (1 - exit_slippage_bps / 10000) * (1 - sell_fee_rate)
expected_net_return = expected_net_proceeds / stake - 1
```

The existing `train_15m.py` direction classifier does not produce the terminal
midpoint required here. A calibrated price/return forecast adapter is still
needed. Do not invent a terminal price from a probability of finishing Up.
No inference or training process has been started on Baymax.

## Public quote collector

Only Coinbase Advanced's public product-book GET endpoint is used. The adapter
checks product identity, server timestamp, request latency, bid/ask and sizes.
Stale/future, crossed, or empty books are unusable. Failed assets do not reuse
their old snapshot. No authentication, balance access, or order endpoints occur.

```sh
python3 -m trading.coinbase_spot_quotes --output trading/reports/coinbase_spot_quotes.json --once
```

Omit `--once` to poll every two seconds. A paper fill requires sufficient base
quantity at the top book level for the full position. Partial fills, exchange
precision/minimum-size constraints, latency, and queue position are not simulated.

Reference: [Coinbase public product book](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/public/get-public-product-book).

## Forecast feed

Write an atomic JSON object containing a `forecasts` array. Each entry requires:

| Field | Meaning |
| --- | --- |
| `asset`, `product_id` | BTC / BTC-USD or ETH / ETH-USD |
| `price_basis` | `mid` |
| `window_start` | UTC quarter-hour start in Unix seconds |
| `horizon_seconds` | 900 |
| `generated_at` | Actual generation time in Unix seconds |
| `forecast_id` | Nonempty unique forecast identity |
| `model_version` | Configured and evaluated checkpoint identity |
| `model_expected_price_usd` | Positive finite expected midpoint at window end |

Forecasts must be generated within the current window and no more than 90 seconds
old. Quotes must be at most 10 seconds old. Conflicting forecasts or quotes for
an asset are rejected. A negative forecast means remain in cash; it does not
short or replace the timed exit rule for an existing position.

## Gemini gate and manual run

Follow [GEMINI_SPOT_HANDOFF.md](GEMINI_SPOT_HANDOFF.md). Reports must explicitly
review `coinbase_spot_15m` and the exact active configuration hash:

```sh
python3 -m trading.spot_runner --print-config-hash
```

The Pacific trading date, prior-day analysis, expiry, checkpoint, immutable report
ID, and asset pause gates remain in force. Changes to costs, sizing, model, or
other config fields require a new matching report. Binary reports cannot approve
spot. No weight recommendation activates a model automatically.

After a collector, actual forecasts, and a valid review are available:

```sh
python3 -m trading.spot_runner \
  --feed trading/reports/coinbase_spot_quotes.json \
  --forecasts trading/reports/spot_forecasts.json \
  --regime-report trading/reports/gemini_spot_latest.json
```

Add `--once` for one cycle. Default state is `trading/spot_paper.sqlite3` with
`spot_cash`, `spot_positions`, `spot_reports`, and `spot_decisions` tables.
Restarting never refills the shared cash. Entries preserve forecasts, costs,
quotes, report references, and predicted economics; exits record simulated net
proceeds and realized P&L.

Exits run before forecast/report gates. They require a fresh full-size bid
timestamped at or after the deadline. Missing/insufficient bids leave holdings
open and cash reserved; overdue exits block new entries. Repeated snapshots or
restarts cannot credit twice. Open positions retain their original exit cost
assumptions when config changes. Mark-to-market portfolio equity is not yet
reported, so cash alone is not a complete performance metric while holding coins.

## Deployment and testing

Run venue clients inside Baymax's PIA-protected `kronos-trading` guest at
`/home/baymax.guest/kronos`. See [VPN_SETUP.md](VPN_SETUP.md). Sources are staged
for manual testing; no collector or paper runner daemon is started automatically.

```sh
python3 -m unittest discover -s tests -p test_spot_runner.py
python3 -m unittest discover -s tests -p test_coinbase_spot_quotes.py
```

No predictive edge is established by passing tests or fetching quotes. Evaluate
chronological held-out net returns, coverage/no-trade frequency, forecast errors,
calibration, drawdown, turnover, and fee/slippage sensitivity. Model inference,
nightly report delivery, historical quote capture, and continuous deployment
supervision remain separate integration work.
