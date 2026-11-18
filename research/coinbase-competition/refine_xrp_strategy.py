"""Reproducible exploratory XRP strategy refinement; standard library only.

Not a broker simulator. No live trading or foundation-model weight changes.
"""
import datetime as dt
import itertools
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRODUCT = 'XPP-20DEC30-CDE'
data = json.loads((ROOT / 'coinbase-alt-futures-input.json').read_text())
bars = sorted(data[PRODUCT], key=lambda b: int(b['start']))
assert len({b['start'] for b in bars}) == len(bars) == 300
bars = [{k: float(v) for k, v in b.items()} for b in bars]
assert all(bars[i]['start'] - bars[i-1]['start'] == 86400 for i in range(1, len(bars)))


def direction(cfg, t):
    """Decision after close t; never uses a later bar."""
    n = cfg['lookback']
    if t < max(n, 60):
        return 0
    close = bars[t]['close']
    past = bars[t-n:t]
    breakout = 1 if close > max(b['high'] for b in past) else -1 if close < min(b['low'] for b in past) else 0
    momentum = 1 if close > bars[t-5]['close'] else -1 if close < bars[t-5]['close'] else 0
    w = cfg['breakout_weight']
    score = w * breakout + (1-w) * momentum
    signal = 1 if score >= 0.5 else -1 if score <= -0.5 else 0
    if cfg['trend_filter'] and signal:
        mean = sum(b['close'] for b in bars[t-59:t+1]) / 60
        if signal * (close - mean) <= 0:
            return 0
    return signal


def evaluate(cfg, start, end, fee=0.0012, funding_drag=0.0005):
    """Fresh flat start; fixed initial notional, no leverage or reinvestment.

    fee is per fill, includes assumed execution cost. Adverse funding drag per
    held calendar day, either direction; a stress assumption, not actual funding.
    Hold-one is next open through same-day close, matching previous baseline.
    Longer trades exit at the scheduled day's close; no signal-based early exit.
    """
    pnl, peak, dd, trades, active, exposure = 0., 1., 0., 0, 0, []
    side, entry, exit_day, previous = 0, None, None, None
    pnl_by_day = []
    for i in range(start, end):
        daily = 0.
        if not side:
            side = direction(cfg, i-1)
            if side:
                entry = bars[i]['open']
                previous = entry
                exit_day = min(i + cfg['hold_days'] - 1, end-1)
                daily -= fee
                trades += 1
        if side:
            active += 1
            daily += side * (bars[i]['close']-previous) / entry - funding_drag
            previous = bars[i]['close']
            exposure.append(side)
            if i == exit_day:
                daily -= fee * bars[i]['close'] / entry
                side = 0
        else:
            exposure.append(0)
        pnl += daily
        pnl_by_day.append(daily)
        peak = max(peak, 1+pnl)
        dd = max(dd, (peak - (1+pnl))/peak)
    return {'return_pct': 100*pnl, 'max_drawdown_pct': 100*dd,
            'trades': trades, 'active_days': active, 'daily_returns': pnl_by_day}


def compact(result):
    return {k: v for k, v in result.items() if k != 'daily_returns'}


configs = [dict(lookback=n, hold_days=h, trend_filter=f, breakout_weight=1.)
           for n, h, f in itertools.product((10, 20, 40), (1, 3, 5), (False, True))]
configs += [dict(lookback=20, hold_days=3, trend_filter=True, breakout_weight=w)
            for w in (0.25, 0.5, 0.75)]
assert len(configs) == 21
baseline = dict(lookback=20, hold_days=1, trend_filter=False, breakout_weight=1.)
folds = [(120, 160), (160, 200), (200, 240)]
ranked = []
for cfg in configs:
    fs = [compact(evaluate(cfg, a, b)) for a, b in folds]
    total_trades = sum(f['trades'] for f in fs)
    worst = min(f['return_pct'] for f in fs)
    # Penalize drawdown and uneven performance. Require enough observations.
    score = sum(f['return_pct'] for f in fs)/3 - 0.5*max(f['max_drawdown_pct'] for f in fs)
    passes = total_trades >= 6 and worst > 0
    ranked.append({'config': cfg, 'development_folds': fs, 'score': score,
                   'passes_development_gate': passes})
ranked.sort(key=lambda r: (r['passes_development_gate'], r['score']), reverse=True)
selected = ranked[0]
# Parameters locked using only indices <240 before evaluating the previously
# inspected diagnostic period. Prior asset selection still creates bias.
cfg = selected['config']
diagnostic = compact(evaluate(cfg, 240, 300))
stress = compact(evaluate(cfg, 240, 300, fee=0.0024, funding_drag=0.001))
baseline_diagnostic = compact(evaluate(baseline, 240, 300))

# Uncertainty diagnostic: fixed-seed circular block bootstrap of daily PnL.
# Not selection-adjusted; not independent confirmation of an edge.
import random
rng = random.Random(20261105)
returns = evaluate(cfg, 240, 300)['daily_returns']
samples = []
for _ in range(2000):
    sample = []
    while len(sample) < len(returns):
        j = rng.randrange(len(returns))
        sample.extend(returns[(j+k) % len(returns)] for k in range(5))
    samples.append(100*sum(sample[:len(returns)]))
samples.sort()
interval = [samples[49], samples[1949]]
result = dict(product=PRODUCT, candidate_reason='Best original validation candidate; no demonstrated edge',
              trial_count=21, historical_trials_before_this_run=24,
              cost_assumption=dict(per_fill=0.0012, adverse_funding_per_active_day=0.0005,
                                   stress_per_fill=0.0024, stress_funding_per_active_day=0.001),
              accounting='Fixed initial notional; additive cash PnL; 1x; flat at each evaluation boundary',
              development_folds=folds, ranked_development=ranked, selected=selected,
              diagnostic=diagnostic, baseline_diagnostic=baseline_diagnostic,
              double_cost_funding_stress=stress, descriptive_bootstrap_95_pct=interval,
              decision='PAPER ONLY; no fresh confirmation and incomplete broker/funding simulation')
(ROOT / 'xrp-refinement-results.json').write_text(json.dumps(result, indent=2)+'\n')

def stat(r):
    return f"{r['return_pct']:+.2f}% | {r['max_drawdown_pct']:.2f}% | {r['trades']} | {r['active_days']}"

date = lambda i: dt.datetime.fromtimestamp(bars[i]['start'], dt.timezone.utc).date().isoformat()
report = f'''# XRP strategy refinement — November 5, 2026

Research candidate: XRP US perpetual-style futures ({PRODUCT}), selected because it led the prior validation screen. Its prior later-period result was negative; this does not establish that XRP has the highest true edge. BTC had the least-negative funding-carry screen, but neither BTC nor ETH carry covered fees.

## Method

Compared 21 explicit configurations: 10/20/40-day breakouts, 1/3/5-day holding periods, with/without a 60-day direction filter (18), plus three breakout/momentum weighted combinations (breakout weights 25%, 50%, 75%, momentum gets the remainder). Blended signals trade only when score reaches +/-0.5. Signals use completed candles; entry is next daily open; exit is the scheduled day's close. No foundation-model weights were changed or claimed to be trained.

Parameters ranked on three successive 40-day development blocks, {date(120)} through {date(239)}. Score is mean block return less half the worst block drawdown. Gate requires at least six trades across development and positive returns in every development block. Those requirements were set before this refinement run. All configurations are recorded, including failures.

Locked candidate: `{json.dumps(cfg, sort_keys=True)}`.

Development gate: **{'PASS' if selected['passes_development_gate'] else 'FAIL'}**. Highest development score: {selected['score']:.2f}.

The following later period, {date(240)} through {date(299)}, was already inspected in the previous asset screen. It is reused only as an exploratory diagnostic, not a fresh holdout. Asset selection and repeated research create selection bias even though this run's parameters use earlier blocks.

| Diagnostic strategy | Net return on initial notional | Maximum daily-close drawdown | Trades | Active days |
| --- | ---: | ---: | ---: | ---: |
| Original 20-day breakout, 1-day holds, revised cost model | {stat(baseline_diagnostic)} |
| Development-selected refinement | {stat(diagnostic)} |
| Refinement with double execution/funding assumptions | {stat(stress)} |

Returns use fixed initial notional, no leverage, no reinvestment and cash PnL marked daily, including overnight moves during longer holds. Every block begins and ends flat. Per-fill assumed execution cost is 0.12% (0.24% round trip), plus adverse funding of 0.05% per active calendar day. Stress doubles both. These are conservative research scenarios, not measured historical funding or complete account-specific charges. This accounting and funding assumption differ from the earlier compounded, funding-free screen; compare the rows above on the same basis.

The selected rule's descriptive five-day block-bootstrap 95% interval for the reused diagnostic return is [{interval[0]:+.2f}%, {interval[1]:+.2f}%]. It ignores parameter/asset selection and cannot certify profitability. {diagnostic['trades']} trades is a limited sample.

## Decision and next test

**Paper only.** A profitable reused diagnostic cannot authorize live promotion. Freeze this configuration rather than selecting another variant after seeing the diagnostic. Collect subsequent unseen quotes and funding, simulate executable entry/exit prices, and report economic net PnL and collateral needs. Require sufficient independent trades, positive results under stressed costs, and no unresolved margin/contract eligibility issues before considering live use.

At 1x initial notional, multiplying a reported percentage by $1,000 gives hypothetical PnL for $1,000 notional; the user's $1,000 maximum-loss constraint is not account equity and does not set a live position size. Drawdowns here are daily close only and do not capture intraday losses, integer contract sizing, liquidation or leg/execution effects.

Data: existing Coinbase FUTURE daily candles, {date(0)} to {date(299)}. Provider returned 300 bars. Historical contract eligibility, actual historical funding and detailed fills remain unverified. No new out-of-sample period was acquired. No orders submitted.

Reproduce: `python3 refine_xrp_strategy.py`. Raw configuration scores and results: `xrp-refinement-results.json`. Arithmetic runs locally; this small daily-bar test needs no GPU.
'''
(ROOT / 'xrp-refinement-report.md').write_text(report)
print(json.dumps({k: result[k] for k in ('selected', 'diagnostic', 'baseline_diagnostic',
                                         'double_cost_funding_stress', 'descriptive_bootstrap_95_pct')}, indent=2))
