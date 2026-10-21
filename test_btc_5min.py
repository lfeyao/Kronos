"""Kronos smoke test on BTC 5-minute candles.

1. Pulls ~2,000 recent BTC-USD 5m candles from Coinbase Exchange public API.
2. Walk-forward: at several cut points, sample forecast paths with Kronos-small
   and estimate P(next close > current close); compare with what actually happened.
3. Prints a live P(up) for the next 5-minute candle from the latest data.
"""
import sys, time, json, urllib.request
import pandas as pd
import numpy as np

sys.path.insert(0, ".")
from model import Kronos, KronosTokenizer, KronosPredictor

GRAN = 300  # 5 minutes
URL = "https://api.exchange.coinbase.com/products/{}/candles?granularity=300&start={}&end={}"

def fetch_candles(n=2000, product="BTC-USD"):
    rows, end = [], int(time.time())
    while len(rows) < n:
        start = end - GRAN * 300
        req = urllib.request.Request(URL.format(product,
            pd.to_datetime(start, unit="s", utc=True).isoformat(),
            pd.to_datetime(end, unit="s", utc=True).isoformat()),
            headers={"User-Agent": "kronos-test"})
        batch = None
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    batch = json.load(r)
                break
            except Exception:
                if attempt == 4:
                    raise
                time.sleep(2 * (attempt + 1))
        if not batch:
            break
        rows.extend(batch)
        end = batch[-1][0] - GRAN
        time.sleep(0.35)
    df = pd.DataFrame(rows, columns=["ts", "low", "high", "open", "close", "volume"])
    df = df.drop_duplicates("ts").sort_values("ts")
    df["timestamps"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_localize(None)
    return df[["timestamps", "open", "high", "low", "close", "volume"]].reset_index(drop=True)

def p_up(predictor, df, cut, pred_len=1, samples=30):
    x = df.iloc[cut - LOOKBACK:cut]
    y_ts = df.iloc[cut:cut + pred_len]["timestamps"]
    if len(y_ts) < pred_len:  # live call: synthesize future 5-min timestamps
        last = x["timestamps"].iloc[-1]
        y_ts = pd.Series([last + pd.Timedelta(minutes=5 * (i + 1)) for i in range(pred_len)])
    preds = []
    for _ in range(samples):
        out = predictor.predict(df=x[["open", "high", "low", "close", "volume"]],
                                x_timestamp=x["timestamps"], y_timestamp=y_ts,
                                pred_len=pred_len, T=1.0, top_p=0.9, sample_count=1)
        preds.append(out["close"].iloc[-1])
    return float(np.mean(np.array(preds) > x["close"].iloc[-1]))

LOOKBACK = 200

def main():
    print("Fetching BTC-USD 5m candles from Coinbase...")
    df = fetch_candles()
    print(f"Got {len(df)} candles: {df['timestamps'].iloc[0]} -> {df['timestamps'].iloc[-1]} UTC")
    print("Loading Kronos-small + tokenizer (downloads weights from Hugging Face)...")
    tok = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
    model = Kronos.from_pretrained("NeoQuasar/Kronos-small")
    predictor = KronosPredictor(model, tok, device="cpu", max_context=512)

    # Walk-forward backtest: 24 cut points spaced 12 candles (1h) apart, 5-min horizon
    cuts = list(range(len(df) - 320, len(df) - 12, 12))[:24]
    print(f"\nBacktest: {len(cuts)} windows, lookback={LOOKBACK}, horizon=1 candle (5 min), 30 sampled paths each")
    hits_brier, rows = [], []
    for c in cuts:
        p = p_up(predictor, df, c, pred_len=1)
        actual_up = df["close"].iloc[c] > df["close"].iloc[c - 1]
        hits_brier.append(((1.0 if actual_up else 0.0) - p) ** 2)
        rows.append((str(df["timestamps"].iloc[c]), round(p, 2), "UP" if actual_up else "DOWN",
                     "hit" if (p > 0.5) == actual_up else "miss"))
    for r in rows:
        print(f"  {r[0]}  P(up)={r[1]:.2f}  actual={r[2]:4s}  {r[3]}")
    acc = np.mean([r[3] == "hit" for r in rows])
    print(f"Directional accuracy (P>0.5 call): {acc:.1%}   Brier score: {np.mean(hits_brier):.3f}  (0.25 = coin flip)")

    # Live forecast for the next 5-minute candle
    p_live = p_up(predictor, df, len(df), pred_len=1)
    last = df.iloc[-1]
    print(f"\nLIVE: last closed candle {last['timestamps']} UTC close ${last['close']:,.2f}")
    print(f"Kronos next-5-min P(up) = {p_live:.2f}")

if __name__ == "__main__":
    main()
