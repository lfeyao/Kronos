# Alternative futures strategy screen — November 5, 2026

Tested SOL, XRP, BCH, LTC, LINK and AVAX US perpetual-style futures histories
returned by Coinbase FUTURE candles. Each history has 300 unique consecutive
daily candles, Jan 9–Nov 3, 2026; the provider truncated the requested year.
Data: [input](coinbase-alt-futures-input.json). Full scores:
[results](coinbase-alt-strategy-results.json).

Four fixed rules per asset, 24 comparisons: sign of 5-day vs 20-day mean;
sign of five-day return; breakout above prior 20-day high/below prior low;
and contrarian direction when close is over 1.5 population standard deviations
from the trailing 20-close mean. Every signal uses data available at that
close. Hypothetical entry next daily open, exit same-day close, 1x notional,
flat between sessions. Charge 0.24% round-trip per active day; stress at 0.48%.
Mean-reversion uses current completed close in its statistics; breakout excludes
that candle from the prior range. Fixed parameters, no parameter fitting.

First 180 observations provide development/context; days 180–239 rank candidates;
last 60 are a later holdout. Select exactly one winner on validation, compare
with flat. This is 24 trials in addition to prior research, not an independent
discovery free of selection bias. Assets selected from today's catalog create
survivorship/availability bias; historical eligibility is unverified.

| Validation rank | Rule | Validation return | Holdout return | Holdout active days |
| --- | --- | ---: | ---: | ---: |
| 1 | XRP breakout20 | +28.64% | -1.34% | 3 |
| 2 | BCH breakout20 | +23.12% | -4.77% | 2 |
| 3 | SOL trend5/20 | +14.49% | -15.68% | 60 |
| 4 | SOL momentum5 | +13.89% | -20.05% | 60 |

The selected XRP rule loses 2.05% on holdout at double assumed costs. Its three
holdout trades are far too few to support an edge estimate. Raw JSON's selected
field denotes validation selection, not deployment approval. Other holdout
results are diagnostic only: do not replace the selected rule with a holdout
winner. The holdout has now been inspected and is not fresh for future tuning.

This is an approximate screen, not an executable broker backtest: missing
historical funding, spreads, limit fill probability, slippage, intraday margin,
liquidations, integer contracts and account-specific all-in charges. Fees are an
assumption. No leverage used, no inference of winning odds, no competition
registration or trade eligibility established. Results are portfolio fractions,
not a guarantee on the $1,000 maximum-loss objective.

Arithmetic was run locally after Colab's upload integration failed; no GPU
inference was needed. A summary is saved in the Colab competition notebook.
Outcome: reject live promotion from this screen. Funding/basis carry and
longer-horizon portfolio signals require different data and genuinely fresh
evaluation; they remain untested rather than presumed profitable.
