# Coinbase futures competition: two vault-inspired strategy tests

Run November 18, 2026 (Pacific). Historical replay only; no live orders, automated deployment, competition registration or account balance assumption.

## Comparison

Tested Coinbase US BTC perpetual-style futures `BIP-20DEC30-CDE`, November 4 at 00:00 UTC through November 19 at 01:30 UTC (November 18 at 17:30 Pacific). Each scenario starts independently with **$10,000 hypothetical equity**. This is not the user's actual balance, a funding request or an approved position size.

The central scenario charges the currently returned maker/taker rates, a 2-basis-point execution buffer per fill, and an adverse **5-basis-point funding charge per held day**. Funding is an assumption, not observed historical funding. End-of-window inventory is closed and its PnL included.

| Strategy | Return on hypothetical starting equity | Net PnL | Maximum modeled drawdown |
| --- | ---: | ---: | ---: |
| Astraeus inverse-variance baseline | +17.93% | +$1,792.72 | $813.52 |
| Simple fixed-contract short BTC benchmark | +16.89% | +$1,689.43 | $672.59 |
| Simple fixed-contract long BTC benchmark | -18.59% | -$1,858.97 | $2,370.63 |
| Archive source-like averaging down, low-before-high path | +0.43% | +$43.21 | $588.23 |
| Archive source-like averaging down, high-before-low path | +0.27% | +$27.46 | $588.74 |
| Archive with exposure/loss controls, low-before-high | -6.36% | -$636.29 | $697.94 |
| Archive with exposure/loss controls, high-before-low | -10.21% | -$1,021.32 | $1,032.74 |

Both Archive rows above use a 0.3% price-profit target. The supplied post does not specify the target; 0.1% and 0.5% were also evaluated and retained in the JSON, without picking the most profitable after inspection. A price-profitable exit can lose after costs. The two OHLC paths are alternative scenarios, not rigorous upper/lower bounds on all possible tick paths.

The trend strategy's result is largely explained by a falling BTC market. Its roughly one percentage point advantage over the passive short is not enough evidence of a durable timing edge. The source-like averaging strategy reached approximately $20,443 notional and $4,298 overnight margin proxy despite starting with one 0.01-BTC contract. Imposing a 1x entry exposure cap changes its ability to recover losing inventory; those controlled versions are explicitly different strategies.

## Funding and tail sensitivity

| Assumed adverse funding per held day | Trend baseline return | Archive source-like return across the two paths |
| --- | ---: | ---: |
| 0 bps | +19.12% | +0.43% to +0.49% |
| 5 bps | +17.93% | +0.27% to +0.43% |
| 10 bps | +17.28% | +0.12% to +0.37% |

Funding affects subsequent equity-dependent sizing, so return differences are not simply the final funding debit divided by starting capital.

A separate synthetic **30% one-day decline** lost approximately **$4,907.71** for the source-like averaging strategy. The controlled variant lost approximately **$1,018.04**, including exit costs and bar-level overshoot. Neither is a historical outcome. These scenarios show why a stated $1,000 risk budget is not a guaranteed maximum loss and why a high historical trade win rate does not resolve tail risk.

## Implementation choices fixed before reading these returns

- BTC-only adaptations; no attempt to reproduce the Astraeus cross-sectional sleeve or undisclosed vault sizing multiplier.
- Trend inputs: hourly EMA spans 48 and 480; hourly squared log returns with EWMA span 336, annualized by 8,760; trailing 24-hour volume divided by trailing 30-day average daily volume. Floors annualized volatility at 10% and caps the volume multiplier at 3.
- Each trend scale factor makes median absolute raw exposure 0.5 on September 2026 data only, after August warm-up. It is not fitted to competition returns. EMA span is our explicit convention because the source does not fully specify decay conventions.
- Daily trend rebalance at 01:45 UTC using only already completed hourly bars, moving 80% toward a target clipped to +/-1x current research equity. Round toward zero to integer 0.01-BTC contracts. The cap applies at rebalance; exposure can drift above it between rebalances. Four signal/sizing ablations are reported in full, not silently substituted for the published inverse-variance baseline.
- Averaging rule: long-only, one micro contract initially, resting entry 0.8% below the completed-hour 14-hour EMA, additions at 2.25/3.5/5/7/9.8% below the first fill, each matching current contract count. Fixed profit targets of 0.1/0.3/0.5% over average entry. Buy limits rounded down and sell limits up to $5 ticks.
- Limits receive modeled touch fills with gap repricing. No more than one new cycle starts in a bar. This does not establish queue position, available depth or actual fill probability. Trend changes and forced exits use taker assumptions. Historical funding credits are not assumed for shorts.
- The controlled averaging variant blocks additions exceeding 1x current equity at the proposed execution, exits after the $1,000 initial-equity loss threshold is observed, and then stops. The source-like version has no discretionary stop, but exits on a modeled margin-proxy breach. These are not exchange liquidation or guaranteed stop simulations.

## Data and cost limits

Raw Coinbase MCP FUTURE candles are saved with request windows and the fee response summary. Earlier hourly requests start August 1; competition candles are 15-minute. Eight absent competition bars occur in two one-hour gaps. They receive no invented fills; elapsed time is charged on the next observed bar. Missing warm-up hours carry the previous close with zero volume for indicator timing. These conventions and session gaps can affect signals.

Current futures fee rates returned by the connector are 0.095% maker and 0.10% taker per side. It also flags cost-plus commission, so these may omit additional charges. The 2-basis-point buffer is a research assumption, not proof it covers every charge. The overnight margin proxies use the current snapshot, 21.025% long and 25.6625% short; historical rules, maintenance margin, collateral haircuts and liquidation mechanics are not available in this replay.

Marked PnL includes price movement between successive bars, execution debits, estimated funding drag and final liquidation. Intrabar margin checks use a simplified equity/margin comparison. Funding drag uses end-of-bar held notional and elapsed calendar time; it is not exact hourly settlement and can understate charges for positions opened and closed within a bar. Extrema-based drawdown is a bar-path estimate, not verified tick-level drawdown. No Sharpe or competition-winning probability is inferred from about 15 days.

## Independence and competition interpretation

The Astraeus article was published November 17 and describes research using data through November 2026. Replaying November 4 onward is therefore **retrospective** and potentially overlaps its development data. A separate flat-start slice from November 18 00:00 UTC to November 19 01:30 UTC returned +$193.34 for the trend baseline and about -$5.63 for source-like averaging under the central assumptions. That one-day slice is too short and too retrospective to validate an edge.

[Official competition terms](https://www.coinbase.com/legal/global-trading-comp-terms) currently describe a November 25, 2026 end date. US participation uses designated CFM futures in the competition account; actual contract eligibility, account approval and registration remain to be verified. Simulated historical gains do not count toward a leaderboard, and prior-to-registration activity is not retroactively credited. No live activity was submitted.

## Decision

**Advance the frozen inverse-variance trend baseline to a forward paper evaluation, not a live allocation.** Keep the averaging strategy as a separate paper/stress benchmark; the source-like version does not fit a dependable $1,000 maximum-loss requirement. Do not choose a larger exposure or a different profit target to improve this already observed test. A genuine forward sample and measured costs/funding are needed before any live decision.

## Artifacts and verification

- [Source review and hypotheses](vault-strategies.md)
- [Raw Coinbase inputs](vault-competition-input.json)
- [Simulation script](test_vault_competition.py)
- [All 54 configuration/cost scenarios, partial-day replay and synthetic stress](vault-competition-results.json)
- [Marked equity paths for central scenarios](vault-competition-equity.csv)
- [Accounting and timing checks](test_vault_accounting.py)

Reproduce from repository root:

```sh
python3 research/test_vault_competition.py
python3 -m unittest discover -s research -p 'test_vault_accounting.py'
```

Five checks pass: futures cash/fees reconcile, funding debit arithmetic, future indicator exclusion, terminal underwater inventory inclusion, and a price winner losing after fees. This is a lightweight standard-library simulation; no GPU or Kronos weight training is involved.
