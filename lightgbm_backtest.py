"""LightGBM head-to-head on the same walk-forward windows as backtest_big.py.

Features from the same 200-candle lookback (returns, vol, RSI, volume, candle shape,
time). Chronological split: first 60% of windows train, 7-window embargo (covers the
200-candle lookback at stride 30), remainder = test. Kronos is scored on the SAME
test windows from data/{sym}_probs.npy when that file exists (full Kronos run).
"""
import sys, os, json
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from backtest_big import load_asset, metrics, simulate, LOOKBACK, STRIDE
import lightgbm as lgb

EPS = 1e-12

def features(df, cut):
    w = df.iloc[cut - LOOKBACK:cut]
    c = w["close"].to_numpy(float); o = w["open"].to_numpy(float)
    h = w["high"].to_numpy(float); l = w["low"].to_numpy(float); v = w["volume"].to_numpy(float)
    r = np.diff(np.log(c))
    f = {}
    for k in (1, 3, 6, 12, 24, 48, 96, 199):
        f[f"ret_{k}"] = c[-1] / c[-1 - k] - 1
    for k in (12, 48, 199):
        f[f"vol_{k}"] = float(np.std(r[-k:]))
    f["mean_r_6"] = float(np.mean(r[-6:])); f["mean_r_24"] = float(np.mean(r[-24:]))
    d = np.diff(c[-15:])
    gains = np.clip(d, 0, None).mean(); losses = np.clip(-d, 0, None).mean()
    f["rsi14"] = 100.0 if losses < EPS else 100 - 100 / (1 + gains / (losses + EPS))
    sma, sd = c[-48:].mean(), c[-48:].std()
    f["bb_pos48"] = (c[-1] - sma) / (2 * sd + EPS)
    f["dist_hi48"] = c[-1] / h[-48:].max() - 1
    f["dist_lo48"] = c[-1] / l[-48:].min() - 1
    f["vol_ratio"] = v[-1] / (v[-48:].mean() + EPS)
    f["vol_trend"] = v[-6:].mean() / (v[-48:].mean() + EPS)
    f["last_body"] = (c[-1] - o[-1]) / (h[-1] - l[-1] + EPS)
    f["last_range"] = (h[-1] - l[-1]) / c[-1]
    f["up_frac_12"] = float(np.mean(r[-12:] > 0)); f["up_frac_48"] = float(np.mean(r[-48:] > 0))
    ts = df["timestamps"].iloc[cut - 1]
    f["hour"] = ts.hour + ts.minute / 60.0; f["dow"] = ts.dayofweek
    return f

def run(sym):
    df = load_asset(sym)
    ts = df["timestamps"].values
    cuts = [c for c in range(LOOKBACK, len(df), STRIDE)
            if ts[c] - ts[c - 1] == np.timedelta64(5, "m")]
    X = pd.DataFrame([features(df, c) for c in cuts])
    y = np.array([1 if df["close"].iloc[c] > df["close"].iloc[c - 1] else 0 for c in cuts])
    n = len(cuts); n_train = int(n * 0.60); embargo = 7
    tr = slice(0, n_train); te = slice(n_train + embargo, n)
    n_val = int(n_train * 0.15)
    model = lgb.LGBMClassifier(objective="binary", n_estimators=800, learning_rate=0.03,
                               num_leaves=31, min_child_samples=40, subsample=0.8,
                               colsample_bytree=0.8, reg_lambda=1.0, verbose=-1)
    model.fit(X.iloc[tr][:-n_val] if n_val else X.iloc[tr], y[tr][:-n_val] if n_val else y[tr],
              eval_set=[(X.iloc[tr][-n_val:], y[tr][-n_val:])] if n_val else None,
              callbacks=[lgb.early_stopping(60, verbose=False)] if n_val else None)
    p = model.predict_proba(X.iloc[te])[:, 1]
    y_te = y[te]
    out = {"asset": sym, "windows_total": n, "train_n": int(n_train - (n_val or 0)),
           "test_n": int(len(y_te)), "best_iter": int(model.best_iteration_ or model.n_estimators),
           "lgbm_test": metrics(p, y_te), "lgbm_sim": simulate(p, y_te),
           "top_features": [(str(k), int(v)) for k, v in sorted(zip(X.columns, model.feature_importances_),
                                  key=lambda t: -t[1])[:10]]}
    # Head-to-head: Kronos probs on the identical test cuts
    npy = f"data/{sym}_probs.npy"
    if os.path.exists(npy):
        arr = np.load(npy)
        kmap = {int(r[0]): (r[1], int(r[2])) for r in arr}
        test_cuts = cuts[te]
        if all(c in kmap for c in test_cuts):
            kp = np.array([kmap[c][0] for c in test_cuts])
            ky = np.array([kmap[c][1] for c in test_cuts])
            assert (ky == y_te).all()
            out["kronos_on_same_test"] = metrics(kp, ky)
            out["kronos_sim_same_test"] = simulate(kp, ky)
            agree = np.mean((kp > 0.5) == (p > 0.5))
            both_right = np.mean(((kp > 0.5) == (ky == 1)) & ((p > 0.5) == (y_te == 1)))
            out["agreement"] = {"call_agreement": float(agree), "both_correct": float(both_right)}
    return out

if __name__ == "__main__":
    results = [run(s) for s in ("BTC", "ETH")]
    with open("results_lgbm.json", "w") as f:
        json.dump(results, f, indent=1)
    print(json.dumps(results, indent=1))
