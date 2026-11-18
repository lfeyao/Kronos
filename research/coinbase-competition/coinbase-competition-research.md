# Coinbase Champions Cup: strategy research

November 5, 2026. Research proposal; no winning strategy, competition entry,
trading eligibility, orders, or positive expected returns established.

## Objective and scoring

Focus on the percentage-P&L leaderboard for a modest account. Actual prize
probability needs the current distribution and final cutoff; neither is available
from the public page snapshot. Dollar P&L is capital intensive. Do not create
turnover to chase volume; Coinbase prohibits abusive churning and US participants
cannot enter the volume leaderboard.

Coinbase's [official terms](https://www.coinbase.com/legal/global-trading-comp-terms)
specify adjusted P&L / capital base, a $100 minimum denominator, a single
designated competition account, and qualifying activity after registration.
Deposits and rewards increase the denominator; withdrawals do not reduce it.
Jurisdiction, product access and physical location remain unconfirmed.

## Candidate hypothesis: BTC/ETH breakout with volatility filter

Evaluate a directional breakout, long or short, only in genuinely eligible
products. At each completed hourly candle, compare close to the previous 24
completed hourly highs/lows (exclude current candle). Break above/below enters
in that direction only when 24-hour realized range is neither exceptionally low
nor above a predefined stress threshold, and expected move exceeds estimated
round-trip spread, fees, slippage and funding. Exact stress threshold and
expected-move model must be fixed on training data, not tuned on competition
results. Otherwise flat. Execute at next bar with conservative bid/ask and
slippage; maker-only assumed fills require order-book evidence, not a touch.

Exit after 24 hours, on a prior-defined volatility-scaled protective threshold,
or when the opposite signal appears, whichever occurs first. Intrabar stop
breaches with candle OHLC should use conservative adverse ordering, and stops
cannot guarantee execution. Avoid adding to losers. One position at a time;
no order or automated execution is authorized by this research document.

Compare with always-flat, buy-and-hold, and a simple 24-hour momentum benchmark.
Kronos may be an additional signal only after independently reproducible live-like
forecasts exist; do not treat its paper runner or model outputs as proven edge.

## Testing required before estimating odds of winning

1. Verify current leaderboard percentile cutoff and scoring; evaluate 21-day
   forward windows, not just average trade win rate. The prior public snapshot
   did not expose the percent leaderboard cutoff.
2. Gather at least 12 months of eligible BTC/ETH contract prices, mark/index
   prices, spreads, historical funding and relevant event timestamps. Build
   continuous point-in-time data, account for contract changes and missing bars.
   Spot is only a proxy, not a substitute for perpetual fills or funding.
3. Split chronologically into train, validation, and untouched out-of-sample;
   run rolling walk-forward tests with no lookahead, a small predeclared parameter
   grid, and multiple-testing adjustment. Reserve the competition window for
   forward evidence; no parameter optimization on the evaluation segment.
4. Model observed maker/taker fees, partial fills, slippage, funding, exchange
   constraints, maintenance margin and liquidation gaps. Use the fees for the
   actual jurisdiction and product; Coinbase's observed FUTURE rates do not
   establish international perpetual fees.
5. Report distributions of net 21-day return, probability of crossing multiple
   candidate leaderboard cutoffs, maximum drawdown, liquidation probability,
   missed fills, coverage and confidence intervals across market regimes.
   Sensitize fees, funding and slippage; compare positive evidence against flat.
   Overlapping windows are dependent; do not claim independent samples.
6. Paper trade forward first and compare actual timestamps/quotes/fills against
   simulation. Define total loss and notional limits from user input; stop rules
   do not guarantee a maximum loss. Contest return is not investment edge.

## Evidence collected so far

- Coinbase lists BTC-PERPETUAL and BTC_USDC-PERPETUAL, but this only verifies
  product visibility, not account access or competition eligibility.
- A test spot query returned 60 hourly BTC-USD candles, Nov 3 08:00 to Nov 5
  19:00 UTC: $76,497.70 to $75,935.14, down ~0.74%; hourly closing-price range
  ~6.38% of the minimum. These are spot prices and are far too little data for
  a backtest, profitability claim or estimate of winning probability.
- Coinbase returned Intro FUTURE fee rates maker 0.095%, taker 0.10%, with
  cost-plus indicated. These are US FUTURE product rates, not a verified
  all-in cost for the eligible international perpetual market.
- Starting capital, total loss limit, residence/current location, registration,
  competition-account access and the live percent leaderboard remain unknown.

Outcome: no validated contest-winning strategy and no justified live trade yet.

## November 5: US and $1,000 loss budget update

The user reports United States and accepts a $1,000 maximum competition loss.
Starting capital and designated competition account are not established. A
loss budget is an objective, not a guarantee: futures stops, gaps, liquidation,
fees and liabilities can lead to greater losses. Confirm actual eligible
products and account access before any order.

The unfiltered US FUTURE catalog returned nano BTC perpetual-style
`BIP-20DEC30-CDE` (0.01 BTC per contract, reference ~$759.50 notional) and
nano ETH perpetual-style `ETP-20DEC30-CDE` (0.1 ETH, ~$224.85 notional).
The catalog's expiry flag for the long-dated BIP listing is EXPIRING although
Coinbase describes this as perpetual-style; verify classification, eligibility
and funding terms with Coinbase. Listing alone does not prove the competition
designates these products. See [contract specifications](https://help.coinbase.com/en/derivatives/perpetual-style-futures/contract-specifications).

### Preliminary data check, not a validated trading system

Coinbase supplied 299 completed daily futures candles per contract, Jan 10–Nov 4
2026; a one-year query was truncated to 300 returned observations. A deliberately
simple diagnostic uses a close beyond the prior 24 daily highs/lows as signal,
enters next daily open in that direction, exits that day's close, otherwise stays
flat, and compounds hypothetical 1x daily notional returns. Charge an assumed
0.10% of notional on entry and 0.10% on exit per signal. This is a different,
daily simplification of the proposed hourly strategy; no hourly strategy was
tested. Results: BTC 20 signals and +6.20%; ETH 16 signals and -18.42%.

These are in-sample exploratory calculations, not a realistic futures-account
backtest: no funding, observed executable bid/ask, spread, market impact, margin,
actual per-contract fees, fills, or liquidation; exact next-bar open fills are
optimistic. The 0.10% assumption is illustrative, not a verified complete fee.
Results are sensitive to start date and signal definition, and there is no
out-of-sample comparison, 21-day distribution, leaderboard cutoff, or estimate
of winning probability. No trading edge is established.
