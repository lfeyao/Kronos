"""Kronos big backtest: BTC + ETH 5-minute candles, walk-forward.

- ~60 days of Coinbase 5m candles per asset (cached to data/).
- Windows every STRIDE candles, lookback 200, horizon 1 candle.
- P(up) per window from ROUNDS sampled paths via predict_batch (sample_count=1 per round).
- Metrics: accuracy, Brier, log loss, calibration buckets, high-confidence subsets,
  momentum baseline, simulated betting vs a flat 50c market with 1c half-spread.
Usage: python backtest_big.py [--probe] [--assets BTC,ETH]
"""
import sys, os, json, time, argparse
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
os.makedirs("data", exist_ok=True)
from test_btc_5min import fetch_candles  # paginated Coinbase fetcher

LOOKBACK = 200
STRIDE = 30
ROUNDS = 10
BATCH = 40
DAYS = 62

def load_asset(sym):
    path = f"data/{sym}.csv"
    need = DAYS * 288
    if os.path.exists(path):
        df = pd.read_csv(path, parse_dates=["timestamps"])
        if len(df) >= need * 0.98:
            return df
    print(f"Fetching {sym}-USD candles (~{need})...", flush=True)
    df = fetch_candles(need + 400, product=f"{sym}-USD")
    df.to_csv(path, index=False)
    return df

def kronos_probs(predictor, df, cuts, tag=""):
    """Return P(up) per cut using ROUNDS batched rounds of predict_batch.
    Checkpoints after every batch to data/{tag}_partial.npz; resumes if present."""
    partial = f"data/{tag}_partial.npz"
    ups = np.zeros(len(cuts))
    start = 0
    if tag and os.path.exists(partial):
        z = np.load(partial)
        if list(z["cuts"]) == list(cuts):
            ups = z["ups"].astype(float); start = int(z["done"])
            print(f"  resuming {tag} at window {start}/{len(cuts)}", flush=True)
    for s in range(start, len(cuts), BATCH):
        batch_cuts = cuts[s:s + BATCH]
        x_list = [df.iloc[c - LOOKBACK:c][["open", "high", "low", "close", "volume"]] for c in batch_cuts]
        xt_list = [df.iloc[c - LOOKBACK:c]["timestamps"] for c in batch_cuts]
        yt_list = [df.iloc[c:c + 1]["timestamps"] for c in batch_cuts]
        last_close = np.array([df["close"].iloc[c - 1] for c in batch_cuts])
        for r in range(ROUNDS):
            outs = predictor.predict_batch(df_list=x_list, x_timestamp_list=xt_list,
                                           y_timestamp_list=yt_list, pred_len=1,
                                           T=1.0, top_p=0.9, sample_count=1, verbose=False)
            pred_close = np.array([o["close"].iloc[-1] for o in outs])
            ups[s:s + len(batch_cuts)] += (pred_close > last_close)
        if tag:
            np.savez(partial, cuts=np.array(cuts), ups=ups, done=s + len(batch_cuts))
        print(f"  windows {s + len(batch_cuts)}/{len(cuts)} done", flush=True)
    return ups / ROUNDS

def metrics(p, y):
    p_c = np.clip(p, 0.025, 0.975)
    call = p > 0.5
    return {
        "n": int(len(y)),
        "base_rate_up": float(np.mean(y)),
        "accuracy": float(np.mean(call == y)),
        "brier": float(np.mean((p - y) ** 2)),
        "logloss": float(-np.mean(y * np.log(p_c) + (1 - y) * np.log(1 - p_c))),
    }

def simulate(p, y, ask=0.51):
    """Bet $1 on Kronos's favored side when its prob for that side >= threshold.
    Market is flat 50c; you pay the 51c ask. Win pays $1."""
    rows = {}
    side_p = np.where(p >= 0.5, p, 1 - p)
    side_win = np.where(p >= 0.5, y == 1, y == 0)
    for th in (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80):
        m = side_p >= th
        if m.sum() == 0:
            rows[str(th)] = {"bets": 0}
            continue
        pnl = np.where(side_win[m], 1.0 / ask - 1.0, -1.0)
        rows[str(th)] = {"bets": int(m.sum()), "win_rate": float(np.mean(side_win[m])),
                         "roi_pct": float(100 * np.mean(pnl)), "total_pnl_per_$1": float(np.sum(pnl))}
    return rows

def summarize(sym, df, cuts, p, elapsed=0.0):
    y = np.array([1 if df["close"].iloc[c] > df["close"].iloc[c - 1] else 0 for c in cuts])
    mom = np.array([np.sign(df["close"].iloc[c - 1] - df["close"].iloc[c - 4]) for c in cuts])
    mom_ok = mom != 0
    res = {
        "windows": len(cuts), "elapsed_s": round(elapsed, 1),
        "kronos": metrics(p, y),
        "momentum_accuracy": float(np.mean((mom[mom_ok] > 0) == (y[mom_ok] == 1))) if mom_ok.any() else None,
        "momentum_n": int(mom_ok.sum()),
        "calibration": [],
        "sim_flat_market": simulate(p, y),
    }
    for lo in np.arange(0, 1.0, 0.1):
        m = (p >= lo) & (p < lo + 0.1) if lo < 0.9 else (p >= lo) & (p <= 1.0)
        if m.sum() >= 5:
            res["calibration"].append({"bucket": f"{lo:.1f}-{lo + 0.1:.1f}", "n": int(m.sum()),
                                       "mean_p": float(np.mean(p[m])), "realized": float(np.mean(y[m]))})
    for th in (0.2, 0.3, 0.4):
        m = np.abs(p - 0.5) >= th
        if m.sum():
            res[f"conf_{th}"] = {"n": int(m.sum()), "accuracy": float(np.mean((p[m] > 0.5) == (y[m] == 1)))}
    return res

def cuts_for(df):
    ts = df["timestamps"].values
    return [c for c in range(LOOKBACK, len(df), STRIDE)
            if ts[c] - ts[c - 1] == np.timedelta64(5, "m")]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--assets", default="BTC,ETH")
    ap.add_argument("--recompute", default="")
    args = ap.parse_args()
    global ROUNDS, BATCH
    if args.probe:
        ROUNDS, BATCH = 3, 16

    if args.recompute:
        sym = args.recompute
        df = load_asset(sym)
        arr = np.load(f"data/{sym}_probs.npy")
        cuts = cuts_for(df)
        assert list(arr[:, 0].astype(int)) == cuts, "saved cuts do not match recomputed cuts"
        res = summarize(sym, df, cuts, arr[:, 1])
        with open(f"results_{sym}.json", "w") as f:
            json.dump(res, f, indent=1)
        print(f"Recomputed {sym}: acc={res['kronos']['accuracy']:.3f} brier={res['kronos']['brier']:.3f}")
        return

    from model import Kronos, KronosTokenizer, KronosPredictor
    import torch
    torch.set_num_threads(2)
    print("Loading Kronos-small...", flush=True)
    tok = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
    model = Kronos.from_pretrained("NeoQuasar/Kronos-small")
    predictor = KronosPredictor(model, tok, device="cpu", max_context=512)

    report = {}
    for sym in args.assets.split(","):
        if os.path.exists(f"data/{sym}_probs.npy") and os.path.exists(f"results_{sym}.json"):
            print(f"{sym}: results already on disk, skipping", flush=True)
            report[sym] = json.load(open(f"results_{sym}.json"))
            continue
        df = load_asset(sym)
        print(f"{sym}: {len(df)} candles {df['timestamps'].iloc[0]} -> {df['timestamps'].iloc[-1]} UTC", flush=True)
        cuts = cuts_for(df)
        if args.probe:
            cuts = cuts[:32]
        print(f"{sym}: {len(cuts)} windows", flush=True)
        t0 = time.time()
        p = kronos_probs(predictor, df, cuts, tag=sym)
        elapsed = time.time() - t0
        partial = f"data/{sym}_partial.npz"
        if os.path.exists(partial):
            os.remove(partial)
        y = np.array([1 if df["close"].iloc[c] > df["close"].iloc[c - 1] else 0 for c in cuts])
        np.save(f"data/{sym}_probs.npy", np.column_stack([cuts, p, y]))
        res = summarize(sym, df, cuts, p, elapsed)
        with open(f"results_{sym}.json", "w") as f:
            json.dump(res, f, indent=1)
        report[sym] = res
        print(json.dumps({sym: res}, indent=1), flush=True)

    with open("results_big.json", "w") as f:
        json.dump(report, f, indent=1)
    print("Saved results_big.json")

if __name__ == "__main__":
    main()
