"""Walk-forward test of long/cash Coinbase spot strategies under fee assumptions.

Research only: reads candle CSVs, fits models, prints/writes statistics. It never
contacts a venue's private endpoints, places orders, or feeds the paper runner.

Data: data/{BTC,ETH}_15m.csv in the same format trading/train_15m.py uses
(timestamps, open, high, low, close, volume).

Usage (needs numpy, pandas, scikit-learn):
    python -m trading.walkforward_spot base   # how often moves clear the cost hurdle
    python -m trading.walkforward_spot wf     # walk-forward models; writes results_spot_walkforward.json

Method: features use only bars up to the entry bar's close. Models are refit
every `retrain_days` on all earlier data (with an embargo of the holding
horizon) and scored only on the following unseen block, over the last
`test_days`. One position at a time, entered at the bar close when the predicted
net return is above zero, held for H bars. Costs follow SPOT_PAPER.md: fee per
side, 5 bps slippage per side, 1 bp exit half-spread.
"""
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
G = 900
HORIZONS = (1, 4, 16, 96)  # 15m, 1h, 4h, 24h
FEES = (0.009, 0.005, 0.001)  # taker, maker, hypothetical low tier


def load(sym):
    df = pd.read_csv(ROOT / "data" / f"{sym}_15m.csv", parse_dates=["timestamps"])
    df["ts"] = (df.timestamps - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)
    idx = np.arange(df.ts.iloc[0], df.ts.iloc[-1] + G, G)
    df = df.drop(columns="timestamps").set_index("ts").reindex(idx)
    df["gap"] = df.close.isna()
    df["close"] = df.close.ffill()
    for c in ("open", "high", "low"):
        df[c] = df[c].fillna(df.close)
    df["volume"] = df.volume.fillna(0)
    return df


def feats(df):
    c, o, h, l, v = df.close, df.open, df.high, df.low, df.volume
    lr = np.log(c).diff()
    f = pd.DataFrame(index=df.index)
    for k in (1, 2, 4, 8, 16, 32, 96, 192, 672):
        f[f"ret_{k}"] = c / c.shift(k) - 1
    for k in (4, 16, 96, 672):
        f[f"vol_{k}"] = lr.rolling(k).std()
    f["volr_4_96"] = f.vol_4 / f.vol_96
    f["volr_96_672"] = f.vol_96 / f.vol_672
    for k in (16, 96, 672):
        hi, lo = h.rolling(k).max(), l.rolling(k).min()
        f[f"pos_{k}"] = (c - lo) / (hi - lo + 1e-12)
        f[f"z_{k}"] = (c - c.rolling(k).mean()) / (c.rolling(k).std() + 1e-12)
    f["range1"] = (h - l) / c
    f["body1"] = (c - o) / (h - l + 1e-12)
    f["upwick"] = (h - np.maximum(c, o)) / c
    f["dnwick"] = (np.minimum(c, o) - l) / c
    f["volu_r"] = v / (v.rolling(96).mean() + 1e-12)
    f["volu_r4"] = v.rolling(4).mean() / (v.rolling(672).mean() + 1e-12)
    f["upfrac16"] = (lr > 0).rolling(16).mean()
    d = c.diff()
    g = d.clip(lower=0).rolling(14).mean()
    ls = (-d).clip(lower=0).rolling(14).mean()
    f["rsi"] = 100 - 100 / (1 + g / (ls + 1e-12))
    t = pd.to_datetime(df.index, unit="s")
    f["hour"] = t.hour + t.minute / 60
    f["dow"] = t.day_of_week
    return f


def cost_mult(fee, slip_bps=5, hs_bps=1):
    """net return = (exit_mid / entry_mid) * cost_mult - 1."""
    return (1 - hs_bps / 1e4) * (1 - slip_bps / 1e4) * (1 - fee) / ((1 + slip_bps / 1e4) * (1 + fee))


def run(sym, H, fee, test_days=730, retrain_days=60, mode="reg"):
    """Return (net, fwd, bad, pred, t0); pred is predicted net return (reg) or P(net>0)-0.5 (clf)."""
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

    df = load(sym)
    X = feats(df)
    k = cost_mult(fee)
    fwd = df.close.shift(-H) / df.close - 1
    bad = df.gap.rolling(H + 1).max().shift(-H).fillna(1).astype(bool) | X.isna().any(axis=1)
    net = (1 + fwd) * k - 1
    n = len(df)
    t0 = n - test_days * 96
    pred = np.full(n, np.nan)
    step = retrain_days * 96
    params = dict(max_iter=200, learning_rate=0.03, max_leaf_nodes=15,
                  min_samples_leaf=200, l2_regularization=1.0, random_state=0)
    for s in range(t0, n, step):
        tr = np.arange(0, s - H)  # embargo: labels must end before the test block
        tr = tr[~bad.values[tr]]
        te = np.arange(s, min(s + step, n))
        if mode == "reg":
            m = HistGradientBoostingRegressor(**params).fit(X.values[tr], fwd.values[tr])
            pred[te] = (1 + m.predict(X.values[te])) * k - 1
        else:
            y = (net.values[tr] > 0).astype(int)
            if y.sum() < 50:
                pred[te] = -1
                continue
            m = HistGradientBoostingClassifier(**params).fit(X.values[tr], y)
            pred[te] = m.predict_proba(X.values[te])[:, 1] - 0.5
    return net, fwd, bad, pred, t0


def simulate(net, bad, pred, t0, H, thr=0.0):
    """One position at a time: enter when pred > thr, hold H bars."""
    i, n, trades = t0, len(net), []
    nv, bv = net.values, bad.values
    while i < n - H:
        if not bv[i] and pred[i] > thr:
            trades.append(nv[i])
            i += H
        else:
            i += 1
    return np.array(trades)


def summ(tr):
    if len(tr) == 0:
        return dict(n=0)
    eq = np.cumprod(1 + tr)
    dd = (eq / np.maximum.accumulate(eq) - 1).min()
    return dict(n=int(len(tr)), mean_bps=round(float(tr.mean() * 1e4), 1),
                win=round(float((tr > 0).mean()), 3), total=round(float(eq[-1] - 1), 4),
                maxdd=round(float(dd), 4),
                t=round(float(tr.mean() / (tr.std() + 1e-12) * np.sqrt(len(tr))), 2))


def base_rates(test_days=730):
    for sym in ("BTC", "ETH"):
        df = load(sym).iloc[-test_days * 96:]
        for H in HORIZONS:
            fwd = (df.close.shift(-H) / df.close - 1).dropna()
            for fee in FEES:
                k = cost_mult(fee)
                net = (1 + fwd) * k - 1
                print(f"{sym} H={H:3d} fee={fee:.3f} hurdle={(1 / k - 1) * 100:.2f}%  "
                      f"P(move>hurdle)={(net > 0).mean():.4%}  always-long mean net={net.mean() * 1e4:8.1f}bps")


def walk_forward(out_path=ROOT / "results_spot_walkforward.json"):
    out = []
    for sym in ("BTC", "ETH"):
        for H in HORIZONS:
            # Regression is fee-independent: fit once at zero cost, then re-apply each cost level.
            _, fwd, bad, pred0, t0 = run(sym, H, 0.0, mode="reg")
            gross = (1 + pred0) / cost_mult(0.0)
            ok = ~bad.values[t0:] & ~np.isnan(pred0[t0:])
            ic = float(np.corrcoef(pred0[t0:][ok], fwd.values[t0:][ok])[0, 1])
            for fee in FEES + (0.0,):
                k = cost_mult(fee) if fee else cost_mult(0, 0, 0)
                net, pred = (1 + fwd) * k - 1, gross * k - 1
                out.append(dict(sym=sym, H=H, fee=fee, mode="reg", ic=round(ic, 4),
                                maxpred_bps=round(float(np.nanmax(pred[t0:]) * 1e4), 1),
                                **summ(simulate(net, bad, pred, t0, H))))
                print(json.dumps(out[-1]), flush=True)
            for fee in FEES:
                net, fwd, bad, pred, t0 = run(sym, H, fee, mode="clf")
                out.append(dict(sym=sym, H=H, fee=fee, mode="clf", **summ(simulate(net, bad, pred, t0, H))))
                print(json.dumps(out[-1]), flush=True)
    Path(out_path).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    if len(sys.argv) != 2 or sys.argv[1] not in ("base", "wf"):
        raise SystemExit("usage: python -m trading.walkforward_spot {base|wf}")
    base_rates() if sys.argv[1] == "base" else walk_forward()
