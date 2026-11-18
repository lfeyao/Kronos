"""15-Minute Training & Probability Calibration Suite for Kronos / LightGBM.

Trains on trailing 1 year of 15-minute Coinbase candles (35,040 bars per asset)
to match the active 15-minute (900s) prediction contract horizon specified in
trading/config.json and trading/GEMINI_HANDOFF.md.
"""
import os, sys, json, time, urllib.request, pickle
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GRAN_15M = 900
BARS_PER_DAY = 96
DAYS_1Y = 365
LOOKBACK_15M = 200
COINBASE_URL = "https://api.exchange.coinbase.com/products/{}/candles?granularity=900&start={}&end={}"
EPS = 1e-12

def fetch_15m(n=DAYS_1Y * BARS_PER_DAY + LOOKBACK_15M, product="BTC-USD"):
    rows, end = [], int(time.time())
    print(f"Fetching {n:,} 15-minute candles for {product}...", flush=True)
    while len(rows) < n:
        start = end - GRAN_15M * 300
        req = urllib.request.Request(
            COINBASE_URL.format(product,
                pd.to_datetime(start, unit="s", utc=True).isoformat(),
                pd.to_datetime(end, unit="s", utc=True).isoformat()),
            headers={"User-Agent": "kronos-15m-train"}
        )
        batch = None
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    batch = json.load(r)
                break
            except Exception:
                time.sleep(1.5 * (attempt + 1))
        if not batch:
            break
        rows.extend(batch)
        end = batch[-1][0] - GRAN_15M
        time.sleep(0.25)
    df = pd.DataFrame(rows, columns=["ts", "low", "high", "open", "close", "volume"])
    df = df.drop_duplicates("ts").sort_values("ts")
    df["timestamps"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_localize(None)
    df = df[["timestamps", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    return df

def load_15m(sym):
    path = ROOT / "data" / f"{sym}_15m.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        df = pd.read_csv(path, parse_dates=["timestamps"])
        if len(df) >= 30000:
            return df
    df = fetch_15m(product=f"{sym}-USD")
    df.to_csv(path, index=False)
    return df

def features_15m(df, cut):
    w = df.iloc[cut - LOOKBACK_15M:cut]
    c = w["close"].to_numpy(float); o = w["open"].to_numpy(float)
    h = w["high"].to_numpy(float); l = w["low"].to_numpy(float); v = w["volume"].to_numpy(float)
    r = np.diff(np.log(c))
    f = {}
    for k in (1, 3, 6, 12, 24, 48, 96, 192):
        f[f"ret_{k}"] = c[-1] / c[-1 - k] - 1
    for k in (6, 24, 96):
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
    f["up_frac_12"] = float(np.mean(r[-12:] > 0))
    ts = df["timestamps"].iloc[cut - 1]
    f["hour"] = ts.hour + ts.minute / 60.0; f["dow"] = ts.dayofweek
    return f

def train_and_calibrate(sym):
    import lightgbm as lgb
    from sklearn.isotonic import IsotonicRegression
    from sklearn.metrics import brier_score_loss, roc_auc_score

    df = load_15m(sym)
    ts = df["timestamps"].values
    n_total = len(df)
    eval_7d_start = max(LOOKBACK_15M, n_total - 7 * BARS_PER_DAY)
    eval_24h_start = max(LOOKBACK_15M, n_total - BARS_PER_DAY)
    calib_start = max(LOOKBACK_15M, eval_7d_start - 14 * BARS_PER_DAY)
    embargo = LOOKBACK_15M

    train_cuts = [c for c in range(LOOKBACK_15M, calib_start - embargo, 2)
                  if ts[c] - ts[c - 1] == np.timedelta64(15, "m")]
    calib_cuts = [c for c in range(calib_start, eval_7d_start - embargo)
                  if ts[c] - ts[c - 1] == np.timedelta64(15, "m")]
    cuts_7d = [c for c in range(eval_7d_start, n_total)
               if ts[c] - ts[c - 1] == np.timedelta64(15, "m")]

    def build_xy(cuts):
        X = pd.DataFrame([features_15m(df, c) for c in cuts])
        ret = np.array([(df["close"].iloc[c] - df["close"].iloc[c - 1]) / df["close"].iloc[c - 1] for c in cuts])
        return X, (ret > 0).astype(int), ret

    print(f"[{sym}] Extracting 15m feature sets...", flush=True)
    X_tr, y_tr, _ = build_xy(train_cuts)
    X_cal, y_cal, _ = build_xy(calib_cuts)
    X_7d, y_7d, ret_7d = build_xy(cuts_7d)

    age_days = (train_cuts[-1] - np.array(train_cuts)) / BARS_PER_DAY
    sample_weights = np.exp(-np.log(2) * age_days / 90.0)

    model = lgb.LGBMClassifier(
        objective="binary", n_estimators=600, learning_rate=0.03,
        num_leaves=31, min_child_samples=30, subsample=0.8,
        colsample_bytree=0.8, reg_lambda=1.5, verbose=-1
    )
    model.fit(X_tr, y_tr, sample_weight=sample_weights,
              eval_set=[(X_cal, y_cal)],
              callbacks=[lgb.early_stopping(50, verbose=False)])

    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.05, y_max=0.95)
    raw_cal = model.predict_proba(X_cal)[:, 1]
    iso.fit(raw_cal, y_cal)

    raw_7d = model.predict_proba(X_7d)[:, 1]
    cal_7d = iso.transform(raw_7d)

    mask_24h = np.array([c >= eval_24h_start for c in cuts_7d])
    cal_24h = cal_7d[mask_24h]
    y_24h = y_7d[mask_24h]

    # Save artifacts
    model_dir = ROOT / "trading" / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    with open(model_dir / f"lgbm_{sym}_15m.pkl", "wb") as f:
        pickle.dump({"model": model, "features": list(X_tr.columns), "trained_at": time.time()}, f)
    with open(model_dir / f"iso_{sym}_15m.pkl", "wb") as f:
        pickle.dump(iso, f)

    res = {
        "asset": sym, "horizon": "15m",
        "acc_24h": float(np.mean((cal_24h > 0.5) == y_24h)),
        "brier_24h": float(brier_score_loss(y_24h, cal_24h)),
        "acc_7d": float(np.mean((cal_7d > 0.5) == y_7d)),
        "brier_7d": float(brier_score_loss(y_7d, cal_7d)),
        "auc_7d": float(roc_auc_score(y_7d, raw_7d))
    }
    print(f"[{sym} 15m Results] {json.dumps(res, indent=2)}", flush=True)
    return res

if __name__ == "__main__":
    for s in ("BTC", "ETH"):
        train_and_calibrate(s)
