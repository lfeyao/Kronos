"""Compare Kronos P(up) vs actual Polymarket 5-min market prices for recent backtest windows.

For each backtest cut in the last ~72h: the market slug timestamp = the target candle's
open time (unix). Market's near-open implied P(up) = first CLOB price point at/after the
window start for the Up token. Outcome scored on the MARKET's own resolution
(gamma outcomePrices), since that is what a bet settles on.
"""
import json, time, urllib.request
import numpy as np
import pandas as pd

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "kronos-check"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)

rows = []
for sym, asset in (("BTC", "btc"), ("ETH", "eth")):
    df = pd.read_csv(f"data/{sym}.csv", parse_dates=["timestamps"])
    arr = np.load(f"data/{sym}_probs.npy")
    ts = df["timestamps"]
    cutoff = ts.iloc[-1] - pd.Timedelta(hours=72)
    for cut_f, p, y in arr:
        cut = int(cut_f)
        wstart = ts.iloc[cut]  # target candle open (UTC, naive)
        if wstart < cutoff:
            continue
        unix = int(wstart.tz_localize("UTC").timestamp())
        try:
            data = get(f"https://gamma-api.polymarket.com/markets?slug={asset}-updown-5m-{unix}&closed=true")
            if not data:
                continue
            m = data[0]
            finals = json.loads(m["outcomePrices"])  # [Up, Down]
            mkt_up = 1 if float(finals[0]) > 0.5 else 0
            tok = json.loads(m["clobTokenIds"])[0]
            h = get(f"https://clob.polymarket.com/prices-history?market={tok}&startTs={unix - 900}&endTs={unix + 600}&fidelity=1")
            hist = [pt for pt in h.get("history", []) if pt["t"] >= unix - 60]
            if not hist:
                continue
            open_px = hist[0]["p"]
            rows.append({"asset": sym, "window_utc": str(wstart), "kronos_p": float(p),
                         "market_open_p": float(open_px), "outcome_up_market": mkt_up,
                         "outcome_up_coinbase": int(y),
                         "agree": int(mkt_up == int(y))})
            time.sleep(0.15)
        except Exception as e:
            print(f"{sym} {wstart}: {e}")
    print(f"{sym} done, total rows {len(rows)}")

with open("results_market.json", "w") as f:
    json.dump(rows, f, indent=1)

if rows:
    kp = np.array([r["kronos_p"] for r in rows]); mp = np.array([r["market_open_p"] for r in rows])
    y = np.array([r["outcome_up_market"] for r in rows])
    print(f"\nMatched windows: {len(rows)}  (Kronos/Coinbase outcome agrees with market resolution on {np.mean([r['agree'] for r in rows]):.1%})")
    print(f"Kronos  : acc {np.mean((kp > 0.5) == (y == 1)):.3f}  brier {np.mean((kp - y) ** 2):.3f}")
    print(f"Market  : acc {np.mean((mp > 0.5) == (y == 1)):.3f}  brier {np.mean((mp - y) ** 2):.3f}")
    div = np.abs(kp - mp)
    print(f"Mean |Kronos - market| divergence: {div.mean():.3f}; windows with divergence >= 0.15: {(div >= 0.15).sum()}")
    for r in rows:
        if abs(r["kronos_p"] - r["market_open_p"]) >= 0.15:
            print(f"  {r['asset']} {r['window_utc']}  kronos {r['kronos_p']:.2f} vs market {r['market_open_p']:.2f}  -> {'UP' if r['outcome_up_market'] else 'DOWN'}")
