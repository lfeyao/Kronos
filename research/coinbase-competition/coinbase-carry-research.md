# Coinbase funding and basis carry screen

Snapshot: November 5, 2026, approximately 20:02 UTC. Research only; no orders placed.

## Result

BTC and ETH spot/futures carry fail the initial fee screen over an illustrative 20-day competition holding period. This is a current-quote economic screen, not a completed historical funding backtest or a forecast of funding rates.

Account-specific Coinbase MCP fee responses report spot maker/taker rates of 0.50%/0.90% per side and futures maker/taker rates of 0.095%/0.10% per side. A matched spot/futures round trip therefore costs approximately 1.19% with all maker fills or 2.00% with all taker fills, measured against one leg's notional. Futures responses flag cost-plus commission; additional charges must be checked before treating these figures as all-in costs. Maker fills are not assured, and obtaining one leg without the other creates price exposure.

## Long spot, short perpetual-style futures

Positive funding is received by the short leg. The table assumes the observed hourly funding rate persists for 480 hours and excludes changes in futures/spot basis, spread, slippage and additional charges.

| Asset | US futures contract | Hourly funding | Gross funding over 20 days | Approximate maker round-trip fees | Funding less those fees |
| --- | --- | ---: | ---: | ---: | ---: |
| BTC | BIP-20DEC30-CDE | 0.0018% | 0.864% | 1.190% | -0.326% |
| ETH | ETP-20DEC30-CDE | 0.0010% | 0.480% | 1.190% | -0.710% |

At unchanged rates, fee-only break-even takes about 27.5 days for BTC and 49.6 days for ETH. The entry futures premium is approximately 0.029% for BTC and 0.025% for ETH; even full capture would not close these fee shortfalls. Perpetual-style futures do not guarantee basis convergence on the competition exit date. Funding can fall or turn negative.

These percentages use matched notional, not total capital. Spot acquisition and futures margin both consume capital, so return on total deployed capital differs.

## Long spot, short November 27 dated futures

Executable top-of-book prices were used to screen entry: buy spot at ask and sell futures at bid. BTC's first spot ask level is smaller than one 0.01 BTC futures contract; an actual simulation must walk the order book. The next ask is $76,128.30, so this snapshot's top-level approximation has a negligible but optimistic difference.

| Asset | Spot ask | Dated futures bid | Entry premium over spot | Contract multiplier | Gross convergence per contract |
| --- | ---: | ---: | ---: | ---: | ---: |
| BTC | $76,128.26 | $76,510.00 | 0.5014% | 0.01 BTC | $3.8174 |
| ETH | $2,254.43 | $2,261.50 | 0.3136% | 0.1 ETH | $0.7070 |

Both premiums are below the approximate 1.19% maker round-trip hurdle. The November 27 settlement is also after the competition ends on November 25, so full convergence cannot be assumed within the competition. Exact settlement reference, exit prices and expiry-specific fees must be modeled rather than assuming an arbitrage payoff.

Indicative spot purchase plus dated-short overnight margin is approximately $955 for one BTC contract or $293 for one ETH contract, before fees and any liquidity buffer. These are not maximum-loss figures. A rise in the underlying can demand cash on the short futures leg even when the spot leg has an offsetting gain, particularly when collateral is held separately.

## Competition scoring

Section 4.4 of the official terms says US CFM competition equity includes USD/USDC balances and unrealized futures PnL, less liabilities; spot trades and other asset value changes do not affect US competition PnL. Thus an economically hedged spot/futures position leaves the futures price exposure visible in the leaderboard score without its spot offset.

A futures-only calendar spread is a separate candidate, subject to confirming that both exact contracts are eligible. It must model funding on the perpetual leg, changes in the calendar spread, four executions, and margin treatment. No profitable calendar-spread result has been established here.

## Historical test still required

The connected funding-history tool supports international GLOBAL_PERP products, not these US FUTURE contracts. International funding history must not be substituted for US funding. A credible US carry backtest needs:

1. Actual historical hourly funding for each US perpetual-style contract and synchronized futures/spot prices, preferably bid/ask and depth.
2. Contract multipliers, settlement reference and dates, fees including extra commissions, and historical margin rules.
3. Separate spot cash, futures collateral, funding cash flows and variation margin. Track maximum collateral demand, leg execution risk and forced close outcomes.
4. Entry and exit rules fixed before evaluation: minimum net carry, maximum holding time, funding reversal and basis-widening exits, and explicit liquidity reserves.
5. Economic PnL and competition-eligible PnL reported separately. Evaluate on untouched periods and stress lower/reversed funding, wider spreads, a 20% underlying move, and adverse basis changes.

The user's $1,000 maximum competition loss is a risk constraint, not an assumption that the account contains $1,000 or that a stop guarantees that loss cap. No live allocation is justified by this screen.

## Sources and raw calculations

- [Competition terms, including sections 2.1 and 4.4](https://www.coinbase.com/legal/global-trading-comp-terms)
- [US perpetual-style futures overview](https://help.coinbase.com/en/derivatives/perpetual-futures/overview)
- [Margin and clearing](https://help.coinbase.com/en/derivatives/perpetual-style-futures/margin-and-clearing)
- Connected Coinbase MCP account fee, product, funding snapshot and order-book responses, collected November 5, 2026.
- Machine-readable derived snapshot: `coinbase-carry-snapshot.json` in this directory.
