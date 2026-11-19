# Strategy decision: BTC trend following

Decision date: November 19, 2026. Owner: trading research team. Status: **frozen research specification; forward paper evaluation recommended; live allocation zero**. This document does not start a runner, register an account, submit orders or authorize another agent to trade.

## What I would do

Choose the BTC-only trend/volume/inverse-variance rule inspired by the Astraeus analysis. Keep its parameters fixed and evaluate subsequent unseen data with measured Coinbase futures costs. I would not allocate live capital for this competition on the evidence currently available. If the forward evaluation cannot finish before the competition ends, continue the research afterward rather than increase risk to chase the leaderboard.

Do not deploy the averaging-down rule: its source-like replay made only 0.27–0.43% while reaching about $20,443 exposure on $10,000 hypothetical starting equity, and a separate synthetic 30% decline lost about $4,908. Adding an exposure cap materially changed the strategy and produced losses in our replay. High trade win rate is not a sufficient selection criterion.

I would also keep the earlier XRP breakout and BTC/ETH spot-futures carry out of live deployment: their screens did not establish a profitable edge after costs. Use flat/cash as the alternative whenever data, sizing or validation requirements fail.

## Why this candidate, and how strong the evidence is

The selected trend baseline returned **17.93%** in the November 4–18 retrospective competition replay, versus **16.89%** for a fixed-contract short-BTC benchmark under the same central cost assumptions. Its modeled maximum drawdown was **$813.52**, versus **$672.59** for the benchmark. All figures use $10,000 hypothetical starting equity, not the user's account balance or a requested deposit.

The extra 1.03 percentage points came with greater drawdown. A declining BTC market explains much of the result; this does not establish superior risk-adjusted performance. Other ablations earned more in this same replay, but selecting one now solely for that reason would add selection bias. Retain the original inverse-variance candidate rather than switch to the best observed row.

The source was published November 17 and used data through November 2026. Most of this replay may overlap its discovery data. Actual historical US funding, all-in charges and executable limit-order fills remain missing. Treat the result as a hypothesis worth testing, not an independently verified edge or evidence we can win the competition.

## Frozen signal specification

Instrument for research: Coinbase US BTC perpetual-style futures `BIP-20DEC30-CDE`. The November 18 connector snapshot reports 0.01 BTC per contract and a $5 price tick. Revalidate the exact product, specification and account eligibility before any execution implementation.

Use completed hourly futures candles, hourly log returns, and EMA/EWMA **span**, with recursion coefficient `2 / (span + 1)`:

```text
trend = log(EMA_48(close) / EMA_480(close))
participation = min(3, sum(volume over 24 hours)
                       / (sum(volume over 720 hours) / 30))
annual_variance = max(8760 * EWMA_336(hourly_log_return^2), 0.10^2)
raw_target = 3.4217284836625144 * trend * participation / annual_variance
clipped_target = clip(raw_target, -1, +1)
weight_today = weight_yesterday + 0.8 * (clipped_target - weight_yesterday)
contracts_today = truncate_toward_zero(weight_today * current_paper_equity
                                      / (execution_price * 0.01))
```

The scale was calibrated using September 2026 only, to a median absolute raw target of 0.5; the saved August history supplies warm-up. Reproduce with the saved data and scale rather than recalibrating on the competition results. Start a forward paper account flat, with `weight_yesterday = 0`; do not inherit retrospectively earned equity or a hypothetical historical position.

Rebalance once daily at **01:45 UTC**, using the latest fully completed hourly candle available then. Do not use the 02:00 close. Carry the position until the next scheduled rebalance, except for separately defined risk exits. Round contract quantity toward zero; zero contracts means remain flat. The 1x cap applies at rebalance and does not prevent exposure drift between rebalances.

This rule can go long or short. An immediate rally after a downtrend can hurt an existing short before the slow signal changes. It is not an immediate bullish-BTC trade. Do not override direction because of a short-term price view, add an untested faster signal, or average down to recover a loss.

## Forward paper evaluation I would run next

Keep two independently accounted paper portfolios: the frozen trend baseline and the simple fixed-contract short benchmark. Include a long-BTC and flat reference for direction/regime attribution. Compare matched starting equity and account for realized plus unrealized PnL, all executions, funding and final inventory. No signal blending with Kronos until it has its own measured incremental value.

Record every completed input, decision time, target and actual simulated contracts, bid/ask, order attempt, fill or cancellation, fees, funding, marked equity, maximum exposure and collateral demand. Identify stale data and venue session gaps rather than silently inventing executable candles. Missing/stale data blocks additions and new entries; position risk monitoring continues. A paper runner and its monitoring still need to be implemented/deployed; these offline scripts are not a running forward service.

Use executable bid/ask costs for the conservative paper comparison. Separately simulate passive orders only when quotes and subsequent trades support a plausible fill. A touched candle is not proof of a passive fill. For a later execution design, a nonurgent entry can start as a post-only limit at the current tick-rounded midpoint and cancel after 60 seconds without automatically crossing. Partial fills must be reconciled. This execution policy was **not** validated by the existing taker-assumption trend replay.

Do not change parameters during the forward test. Before any live promotion, require at least 30 subsequent calendar days, at least 20 filled rebalance decisions, positive net performance under measured and stressed costs, and a comparison showing that results are not merely a permanent directional bet. These are research gates chosen now, not statistically sufficient proof. If the gates fail or the sample remains inconclusive, stay paper/flat; no automatic promotion on elapsed time.

## Risk and sizing policy for any later execution proposal

The user's **$1,000 maximum competition loss** is a risk budget, not an account balance or guaranteed stop. Current funded futures equity is not verified. The existing $10,000 simulation must not be translated directly into a live allocation.

If a later live pilot is justified, I would propose a maximum of **one micro contract**, no pyramiding, and a separate risk overlay. For a candidate quantity `q` BTC and fresh price `P`, require all of:

- Notional `abs(q) * P` no greater than 25% of verified futures equity.
- A 30% adverse-price stress plus expected round-trip charges no greater than $250.
- Overnight initial margin no greater than 25% of verified available futures collateral, with a separate liquidity reserve.
- Existing open orders and positions reconciled; competition registration and exact contract eligibility confirmed.

The minimum contract may fail these constraints; then trade zero. These pilot caps are a proposed modification, **not** the backtested 1x strategy and not authority to place a trade. Replay and paper-test the overlay separately before adoption.

For a later monitored pilot, propose stopping additions and closing exposure at a $500 peak-to-trough marked loss, or a $750 loss from initial pilot equity, whichever triggers first. Fees, funding and open losses count. Halt until reviewed, with no reset by restarting the process or depositing more cash. These earlier action thresholds leave room under the $1,000 budget, but gaps, slippage, outages and liquidation can exceed it. Broker-native risk orders and monitored cancellation/reconciliation need verification; do not call an application threshold a guaranteed maximum loss.

## Competition implications

[Coinbase's official terms](https://www.coinbase.com/legal/global-trading-comp-terms), checked November 19, describe the competition ending November 25, 2026 at 23:59 UTC. US users participate through designated CFM futures in their competition account. Registration, account access and contract eligibility must be verified; prior simulated returns never count toward the leaderboard. The remaining competition period cannot satisfy the forward-sample requirements above. My present recommendation is therefore **paper research, no new live competition position**.

## Team handoff and reproducibility

- [Detailed replay, assumptions and limitations](vault-competition-report.md)
- [All scenario results](vault-competition-results.json)
- [Raw futures candle requests and fee snapshot](vault-competition-input.json)
- [Simulation implementation](test_vault_competition.py)
- [Accounting checks](test_vault_accounting.py)
- [Source review](vault-strategies.md)

```sh
python3 research/test_vault_competition.py
python3 -m unittest discover -s research -p 'test_vault_accounting.py'
```

Research status: offline replay and five accounting/timing checks completed. Forward runner, measured historical funding, live account checks, execution adapter integration and pilot-risk overlay validation remain outstanding. No strategy daemon or new order was started for this decision.
