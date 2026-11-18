# One forecast, compare every venue, select one trade

Before entry, the runner requires a model forecast containing the expected
terminal BTC/ETH price in USD, a unique `forecast_id`, the actual `model_version`,
the 15-minute target window, and inference completion timestamp. All venue
signals for an asset/window must carry exactly the same forecast ID, version,
expected price, and inference timestamp. A mismatch pauses selection.

`model_expected_price_usd` is the mean terminal price forecast for the window's
end, not an optimistic scenario. Prediction-market signals also require the
model's probability of the contract's outcome. A mean price alone does not
determine P(up); use the forecast distribution and actual resolution rule.
Differences in venue price/settlement sources must be reflected in probabilities.

## Compare executable returns

Each adapter supplies a fresh full-$100 quote including entry costs, spread,
fees, slippage, and depth in `entry_cost_per_unit`.

Only Up/Down prediction contracts are eligible on all three venues. Expected
ROI = probability of the selected side / all-in cost per share - 1. Winning
payout is $1/share; losing payout is $0. Spot, futures, and leveraged products
are rejected.

Rank all candidates by expected ROI on the same $100 committed. Pick the highest
eligible return with sufficient venue cash and ROI strictly above 50%, subject
to Gemini approval. Match the actual start/end times, target price, reference
feed, averaging method, and tie rule before estimating each contract's outcome
probability. A cheaper contract is not necessarily the same bet on another
venue. Different settlement rules may require different probabilities from the
same forecast distribution. Funds are not transferred between venues.

Only **one position per asset/window across all venues** may open, even if later
polls find better odds elsewhere. BTC and ETH may each open a position. If the best
venue lacks $100 available, consider the next eligible funded candidate.
Alternatives, quote costs, outcome probabilities, expected price, and ROI
are stored in `decisions` (`venue_comparison` / `venue_selected`). The position
stores its forecast ID, model version, and expected price. Existing histories
are preserved; old rows may lack these fields.

## Wait for every venue

With `require_all_venue_checks: true` (default), every enabled venue must have a
valid fresh signal for that asset/window, or explicitly report it is unavailable.
Missing feeds and stale quotes do not count as unavailable. This prevents routing
to the first adapter to respond. An unavailable report must reflect a real check,
not an assumption that a slower venue has worse odds.

An adapter unable to offer an executable quote can publish:

```json
{
  "signals": [],
  "settlements": [],
  "venue_checks": [
    {
      "venue": "robinhood", "asset": "BTC", "window_start": 1800000000,
      "checked_at": 1800000005, "status": "unavailable",
      "reason": "No supported executable BTC instrument in the connected account"
    }
  ]
}
```

Replace these illustrative timestamps with current ones. Availability checks
expire after 10 seconds. If all venue results do not arrive within the 90-second
entry period, skip the window.

## Feed the comparison engine

Repeat `--feed` for independently written venue feeds. The runner merges their
signals, settlements, and availability checks on each poll:

```sh
python3 -m trading.runner \
  --feed /absolute/path/coinbase-feed.json \
  --feed /absolute/path/robinhood-feed.json \
  --feed /absolute/path/polymarket-feed.json
```

Each signal needs these fields in addition to its quote and payoff fields:

```json
{
  "forecast_id": "BTC-1800000000-kronos-baseline-001",
  "model_version": "kronos-small:baseline",
  "model_expected_price_usd": 100500,
  "generated_at": 1800000005
}
```

Compute the forecast once, then send it to each adapter. Do not independently
resample forecasts per venue and label them as the same prediction.

Polymarket's public SDK adapter forwards these fields and emits availability
checks after unsuccessful attempts for a current prediction. Coinbase/Robinhood
prediction-contract quote adapters, model inference, authenticated execution, and
final-outcome/redemption integration are
still pending. Offline fixtures verify comparison logic; it does not yet fetch
all three live venue feeds or place real orders.
