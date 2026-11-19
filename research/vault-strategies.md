# Hyperliquid vault reconstruction ideas

Reviewed November 18, 2026. Sources read directly in the browser. These are third-party research claims, not independently reproduced performance. No orders or model-weight changes.

## Astraeus: trend following and risk-based sizing

[Source: Astraeus, November 17, 2026](https://x.com/astraeuscap/status/2122868247972180231)

The author approximates the BTC-only +convexity vault using hourly inputs and a daily rebalance around 01:45 UTC:

```text
trend = log(EMA_48h(price) / EMA_480h(price))
participation = volume_24h / average_daily_volume_30d
variance = 8760 * EWMA_336h(hourly_log_return_squared)
target_exposure = scale * trend * participation / variance
new_exposure = previous_exposure + 0.8 * (target_exposure - previous_exposure)
```

The scale factor remains unspecified. The author reports incomplete sizing reconstruction, a substantial performance gap during February, and an alternative funding filter that is not established as the vault's actual rule. A second strategy ranks assets by score, applies inverse-volatility weights, and combines that cross-sectional sleeve with BTC exposure. The reported combined gross Sharpe is approximately 1.63; funding, costs and execution need independent verification.

Important source inconsistency: a caption says doubling variance quarters position size. Under the stated inverse-variance formula, doubling variance halves position size; doubling volatility quarters it. Use the formula and verify conventions rather than copying that caption.

## 0xArchive: averaging down with escalating exposure

[Source: 0xArchive, November 6, 2026](https://x.com/0xarchiveio/status/2118753234856943724)

The post claims a 99.3% trade win rate and describes entry about 0.8% below a 14-hour EMA. Further entries occur at drawdowns of approximately 2.25%, 3.5%, 5%, 7% and 9.8% relative to the initial entry. Each addition roughly matches existing size, and the strategy exits slightly above average entry without a stop. The author reports reconstructed daily-return correlation of 0.81 with the vault. Neither that correlation nor trade win rate establishes profitable future returns.

## Assessment for our project

Prioritize the trend-following hypothesis for testing. It changes both signal construction and risk sizing, rather than merely searching more breakout parameters on our already inspected XRP data. It remains unproven. It can lose repeatedly in sideways markets and inverse-variance sizing can create excessive exposure after quiet periods.

Treat the averaging-down hypothesis as a tail-risk stress benchmark, not a live deployment candidate. If size exactly doubles after each of five additions, exposure grows from 1 to 2, 4, 8, 16 and 32 times the starting quantity. That is a mechanical illustration, not a verified reconstruction of the vault. Frequent small realized wins can coexist with a large open loss or liquidation. The starting order size must therefore not be confused with maximum committed capital or maximum loss.

## Reproducible test specification

1. Acquire timestamped hourly BTC prices and volumes, actual venue funding, execution costs and contract terms. Include a warm-up beyond the longest estimator. Clarify whether EMA/EWMA parameters mean span, half-life or another decay convention; the post does not fully resolve this.
2. Compute indicators only from completed bars. At a 01:45 UTC decision use information available then, not the future 02:00 hourly close. Model delayed executions, turnover, fees, funding, and marked equity between rebalances.
3. Fix one baseline before examining new returns. Select any scale factor using development data only. For the first research baseline cap absolute exposure at 1x, specify a variance floor and participation cap, and record these as our modifications rather than exact replication.
4. Compare trend alone, trend plus participation, inverse-volatility sizing and inverse-variance sizing under identical costs and exposure caps. Add the 80% adjustment as a separate ablation. Defer the funding gate until historical funding is available.
5. Treat cross-sectional ranking as a separate experiment. It needs historical eligible universes, delisted assets, liquidity constraints and accurate funding; a current six-asset catalog is not a replication of the author's universe.
6. For averaging down, account for every simultaneous position and addition, available collateral, intrabar adverse moves, fees, funding, and liquidation. Daily candles cannot reliably establish the ordering of entry, addition and exit events. Include unrecovered open positions in terminal PnL.
7. Report net PnL, drawdown, turnover, maximum exposure, collateral demand, trade counts and dependence on the largest winning/losing days. Freeze parameters and then evaluate on newly acquired untouched periods or a forward paper run. The earlier XRP diagnostic is not a fresh holdout.

Initial research status at source review: neither strategy had been tested. Subsequently, [both were replayed using Coinbase futures data](vault-competition-report.md), with explicit adaptations and limitations. Neither post alone justifies live promotion. Competition availability, venue eligibility and account-specific costs must be verified separately.
