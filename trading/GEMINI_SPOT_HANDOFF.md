# Gemini daily Coinbase spot research

The active target changed to BTC/ETH Coinbase USD spot on 2026-10-24. Use this
contract for spot research. Keep existing binary reports separate;
[GEMINI_HANDOFF.md](GEMINI_HANDOFF.md) remains their contract. Reuse the existing
nightly Gemini job; no new scheduled job was created.

## Publish a separate JSON report

Write a JSON object without Markdown fences to
`trading/reports/gemini_spot_latest.json` on the runner machine. Write an immutable
`trading/reports/<report_id>.json` archive first, then atomically replace latest.
An optional Markdown explanation is welcome. Delivery into Baymax's guest still
needs wiring; no current report has been fabricated.

Retain the schema-1 report envelope, with these required fields:

- `schema_version`: integer 1; `source`: `gemini`.
- `report_id`: unique immutable nonempty string.
- `strategy`: `coinbase_spot_15m`.
- `strategy_config_hash`: exact output from
  `python3 -m trading.spot_runner --print-config-hash` for the evaluated config.
- `model_version`: actual evaluated checkpoint matching `spot_config.json`.
- `horizon_seconds`: 900.
- `trading_date`: current Pacific calendar date, `YYYY-MM-DD`.
- `analyzed_date`: previous Pacific calendar date.
- `generated_at`, `expires_at`: timezone-aware ISO timestamps. Generate on the
  trading date, with age/lifetime within the configured 26-hour maximum.
- `assets`: BTC/ETH objects with boolean `trade_allowed`, nonempty `regime`, and
  a specific nonempty `reason`.
- `weight_update`: boolean `recommended` and a nonempty `reason`; include candidate
  identity/evidence when proposing a change. Never activate weights in this job.

If terminal midpoint/return forecasts, execution-cost history, current data, or a
matching evaluation are unavailable, set `trade_allowed: false` and explain the
gap. Do not fabricate approvals, trades, performance, or confidence. Binary
directional accuracy and Brier score alone do not show profitable spot trading.

## Evaluate the actual spot policy

Read [SPOT_PAPER.md](SPOT_PAPER.md) and `spot_config.json`. Evaluate the long/cash
policy, fee-inclusive $100 entry, $1,000 shared cash, UTC-quarter-hour timed exit,
one position per asset, freshness checks, and deferred exits. Positive predicted
net return after costs is the user-approved paper research baseline; the old
binary 50% ROI rule does not apply.

The account fee check on 2026-10-24 returned a 0.009 taker rate per side. Configured
spread/slippage buffers are research assumptions. Refresh account fee evidence
when possible, evaluate larger costs, and propose changes rather than silently
editing the config. Candles do not establish executable historical depth or
spread. Simulated fills must remain separate from any real account activity.

Use chronological training/calibration/held-out splits, prevent overlapping-window
leakage, freeze forward rules, and distinguish fitted, untouched, and forward
paper results. Report:

- Expected/evaluated windows, coverage, missing inputs, and no-trade frequency.
- Terminal price/return errors and uncertainty calibration where available.
- Closed versus still-open positions, gross/net P&L, fee totals, capital/return
  definition, drawdown, and turnover.
- Matched-date/capital comparisons against stay-in-cash and buy-and-hold baselines.
- Asset/regime sample sizes, day/block uncertainty, dependence, and sensitivity
  to fees, spread, slippage, execution delay, and the entry threshold.
- Input provenance, checkpoint identity, exact config hash, and time boundaries.

Use nulls with explanations for missing values. Extra research evidence is stored
but is not independently statistically verified by the parser. Model/threshold
recommendations are advisory. Additional market candidates remain research-only;
they cannot expand the BTC/ETH allowlist automatically.
