"""Offline Coinbase BTC futures adaptations of two linked vault strategies.

Standard library; no API keys, order endpoint, or live execution. Writes a report,
summary JSON and marked equity CSV. Capital is a hypothetical scenario only.
"""
import bisect
import csv
import datetime as dt
import json
import math
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent
UTC = dt.timezone.utc
CAPITAL = 10000.0
MULTIPLIER = 0.01
LONG_MARGIN, SHORT_MARGIN = 0.21025, 0.256625
FEE_MAKER, FEE_TAKER = 0.00095, 0.001
SLIP = 0.0002
TICK = 5.0
LOSS_BUDGET = 1000.0
START = int(dt.datetime(2026, 11, 4, tzinfo=UTC).timestamp())
END = int(dt.datetime(2026, 11, 19, 1, 30, tzinfo=UTC).timestamp())


def timestamp(s):
    return int(dt.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp())


def load():
    source = json.loads((ROOT / 'vault-competition-input.json').read_text())
    groups = {'1h': {}, '15m': {}}
    for response in source['requests']:
        req = response['request']
        lo, hi = timestamp(req['start']), timestamp(req['end'])
        for b in response['candles']:
            t = int(b['start'])
            if lo <= t < hi:
                groups[req['granularity']][t] = {k: float(v) for k, v in b.items()}
    fine = groups['15m']
    # Only aggregate complete hours; absent hours are marked synthetic below.
    for h in sorted({t//3600*3600 for t in fine}):
        parts = [fine.get(h+i*900) for i in range(4)]
        if all(parts):
            groups['1h'][h] = dict(start=h, open=parts[0]['open'],
                                    close=parts[-1]['close'],
                                    high=max(b['high'] for b in parts),
                                    low=min(b['low'] for b in parts),
                                    volume=sum(b['volume'] for b in parts))
    hours = groups['1h']
    hourly, missing = [], 0
    for h in range(min(hours), max(hours)+1, 3600):
        if h in hours:
            hourly.append(hours[h])
        else:
            missing += 1
            p = hourly[-1]['close']
            hourly.append(dict(start=h, open=p, close=p, high=p, low=p, volume=0))
    bars = [fine[t] for t in sorted(fine) if START <= t < END]
    assert bars and all(b['low'] <= min(b['open'], b['close']) <= max(b['open'], b['close']) <= b['high'] for b in bars)
    return hourly, bars, missing


def indicators(hours):
    fast = slow = ema14 = hours[0]['close']
    variance = 0.0
    prior = hours[0]['close']
    volumes, out = [], []
    for i, b in enumerate(hours):
        p = b['close']
        fast += 2/49*(p-fast)
        slow += 2/481*(p-slow)
        ema14 += 2/15*(p-ema14)
        ret = math.log(p/prior)
        variance += 2/337*(ret*ret-variance)
        volumes.append(b['volume'])
        v24 = sum(volumes[-24:])
        v30 = sum(volumes[-720:])/30
        participation = min(3., v24/v30) if v30 > 0 else 0.
        trend = math.log(fast/slow)
        ann_var = max(variance*8760, 0.10**2)
        out.append(dict(time=int(b['start'])+3600, trend=trend,
                        participation=participation, variance=ann_var, ema14=ema14))
        prior = p
    return out


def score(x, kind):
    trend = x['trend']
    if kind == 'trend':
        return trend
    if kind == 'trend_volume':
        return trend*x['participation']
    power = 0.5 if kind == 'inverse_volatility' else 1.
    return trend*x['participation']/x['variance']**power


class Ledger:
    def __init__(self, name, funding_bps):
        self.name, self.funding_bps = name, funding_bps
        self.equity, self.peak = CAPITAL, CAPITAL
        self.q, self.last = 0., None
        self.fees = self.funding = self.turnover = 0.
        self.max_dd = self.max_loss = self.max_margin = self.max_exposure = 0.
        self.fills = self.margin_breaches = 0
        self.loss_breached = False
        self.curve = []

    def observe(self, price):
        equity = self.equity + (self.q*(price-self.last) if self.last is not None else 0.)
        self.peak = max(self.peak, equity)
        self.max_dd = max(self.max_dd, self.peak-equity)
        self.max_loss = max(self.max_loss, CAPITAL-equity)
        self.loss_breached |= equity <= CAPITAL-LOSS_BUDGET
        margin = abs(self.q)*price*(LONG_MARGIN if self.q >= 0 else SHORT_MARGIN)
        self.max_margin = max(self.max_margin, margin)
        self.max_exposure = max(self.max_exposure, abs(self.q)*price)
        return equity, margin

    def mark(self, price):
        if self.last is not None:
            self.equity += self.q*(price-self.last)
        self.last = price
        self.observe(price)

    def trade(self, target_q, price, fee):
        self.mark(price)
        delta = abs(target_q-self.q)
        if delta < 1e-9:
            return
        cost = delta*price*(fee+SLIP)
        self.equity -= cost
        self.fees += cost
        self.turnover += delta*price
        self.fills += 1
        self.q = target_q
        self.observe(price)

    def close_bar(self, b, elapsed):
        self.mark(b['close'])
        charge = abs(self.q)*b['close']*self.funding_bps/10000*elapsed/86400
        self.equity -= charge
        self.funding += charge
        self.observe(b['close'])
        self.curve.append((int(b['start'])+900, self.equity, self.q))

    def summary(self):
        return dict(strategy=self.name, net_pnl_usd=self.equity-CAPITAL,
                    return_pct=100*(self.equity/CAPITAL-1),
                    max_drawdown_usd=self.max_dd, max_loss_from_initial_usd=self.max_loss,
                    execution_cost_usd=self.fees, funding_drag_usd=self.funding,
                    turnover_usd=self.turnover, fills=self.fills,
                    max_notional_usd=self.max_exposure, max_margin_proxy_usd=self.max_margin,
                    initial_loss_budget_breached=self.loss_breached,
                    margin_proxy_breach_bars=self.margin_breaches)


def trend_run(bars, ind, kind, funding_bps, scale):
    l = Ledger('astraeus_'+kind, funding_bps)
    times = [x['time'] for x in ind]
    target_weight = 0.
    last_t = int(bars[0]['start'])-900
    margin_failed = False
    for b in bars:
        t = int(b['start'])
        l.mark(b['open'])
        if t % 86400 == 6300 and not margin_failed:  # 01:45 UTC
            j = bisect.bisect_right(times, t)-1
            assert ind[j]['time'] <= t
            desired = max(-1., min(1., scale*score(ind[j], kind)))
            target_weight += .8*(desired-target_weight)
            # Adaptation: cap to 1x current research equity, integer micro contracts.
            q = math.trunc(target_weight*max(l.equity, 0)/b['open']/MULTIPLIER)*MULTIPLIER
            l.trade(q, b['open'], FEE_TAKER)
        adverse = b['low'] if l.q >= 0 else b['high']
        adverse_equity, margin = l.observe(adverse)
        l.observe(b['high'] if l.q >= 0 else b['low'])
        if l.q and adverse_equity < margin:
            l.margin_breaches += 1
            l.trade(0., adverse, FEE_TAKER)
            margin_failed = True
        l.close_bar(b, t-last_t)
        last_t = t
    l.trade(0., bars[-1]['close'], FEE_TAKER)
    l.curve[-1] = (END, l.equity, 0.)
    return l


def passive_run(bars, side, funding_bps):
    l = Ledger('passive_'+('long' if side > 0 else 'short'), funding_bps)
    q = side*math.floor(CAPITAL/bars[0]['open']/MULTIPLIER)*MULTIPLIER
    l.trade(q, bars[0]['open'], FEE_TAKER)
    prior = int(bars[0]['start'])-900
    for b in bars:
        l.mark(b['open'])
        l.observe(b['low'] if side > 0 else b['high'])
        l.observe(b['high'] if side > 0 else b['low'])
        l.close_bar(b, int(b['start'])-prior)
        prior = int(b['start'])
    l.trade(0., bars[-1]['close'], FEE_TAKER)
    return l


def average_run(bars, ind, take_profit, path, funding_bps, bounded):
    label = f'archive_tp{take_profit*100:.1f}_{path}_'+('bounded' if bounded else 'source_like')
    l = Ledger(label, funding_bps)
    times = [x['time'] for x in ind]
    first = avg = 0.
    adds, wins, cycles = 0, 0, 0
    max_adds, skipped = 0, 0
    drawdowns = (0.0225, 0.035, 0.05, 0.07, 0.098)
    halted = False
    last_t = int(bars[0]['start'])-900
    for b in bars:
        t = int(b['start'])
        j = bisect.bisect_right(times, t)-1
        entry_limit = math.floor(.992*ind[j]['ema14']/TICK)*TICK
        entered_this_bar = False
        closed_this_bar = False

        def buy(q, p):
            nonlocal avg, first, adds, entered_this_bar, skipped
            new_q = l.q+q
            # Explicit adaptation; raw variant can double to all 32 micro contracts.
            if bounded and new_q*p > max(l.equity, 0):
                skipped += 1
                return False
            avg = (avg*l.q+p*q)/new_q
            if not l.q:
                first, adds = p, 0
                entered_this_bar = True
            else:
                adds += 1
            l.trade(new_q, p, FEE_MAKER)
            return True

        def close(p, forced=False):
            nonlocal cycles, wins, avg, first, closed_this_bar, halted
            # Cycle count is price-based; separately report total net PnL/costs.
            if not forced:
                wins += int(p > avg)
            cycles += 1
            l.trade(0., p, FEE_TAKER if forced else FEE_MAKER)
            avg = first = 0.
            closed_this_bar = True
            halted |= forced

        def risk(p):
            nonlocal halted
            equity, margin = l.observe(p)
            if l.q and equity < margin:
                l.margin_breaches += 1
                close(p, True)
            elif bounded and l.q and equity <= CAPITAL-LOSS_BUDGET:
                close(p, True)

        # Opening gaps: reprice marketable limits at the opening print.
        l.mark(b['open'])
        if l.q:
            risk(b['open'])
            if l.q and b['open'] >= avg*(1+take_profit):
                close(b['open'])
            while l.q and adds < len(drawdowns) and b['open'] <= math.floor(first*(1-drawdowns[adds])/TICK)*TICK:
                if not buy(l.q, b['open']):
                    break
                risk(b['open'])
        elif not halted and b['open'] <= entry_limit:
            buy(MULTIPLIER, b['open'])

        points = [b['open'], b['low'], b['high'], b['close']] if path == 'low_high' else [b['open'], b['high'], b['low'], b['close']]
        for a, z in zip(points, points[1:]):
            if z < a:
                if not l.q and not halted and not closed_this_bar and not entered_this_bar and z <= entry_limit <= a:
                    buy(MULTIPLIER, entry_limit)
                while l.q and adds < len(drawdowns):
                    level = math.floor(first*(1-drawdowns[adds])/TICK)*TICK
                    if not z <= level <= a:
                        break
                    risk(level)
                    if not l.q or not buy(l.q, level):
                        break
                    max_adds = max(max_adds, adds)
                risk(z)
            elif l.q and z >= math.ceil(avg*(1+take_profit)/TICK)*TICK >= a:
                close(math.ceil(avg*(1+take_profit)/TICK)*TICK)
            else:
                risk(z)
            l.mark(z)
        l.close_bar(b, t-last_t)
        last_t = t
    terminal_open_q = l.q
    terminal_unrealized = l.q*(bars[-1]['close']-avg) if l.q else 0.
    # Force an explicit end-of-window exit; never omit underwater inventory.
    if l.q:
        close(bars[-1]['close'], True)
    l.curve[-1] = (END, l.equity, 0.)
    extra = dict(completed_cycles_before_terminal=cycles-int(terminal_open_q>0),
                 price_profitable_cycles=wins, terminal_open_contracts=round(terminal_open_q/MULTIPLIER),
                 terminal_unrealized_before_exit_usd=terminal_unrealized,
                 deepest_add_level=max_adds, blocked_additions=skipped)
    return l, extra


def main():
    hours, bars, missing = load()
    ind = indicators(hours)
    # Fixed September calibration, unrelated to competition-period returns.
    dev = [x for x in ind if timestamp('2026-09-01T00:00:00Z') <= x['time'] < timestamp('2026-10-01T00:00:00Z')]
    scales = {kind: .5/max(median(abs(score(x, kind)) for x in dev), 1e-9)
              for kind in ('trend', 'trend_volume', 'inverse_volatility', 'inverse_variance')}
    rows, curves = [], []
    # Actual US funding history unavailable: report cost sensitivity, not net actual funding.
    for funding in (0., 5., 10.):
        for side in (-1, 1):
            l = passive_run(bars, side, funding)
            rows.append(dict(**l.summary(), funding_drag_bps_day=funding))
        for kind in scales:
            l = trend_run(bars, ind, kind, funding, scales[kind])
            rows.append(dict(**l.summary(), funding_drag_bps_day=funding))
            if funding == 5:
                curves.extend((l.name, *r) for r in l.curve)
        for tp in (.001, .003, .005):
            for path in ('low_high', 'high_low'):
                for bounded in (False, True):
                    l, extra = average_run(bars, ind, tp, path, funding, bounded)
                    rows.append(dict(**l.summary(), **extra, funding_drag_bps_day=funding))
                    if funding == 5 and tp == .003:
                        curves.extend((l.name, *r) for r in l.curve)
    post_publication = []
    later = [b for b in bars if b['start'] >= timestamp('2026-11-18T00:00:00Z')]
    l = trend_run(later, ind, 'inverse_variance', 5., scales['inverse_variance'])
    post_publication.append(l.summary())
    for path in ('low_high', 'high_low'):
        l, extra = average_run(later, ind, .003, path, 5., False)
        post_publication.append(dict(**l.summary(), **extra))
    crash = []
    for i in range(96):
        a, z = 70000*(1-.30*i/96), 70000*(1-.30*(i+1)/96)
        crash.append(dict(start=START+i*900, open=a, close=z, high=a, low=z, volume=1))
    frozen = [dict(time=START, ema14=70000)]
    stress = []
    for bounded in (False, True):
        l, extra = average_run(crash, frozen, .003, 'high_low', 5., bounded)
        stress.append(dict(**l.summary(), **extra))
    result = dict(observed_start_utc=dt.datetime.fromtimestamp(START, UTC).isoformat(),
                  observed_end_exclusive_utc=dt.datetime.fromtimestamp(END, UTC).isoformat(),
                  hypothetical_equity_usd=CAPITAL, not_actual_account_balance=True,
                  contract_size_btc=MULTIPLIER, scales_fitted_september=scales,
                  bars_15m=len(bars), synthetic_warmup_hours=missing,
                  missing_competition_15m_bars=(END-START)//900-len(bars),
                  all_results=rows, post_publication_partial_day=post_publication,
                  synthetic_30pct_one_day_decline=stress,
                  warning='Retrospective source-inspired adaptations, not independent out-of-sample vault replication; no live orders.')
    (ROOT / 'vault-competition-results.json').write_text(json.dumps(result, indent=2)+'\n')
    with (ROOT / 'vault-competition-equity.csv').open('w') as f:
        writer = csv.writer(f, lineterminator='\n')
        writer.writerow(['strategy', 'timestamp_utc', 'equity_usd', 'btc_position'])
        for name, t, equity, q in curves:
            writer.writerow([name, dt.datetime.fromtimestamp(t, UTC).isoformat(), equity, q])
    central = [r for r in rows if r['funding_drag_bps_day'] == 5 and
               (r['strategy'].startswith('astraeus') or '_tp0.3_' in r['strategy'])]
    print(json.dumps(central, indent=2))


if __name__ == '__main__':
    main()
