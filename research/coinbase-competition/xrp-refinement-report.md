# XRP strategy refinement — November 5, 2026

Research candidate: XRP US perpetual-style futures (XPP-20DEC30-CDE), selected because it led the prior validation screen. Its prior later-period result was negative; this does not establish that XRP has the highest true edge. BTC had the least-negative funding-carry screen, but neither BTC nor ETH carry covered fees.

## Method

Compared 21 explicit configurations: 10/20/40-day breakouts, 1/3/5-day holding periods, with/without a 60-day direction filter (18), plus three breakout/momentum weighted combinations (breakout weights 25%, 50%, 75%, momentum gets the remainder). Blended signals trade only when score reaches +/-0.5. Signals use completed candles; entry is next daily open; exit is the scheduled day's close. No foundation-model weights were changed or claimed to be trained.

Parameters ranked on three successive 40-day development blocks, 2026-05-09 through 2026-09-05. Score is mean block return less half the worst block drawdown. Gate requires at least six trades across development and positive returns in every development block. Those requirements were set before this refinement run. All configurations are recorded, including failures.

Locked candidate: `{"breakout_weight": 1.0, "hold_days": 1, "lookback": 10, "trend_filter": false}`.

Development gate: **PASS**. Highest development score: 7.78.

The following later period, 2026-09-06 through 2026-11-04, was already inspected in the previous asset screen. It is reused only as an exploratory diagnostic, not a fresh holdout. Asset selection and repeated research create selection bias even though this run's parameters use earlier blocks.

| Diagnostic strategy | Net return on initial notional | Maximum daily-close drawdown | Trades | Active days |
| --- | ---: | ---: | ---: | ---: |
| Original 20-day breakout, 1-day holds, revised cost model | -1.45% | 2.02% | 3 | 3 |
| Development-selected refinement | -0.27% | 3.36% | 5 | 5 |
| Refinement with double execution/funding assumptions | -1.72% | 3.96% | 5 | 5 |

Returns use fixed initial notional, no leverage, no reinvestment and cash PnL marked daily, including overnight moves during longer holds. Every block begins and ends flat. Per-fill assumed execution cost is 0.12% (0.24% round trip), plus adverse funding of 0.05% per active calendar day. Stress doubles both. These are conservative research scenarios, not measured historical funding or complete account-specific charges. This accounting and funding assumption differ from the earlier compounded, funding-free screen; compare the rows above on the same basis.

The selected rule's descriptive five-day block-bootstrap 95% interval for the reused diagnostic return is [-7.54%, +7.21%]. It ignores parameter/asset selection and cannot certify profitability. 5 trades is a limited sample.

## Decision and next test

**Paper only.** A profitable reused diagnostic cannot authorize live promotion. Freeze this configuration rather than selecting another variant after seeing the diagnostic. Collect subsequent unseen quotes and funding, simulate executable entry/exit prices, and report economic net PnL and collateral needs. Require sufficient independent trades, positive results under stressed costs, and no unresolved margin/contract eligibility issues before considering live use.

At 1x initial notional, multiplying a reported percentage by $1,000 gives hypothetical PnL for $1,000 notional; the user's $1,000 maximum-loss constraint is not account equity and does not set a live position size. Drawdowns here are daily close only and do not capture intraday losses, integer contract sizing, liquidation or leg/execution effects.

Data: existing Coinbase FUTURE daily candles, 2026-01-09 to 2026-11-04. Provider returned 300 bars. Historical contract eligibility, actual historical funding and detailed fills remain unverified. No new out-of-sample period was acquired. No orders submitted.

Reproduce: `python3 refine_xrp_strategy.py`. Raw configuration scores and results: `xrp-refinement-results.json`. Arithmetic runs locally; this small daily-bar test needs no GPU.
