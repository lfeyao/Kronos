# Kronos competition experiment 1

Completed November 5, 2026, about 11:48 AM Pacific in
[the Colab research notebook](https://colab.research.google.com/drive/1JWG-M7JL5DDYbNm2G9bfKI3ISaCJ1ffK).
Runtime: NVIDIA A100-SXM4-40GB. Execution time approximately 37.6 seconds.

## Frozen design

- Public Coinbase Exchange BTC-USD and ETH-USD spot 15-minute OHLCV.
- Oct 5 through Nov 3 inclusive: 2,880 complete contiguous candles per asset.
  Cutoff Nov 4 00:00 UTC precedes competition data, to avoid tuning to the contest.
- 120 chronologically spaced forecast windows per asset, 256-bar contexts,
  four-step (one-hour) horizon, eight generated samples, fixed seed 20261105.
- Sequential 60 training / 30 validation / 30 untouched holdout observations
  per asset. Forecast windows do not overlap, but inputs/market regimes are
  dependent. This is a short exploratory holdout, not a rigorous edge estimate.
- Neural model: official Kronos-small, checkpoint unchanged. Training fits
  separate scalar return calibration slopes for Kronos and past-hour momentum,
  clipped to [-1,1]. This tunes output calibration, not foundation-model weights.
- Validation chooses among 5 Kronos/momentum weights and 5 signal thresholds,
  including always flat: 25 settings per asset, 50 total. Active settings need
  at least 5 validation trades. No tuning on final holdout.
- Hypothetical execution: next candle open, exit one hour later; 1x notional,
  0.24% assumed round-trip cost per trade, doubled-cost sensitivity at 0.48%.
  Assumption is not an all-in venue fee quote. Funding, observed futures spreads,
  order-book fills, latency, margin/liquidation and contract granularity omitted.
  Returns are sampled opportunities, not a complete continuous strategy history.

## Results

| Asset | Training calibration: Kronos | Momentum | Validation choice | Holdout trades | Raw Kronos holdout direction |
| --- | ---: | ---: | --- | ---: | ---: |
| BTC | 0.29735 | -0.07228 | Always flat | 0 | 8 / 30 = 26.67% |
| ETH | 0.01702 | 0.22971 | Always flat | 0 | 16 / 30 = 53.33% |

Both validation choices returned 0% with zero trades on holdout, including the
doubled-cost scenario. Zero is the result of no exposure, not evidence of a
profitable or drawdown-free active strategy. The winning tuple's reported
Kronos weight is 0; its infinite threshold makes all weights irrelevant.
The strong shrinkage for ETH indicates little usable training relationship in
this sample. Do not interpret BTC's low holdout hit rate as proof that inversion
will work; trying inversion now would consume this holdout.

The notebook saves input CSVs, all 240 forecasts and report.json under
`/content/competition_experiment_1`. These runtime files are ephemeral; notebook
code and output summary are saved in Drive. Raw artifacts have not yet been
exported to durable storage. No claim of reproducible raw-data archival is made.

## Decision

No live promotion and no competition orders. No validated return edge or
probability of winning was established. Fine-tuning neural weights on these
few observations would invite overfitting rather than justify live use.

Next defensible research stage: a longer point-in-time futures dataset with
funding and realistic execution, multiple predeclared nonoverlapping regime
splits, and forward paper forecasts. This experiment's final holdout is now
observed and cannot be reused as an untouched test after further model changes.
The user's $1,000 loss budget remains a risk objective, not a guarantee from
stops or margin controls. Account eligibility, competition registration,
designated account and starting capital still need verification before trading.
