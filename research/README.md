# Trading research and team notes

This directory is the shared repository location for trading research, experiment notes, methodology, data snapshots and reproducible analysis scripts. Add future research here and update this index. Do not rely on chat history or an external Codex workspace as the only record.

**Current recommendation:** [BTC trend-following strategy decision — November 19, 2026](STRATEGY_DECISION.md). Frozen signal specification, evidence, sizing proposal and validation gates; paper evaluation recommended, live allocation zero.

## Coinbase competition

The [competition research folder](coinbase-competition/) contains the November 2026 research migrated into this repo on November 18, 2026:

| Research | Report | Supporting artifacts |
| --- | --- | --- |
| Competition overview and constraints | [Research notes](coinbase-competition/coinbase-competition-research.md) | Historical notes; verify current terms before using |
| Kronos forecast evaluation | [Experiment 1](coinbase-competition/kronos-competition-experiment-1.md) | [Colab notebook](https://colab.research.google.com/drive/1JWG-M7JL5DDYbNm2G9bfKI3ISaCJ1ffK) |
| Six-asset, 24-rule screen | [Alternative strategies](coinbase-competition/coinbase-alt-strategy-report.md) | [Candles](coinbase-competition/coinbase-alt-futures-input.json), [scores](coinbase-competition/coinbase-alt-strategy-results.json) |
| XRP refinement, 21 configurations | [Refinement report](coinbase-competition/xrp-refinement-report.md) | [Script](coinbase-competition/refine_xrp_strategy.py), [results](coinbase-competition/xrp-refinement-results.json) |
| Funding and dated-futures carry | [Carry screen](coinbase-competition/coinbase-carry-research.md) | [Snapshot](coinbase-competition/coinbase-carry-snapshot.json) |
| Public competition leaders | [Leader analysis](coinbase-competition/competition-leader-analysis.md) | Public leaderboard evidence only |

The experiments have **not established a deployable profitable edge**. XRP refinement reduced the diagnostic loss, but the diagnostic period had already been inspected. Carry was a snapshot fee screen, not a historical funding backtest. Reports preserve their original observation dates; migration does not make those market observations current.

Reproduce the XRP refinement from the repo root:

```sh
python3 research/coinbase-competition/refine_xrp_strategy.py
```

The script uses the Python standard library and writes results beside itself. No GPU is needed for that rule-based calculation. This does not retrain Kronos model weights.

## Existing implementation and operational documentation

- [Hyperliquid vault strategies: source review and test plan](vault-strategies.md) — Astraeus trend/volume/variance sizing and 0xArchive averaging-down strategy; reviewed November 18, 2026. Initial hypotheses and source caveats; replay linked below.
- [Coinbase competition replay of both vault strategies](vault-competition-report.md) — November 18, 2026 run; futures data, source-inspired rules, benchmark, fee/funding sensitivity, intrabar-path scenarios and tail stress. Retrospective paper research only.

- [Trading implementation and overview](../trading/README.md)
- [Trading status](../trading/TRADING_STATUS.md)
- [Gemini researcher handoff](../trading/GEMINI_HANDOFF.md)
- [Gemini spot research handoff](../trading/GEMINI_SPOT_HANDOFF.md)
- [Spot paper runner](../trading/SPOT_PAPER.md)

Keep market observations dated, distinguish fitted and evaluation data, record fees and missing inputs, and retain negative results. Store credentials outside versioned research files.
