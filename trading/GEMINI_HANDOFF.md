# Nightly Gemini report contract

**Spot research:** use [GEMINI_SPOT_HANDOFF.md](GEMINI_SPOT_HANDOFF.md) for the
Coinbase spot target selected on 2026-10-24. The contract below remains specific
to binary prediction markets and does not approve spot entries.

Give this Markdown file to the existing Gemini job as its specification. Its
daily deliverable should be **valid JSON**, not a Markdown table or free-form
chat response. An additional Markdown summary is welcome, but the runner consumes
the JSON file.

## Objective and fixed trading scope

Answer four questions each night:

1. Is the current model suitable for trading BTC and ETH Up/Down prediction
   contracts in the present regime, separately for each asset?
2. Does the evidence justify evaluating a change to model weights?
3. Are the venues' contracts equivalent enough for a cheapest-price comparison,
   and what data or integration gaps prevent a reliable comparison?
4. Are there other 15-minute Up/Down prediction markets worth observing,
   paper-testing, or proposing for addition based on repeatable net edge?

Scope: BTC/ETH, 15-minute Up/Down prediction markets only, on Coinbase,
Robinhood, and Polymarket. No spot crypto or futures trades. Current settings
are $100 per trade, expected ROI strictly above 50%, and $1,000 starting capital
per venue. One selected position per asset/window across venues. Read
`trading/config.json` each run for active settings and model version; report any
change, but do not edit the configuration.

The research universe may include other underlying assets, but the trading
universe remains BTC/ETH. Market-expansion recommendations are research output;
they never authorize new assets or modify the runner's allowlist.

Daily approval is a regime assessment, not a specific order or a replacement for
fresh per-window forecasts. The execution process must still obtain the model's
expected terminal price and contract-specific outcome probability, live quotes,
fees, liquidity, and balances at entry time.

Use the existing Gemini job; no new schedule is needed. After each complete
Pacific calendar day, review that day's BTC/ETH data, model predictions, actual
outcomes, and available trade/fill results. Write a machine-readable JSON report
for the next trading date. The runner reads it locally on every feed-processing
cycle. This is a file integration, not an automated message to the Codex chat.

## Deliver files

- Archive: `/Users/daiyu/Documents/Code/Kronos/trading/reports/<report_id>.json`
- Current: `/Users/daiyu/Documents/Code/Kronos/trading/reports/gemini_latest.json`
- Optional human summary:
  `/Users/daiyu/Documents/Code/Kronos/trading/reports/<report_id>.md`
- Optional detailed observations:
  `/Users/daiyu/Documents/Code/Kronos/trading/reports/<report_id>.jsonl`

Create the `reports` folder if needed. Write the archive first, then write a
temporary file in the same folder and rename it over `gemini_latest.json`.
Never edit a report in place or reuse its ID with different contents. These local
reports are ignored by Git; retain archives for audit/history.

## Required JSON structure

This is a **paused example**, not an assessment of the current market:

```json
{
  "schema_version": 1,
  "source": "gemini",
  "report_id": "gemini-2026-10-22T090000Z",
  "model_version": "kronos-small:baseline",
  "horizon_seconds": 900,
  "analyzed_date": "2026-10-21",
  "trading_date": "2026-10-22",
  "generated_at": "2026-10-22T09:00:00Z",
  "expires_at": "2026-10-23T07:00:00Z",
  "assets": {
    "BTC": {
      "trade_allowed": false,
      "regime": "uncertain",
      "reason": "Example only; replace with an evidence-based decision.",
      "metrics": {
        "expected_windows": 96,
        "evaluated_windows": 0,
        "coverage_fraction": 0.0,
        "settled_trades": 0,
        "unresolved_trades": 0,
        "directional_accuracy": null,
        "brier_score": null,
        "market_brier_score": null,
        "terminal_price_mae_usd": null,
        "net_realized_pnl_usd": null,
        "settled_stake_usd": 0.0,
        "net_realized_roi": null
      }
    },
    "ETH": {
      "trade_allowed": false,
      "regime": "uncertain",
      "reason": "Example only; replace with an evidence-based decision.",
      "metrics": {
        "expected_windows": 96,
        "evaluated_windows": 0,
        "coverage_fraction": 0.0,
        "settled_trades": 0,
        "unresolved_trades": 0,
        "directional_accuracy": null,
        "brier_score": null,
        "market_brier_score": null,
        "terminal_price_mae_usd": null,
        "net_realized_pnl_usd": null,
        "settled_stake_usd": 0.0,
        "net_realized_roi": null
      }
    }
  },
  "weight_update": {
    "recommended": false,
    "action": "keep",
    "reason": "Example only; review evidence before recommending changes.",
    "candidate_version": null,
    "candidate_artifact_path": null,
    "validation_summary": null
  },
  "data_quality": {
    "status": "insufficient",
    "missing_inputs": ["Example only; replace with actual missing inputs"],
    "sources": []
  },
  "contract_equivalence_review": {
    "groups": [],
    "mismatches": [],
    "unknowns": ["Example only; contract rules have not been reviewed"]
  },
  "market_expansion_review": {
    "reviewed_at": "2026-10-22T09:00:00Z",
    "scope": "15-minute Up/Down prediction contracts only",
    "candidates": [],
    "discovery_gaps": ["Example only; candidate discovery has not been performed"],
    "summary": "No market additions recommended without supporting evidence."
  },
  "summary": "Paused example only; no actual analysis has been performed."
}
```

Dates use `America/Los_Angeles`; timestamps require an explicit offset or `Z`.
`analyzed_date` is the prior Pacific date. `trading_date` must be the current
Pacific date. Generate the report after that day's midnight, and expire it no
later than the next midnight (or earlier if evidence becomes stale). Lifetime and
age must also stay within the configured 26-hour maximum. Account for daylight
saving transitions. Entries pause at midnight until that day's report arrives;
there is no carry-forward of yesterday's permission.

`model_version` must identify the **actual checkpoint evaluated**, match the
active version in `trading/config.json`, and match each inference signal. The
initial symbolic ID is `kronos-small:baseline`; use a checkpoint/revision/hash ID
when inference is wired. Changing an active checkpoint invalidates its prior
report. Do not merely copy an active ID onto an evaluation of different weights.

`assets.<asset>.trade_allowed` must be a JSON boolean. Missing decisions, strings
such as `"true"`, unknown regimes without a reason, and invalid reports block
entries for the affected asset. BTC and ETH decisions are independent and apply
across the configured venues. Approval still requires the runner's ROI, freshness,
liquidity, balance, and duplicate checks; it cannot change the $100 size or 50%
minimum expected ROI.

The runner currently validates the report identity, dates, lifetime, model
version, horizon, per-asset decisions/reasons, and weight recommendation flag.
The additional evidence fields requested in this document are preserved for
review; they are not independently statistically verified or enforced by the
current parser. Keep the schema at version 1 unless the consumer is updated too.

## Input data and provenance

Read available inputs from this checkout:

- `trading/config.json`: active settings and checkpoint ID.
- `trading/runner.sqlite3`, **if it exists**: `positions`, `decisions`, and
  `regime_reports`. Positions contain expected price, forecast ID, selected venue,
  cost, expected ROI, realized P&L when settled, and report ID. Decisions include
  venue comparisons and selection/rejection reasons.
- `data/BTC.csv` and `data/ETH.csv`: historical candles. Inspect frequency,
  timestamps, source, freshness, and gaps before using them.
- Forecast/quote/outcome archives supplied by the model and venue adapters, when
  available. A database row or last price is not proof of an executable fill.
- `paper/paper.db`, **if it exists**, is the legacy **5-minute** experiment.
  Label it separately; never present those results as 15-minute validation.

The new runner, inference, and all venue integrations may not yet be running.
Missing databases or unavailable predictions are valid findings. Report what is
missing and pause any affected asset when evidence is insufficient. Do not invent
observations, fill prices, probabilities, model versions, or positive results.

In `data_quality.sources`, list each file/table or API source used, its covered
time range, collection time, source version/hash when available, and whether it
is observed, reconstructed, simulated, or actual live execution data. Read
databases without changing them. Do not include credentials in any report.

## Required evidence per asset

Populate `assets.BTC` and `assets.ETH` independently. Use JSON numbers for
measurements, JSON booleans for decisions, and `null` for unavailable metrics;
explain missing values in `data_quality.missing_inputs` and the asset's reason.
Zero means a measured zero, not unknown. Never emit NaN or Infinity.

| Field or analysis | What to report |
| --- | --- |
| `regime` | A descriptive label such as trending, ranging, high-volatility, low-liquidity, mixed, or uncertain; explain the measured evidence. |
| `trade_allowed` and `reason` | A clear trade/pause decision for the current model, with the strongest evidence and limitations. |
| `expected_windows`, `evaluated_windows`, `coverage_fraction` | Unique 15-minute windows per asset, data gaps, and observed coverage; do not count three venues as three independent price windows. |
| `directional_accuracy`, `brier_score` | Score actual resolved forecasts; Brier is mean squared probability error, lower is better. State the sample count and outcome reference. |
| `market_brier_score` | A market probability baseline observed at the same decision time, on the same contracts and matched outcome sample. Never use final/resolved prices as the baseline. |
| `terminal_price_mae_usd` | Mean absolute error of the model's terminal price forecast, scored against its declared price source and horizon. |
| `settled_trades`, `unresolved_trades` | Show finalized versus pending positions separately. A day-end open position is not a realized loss or win. |
| `net_realized_pnl_usd`, `settled_stake_usd`, `net_realized_roi` | Net P&L after applicable costs, the matching settled capital, and P&L divided by that capital. Use null ROI when no capital is settled. |
| Calibration and concentration | Reliability by probability bucket, cheap-contract concentration, largest wins/losses, and whether a few trades dominate results. Include sample counts. |
| Venue breakdown | Per-venue coverage, costs, executable depth, unavailable checks, selected trades, and settled results. Separate prediction-contract observations from spot reference data. |
| Historical context | Where data allows, append separately labeled trailing 7-day and 30-day metrics using the same definitions. State actual coverage and uncertainty. |

The example has 96 expected windows for a normal Pacific day. Compute this from
the actual UTC duration of that local day: DST transitions can produce 92 or 100.
Use UTC timestamps as unique IDs during the repeated fall-back hour.

All ROI, accuracy, and coverage values are **fractions** (`0.50` means 50%). USD
values are dollars; probabilities are in `[0, 1]`. Clearly label denominators and
sample sizes. State whether results are grouped by entry date or settlement date;
do not mix those cohorts within one ROI calculation.

Do not invent an arbitrary minimum sample threshold or claim that one profitable
day establishes an edge. Explain the uncertainty and evidence for your decision.

## Contract equivalence and venue comparison

For each matched BTC/ETH window, inspect each venue's actual contract metadata:

- Underlying asset and normalized Up/Down side.
- Exact UTC observation start and end; trading cutoff separately from resolution
  and payout time.
- Target/reference price and how it is set.
- Resolution feed/index, averaging method and interval, rounding, tie treatment,
  and exceptional/cancellation rules.
- Winning payout and applicable fee schedule.

In `contract_equivalence_review.groups`, list the concrete contract IDs, venues,
and rules that establish equivalence. List differing rules under `mismatches`
and unavailable evidence under `unknowns`. Matching times alone is insufficient.
Do not assume Coinbase/Robinhood listings or their MCPs expose identical products
or support prediction-market execution; verify capabilities.

For equivalent contracts on the same side, compare the **all-in executable price
for $100**, not a mid price, last trade, or an ask with insufficient depth. For
different settlement rules, estimate a separate win probability for each contract
from the same forecast distribution. Do not automatically select the cheapest
contract if it is a different bet.

Expected ROI for a $1/zero Up/Down contract is:

`probability_of_selected_outcome / all_in_cost_per_share - 1`

The model's mean expected BTC/ETH price is useful context but does not determine
the outcome probability by itself. Preserve both in the evaluation evidence.
Daily contract reviews are historical evidence; the execution adapters must
recheck each new contract's current rules, fees, quote, and cutoff.

## What Gemini should review

Review observed forecast calibration, directional results, net returns after
costs, data gaps, volatility/trend/liquidity changes, and differences between
the model's price source and each venue's settlement rule. Distinguish paper
results from actual fills and unresolved positions. Include metrics, sample
counts, coverage, uncertainty, and evidence behind each decision. The runner
records the full report but does not independently verify Gemini's statistical
claims or impose an invented minimum sample count.

A weight-change recommendation is separate from permission to trade the current
model. Use `trade_allowed: false` when the current model should pause while a
candidate is evaluated. Recommendations **never alter active weights**. Proposed
weights should be staged with a distinct version and evaluated on held-out,
time-ordered data; training on a day and scoring on that same day is not evidence
of improved future performance. The training/promotion pipeline is not built by
this report integration.

Use `weight_update.action` as `keep`, `evaluate_candidate`, or `insufficient_data`.
If recommending a candidate, include its actual checkpoint/revision/hash, local
artifact path if one exists, training data interval, held-out test interval,
baseline-versus-candidate metrics, costs, uncertainty, and any regressions in
`validation_summary`. If no candidate exists, leave its version/path null and
describe the proposed experiment. Do not overwrite, activate, or retrain the live
model as part of producing this report. Do not lower the trading threshold.

## Daily market-expansion review

Run this research review every night alongside the BTC/ETH regime assessment.
Discover other available **15-minute Up/Down prediction contracts** on the
configured venues. Verify actual listings, rules, market-data access, and
execution capability; do not assume an asset is available on every venue. Broader
events, spot crypto, futures, and different durations are outside this review.

Evaluate whether the current model and data pipeline work for each underlying.
Do not assume a model evaluated on BTC/ETH transfers to another asset. If another
checkpoint or calibration is necessary, identify it separately and propose an
experiment without modifying active weights.

Use a persistent candidate roster, retaining rejected and inconclusive results
as well as winners. Record first-observed date and stable evaluation ID so daily
reruns extend an evaluation rather than repeatedly resetting its test period.
An empty candidate list is valid only when its discovery coverage and gaps are
explained. Preserve prior archives for longitudinal evaluation.

### Evaluation stages

1. **Discover:** identify concrete contracts, settlement rules and price source,
   reliable reference history, venue/API access, and data gaps.
2. **Observe:** collect timestamped forecasts, both sides' executable books,
   actual fees, full-$100 depth, and resolved outcomes. Retain every observed
   window, including rejected opportunities, stale quotes, and unfilled attempts.
   Do not reconstruct historical executable quotes from candle closes.
3. **Validate:** freeze model/checkpoint, feature/calibration settings, entry
   timing, routing, costs, and the >50% expected-ROI filter before the forward
   evaluation. Separate development data from later unseen validation data and
   reserve a final untouched test period. If a rule changes, start a new named
   evaluation; do not relabel its earlier results as a fixed-strategy test.
4. **Paper-test:** use the actual runner's timing and $100 size assumptions,
   accounting for depth, slippage, fees, latency, unavailable venues, missed fills,
   settlement delays and reserved cash. Hypothetical fills and actual fills must
   remain separately labeled. The current runner does not yet support candidate
   assets; recommend such testing or use clearly labeled offline research without
   modifying the active allowlist.
5. **Assess incremental value:** compare BTC/ETH alone against BTC/ETH plus the
   candidate on matched periods, under the same $1,000-per-venue starting capital,
   $100 stakes, routing rules and cash constraints. Report incremental net P&L,
   drawdown, correlated losses, capital locked until settlement, and BTC/ETH
   opportunities displaced by the candidate. Do not give the expanded portfolio
   extra capital and present its larger raw profit as an improvement.

Large model-versus-market disagreements, low contract prices, wide spreads, or
slow quote updates are investigation signals, not proof of inefficiency. The
model may be wrong, and apparent edge may be unavailable at the required size.
Require evidence of repeatable **net executable edge**.

### Candidate scorecard format

Populate `market_expansion_review.candidates` with one object per underlying
asset, containing per-venue results. This placeholder is a structure example,
not an evaluated asset or an approval:

```json
{
  "asset": "EXAMPLE_ASSET",
  "evaluation_id": "example-fixed-strategy-v1",
  "first_observed_date": "2026-10-21",
  "stage": "discover",
  "recommendation": "watch",
  "reason": "Example only; collect valid forward evidence before proposing addition.",
  "venues_checked": ["coinbase", "robinhood", "polymarket"],
  "available_venues": [],
  "contract_rules_verified": false,
  "model_version_evaluated": null,
  "model_transfer_validated": false,
  "development_period": null,
  "validation_period": null,
  "untouched_test_period": null,
  "unique_observed_windows": 0,
  "eligible_opportunities": 0,
  "settled_paper_trades": 0,
  "unresolved_paper_trades": 0,
  "net_realized_roi": null,
  "roi_confidence_interval_95": null,
  "uncertainty_method": null,
  "brier_score": null,
  "market_brier_score": null,
  "full_stake_executable_fraction": null,
  "largest_five_wins_share_of_gross_profit": null,
  "results_without_largest_five_wins": null,
  "performance_by_regime": [],
  "venue_breakdown": [],
  "incremental_portfolio_results": null,
  "search_trials_disclosed": null,
  "data_gaps": ["Example only; no observations have been collected"],
  "next_action": "Verify listings, model suitability, settlement rules, and data access."
}
```

Use stages `discover`, `observe`, `validate`, `paper_test`, or `portfolio_review`.
Use recommendations `watch`, `paper_test`, `consider_adding`, `reject`, or
`insufficient_data`. Dates/periods need explicit UTC boundaries; use the same
fraction/USD/null conventions as the BTC/ETH report. An unavailable venue must
have a documented reason. Counts must distinguish windows from separate venue
quotes on the same underlying event.

Include daily and cumulative fixed-evaluation results, plus trailing 7/30-day
results where available. Confidence intervals must state the method and sample
size; account for serial dependence and shared outcomes across venues (for
example, with an appropriate time-block bootstrap). Do not treat repeated quotes
or correlated contracts as independent trials. State assumptions and limitations.

Disclose all candidate assets and strategy/calibration variants searched.
Account for selecting the best result from many trials; a nominal 95% interval
for the winner alone is not sufficient evidence after an unrestricted search.
Use the untouched forward period to check whether the discovered edge persists.

### Recommendation requirements

- `watch`: potentially interesting, but listings, execution, model transfer, or
  evidence still need investigation. Specify the next measurable step.
- `paper_test`: rules and data are usable and an experiment is defined; recommend
  prospective testing without real orders or active-universe changes.
- `consider_adding`: the fixed-strategy forward evaluation supports positive net
  edge under a stated uncertainty/selection analysis, full-$100 execution is
  practical, results survive realistic cost/latency assumptions and concentration
  checks, and the equal-capital portfolio comparison supports an addition.
  Describe remaining uncertainty and a proposed monitored trial; do not call it
  proven profitability.
- `reject`: evidence or operational constraints argue against inclusion; document
  the specific failure and conditions that would justify revisiting it.
- `insufficient_data`: uncertainty or too few qualifying observations prevents a
  conclusion. Keep the >50% expected-ROI rule unchanged; do not lower it just to
  generate a larger sample or count a day with no trades as evidence of edge.

No fixed number of days or trades automatically establishes suitability. Do not
promote an asset based on a single profitable day or a handful of cheap-contract
wins. Keep evidence on rejected/inconclusive candidates to reduce selection bias.

Candidate recommendations are informational extensions to schema version 1.
The runner archives them with the report but does not automatically implement
them. Never add candidate assets to the active `assets` decisions, change config,
activate a checkpoint, or place an order through this daily research job. The
user must approve expansion and the runner/venue adapters must support it first.

## Optional per-window evidence file

For deeper audit, write JSONL with one object per venue/asset/window/side. Include
`forecast_id`, `model_version`, `window_start`, `window_end`, `generated_at`,
`quoted_at`, `venue`, `asset`, `instrument_id`, `side`,
`model_expected_price_usd`, `probability`, `entry_cost_per_unit`,
`executable_budget_usd`, `expected_roi`, the contract rule metadata above, actual
resolved outcome, net realized P&L, and a data-type label (paper/live/reconstructed).
Use Unix UTC seconds for these observation timestamps, matching the adapter feeds.
Unknown outcomes or prices must be null; do not synthesize missing quotes.

This JSONL is historical review evidence, not an executable feed. If its location
is outside the report folder, include an explicit artifact path in the report.

## Publish checklist

1. Parse the output as JSON with no surrounding code fences or explanatory prose.
2. Confirm the model ID is the one actually evaluated and matches active config.
3. Confirm prior-day analysis, current trading date, timezone-aware timestamps,
   and expiry. Review both assets; use explicit pauses for uncertainty/missing data.
4. Check numeric units, sample counts, missing-value explanations, and provenance.
5. Include the daily market-expansion review, its discovery coverage, candidate
   scorecards and next actions, including rejected or inconclusive candidates.
6. Write the immutable archive, then atomically replace `gemini_latest.json`.
7. Optionally write a short Markdown summary: BTC decision, ETH decision, evidence,
   recommended weight action, contract mismatches, candidate-market recommendations,
   and missing inputs.

## Runner behavior

The runner defaults to the current-report path above. Override it with:

```sh
python3 -m trading.runner --feed /absolute/path/feed.json --regime-report /absolute/path/gemini_latest.json
```

Every model signal also needs `"model_version": "kronos-small:baseline"` (or the
actual configured checkpoint ID). The Polymarket quote adapter forwards that
field from its prediction input.

Signals also carry `forecast_id` and `model_expected_price_usd`. The runner
compares all enabled venues using the same forecast before selecting one eligible
trade per asset/window. See [venue selection](VENUE_SELECTION.md).

Valid reports are stored in the SQLite `regime_reports` table. Positions record
their `regime_report_id`; rejected entries record `regime_blocked` and a reason in
`decisions`. A missing report blocks entries but never blocks paper settlements.
The runner must be running for it to consume new reports. It does not notify this
chat or launch Gemini. Live trading remains unimplemented.
