import sys, json
import numpy as np, pandas as pd
sys.path.insert(0, ".")
from lightgbm_backtest import features
from backtest_big import load_asset, LOOKBACK, STRIDE
import lightgbm as lgb

rows = json.load(open("results_market.json"))
out = {}
for sym in ("BTC", "ETH"):
    df = load_asset(sym)
    ts = df["timestamps"].values
    cuts = [c for c in range(LOOKBACK, len(df), STRIDE) if ts[c] - ts[c-1] == np.timedelta64(5, "m")]
    X = pd.DataFrame([features(df, c) for c in cuts])
    y = np.array([1 if df["close"].iloc[c] > df["close"].iloc[c-1] else 0 for c in cuts])
    n = len(cuts); n_train = int(n*0.60); embargo = 7; n_val = int(n_train*0.15)
    m = lgb.LGBMClassifier(objective="binary", n_estimators=800, learning_rate=0.03, num_leaves=31,
                           min_child_samples=40, subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0, verbose=-1)
    m.fit(X.iloc[:n_train][:-n_val], y[:n_train][:-n_val], eval_set=[(X.iloc[:n_train][-n_val:], y[:n_train][-n_val:])],
          callbacks=[lgb.early_stopping(60, verbose=False)])
    cut_ts = {str(df["timestamps"].iloc[c]): i for i, c in enumerate(cuts)}
    probs = m.predict_proba(X)[:, 1]
    sub = [r for r in rows if r["asset"] == sym and r["window_utc"] in cut_ts]
    lp = np.array([probs[cut_ts[r["window_utc"]]] for r in sub])
    mp = np.array([r["market_open_p"] for r in sub]); yy = np.array([r["outcome_up_market"] for r in sub])
    res = {"n": len(sub), "lgbm_acc": float(np.mean((lp > 0.5) == (yy == 1))), "lgbm_brier": float(np.mean((lp - yy) ** 2))}
    for th in (0.05, 0.10):
        pnl, nb = 0.0, 0
        for r, p in zip(sub, lp):
            d = p - r["market_open_p"]
            if abs(d) >= th:
                nb += 1
                if d > 0: price, win = r["market_open_p"] + 0.01, r["outcome_up_market"] == 1
                else: price, win = (1 - r["market_open_p"]) + 0.01, r["outcome_up_market"] == 0
                pnl += (1.0/price - 1.0) if win else -1.0
        res[f"div>={th}"] = {"bets": nb, "pnl_per_$1": round(float(pnl), 2)}
    out[sym] = res
    print(sym, res)
json.dump(out, open("results_lgbm_market.json", "w"), indent=1)
