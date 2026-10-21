"""Live paper-trading logger: Kronos + LightGBM vs Polymarket 5-minute markets.

Every 5-min window (BTC, ETH):
  - P(up) from Kronos-small (20 sampled paths) and LightGBM (features model,
    retrained daily on trailing ~62 days of Coinbase 5m candles).
  - Market prices from the Polymarket CLOB book for that window's market.
  - Paper trade per model when its probability beats the ask by >= EDGE:
    $10 stake at the ask. NO real orders are ever placed.
  - After the window closes, settle from the market's own resolution
    (gamma outcomePrices) and book paper P&L.
State: paper/paper.db (SQLite). Models: paper/lgbm_{BTC,ETH}.pkl.
Run: python paper_trader.py [--once]
"""
import sys, os, json, time, pickle, sqlite3, logging, argparse
import urllib.request
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # ~/workspace/kronos
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from test_btc_5min import fetch_candles          # Coinbase, with retries
from lightgbm_backtest import features           # same feature fn as the backtest
from backtest_big import LOOKBACK

ASSETS = ("BTC", "ETH")
EDGE = 0.08
STAKE = 10.0
KRONOS_ROUNDS = 20
DB = os.path.join(BASE, "paper", "paper.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(),
                              logging.FileHandler(os.path.join(BASE, "paper", "paper_trader.log"))])
log = logging.getLogger("paper")

def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "paper-trader"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)

# ---------- data ----------
def refresh_candles(sym):
    """Fetch the last ~260 candles and merge into data/{sym}.csv. Returns the full df."""
    path = f"data/{sym}.csv"
    fresh = fetch_candles(260, product=f"{sym}-USD")
    if os.path.exists(path):
        old = pd.read_csv(path, parse_dates=["timestamps"])
        df = pd.concat([old, fresh]).drop_duplicates("timestamps").sort_values("timestamps")
    else:
        df = fresh
    df = df.reset_index(drop=True)
    df.to_csv(path, index=False)
    return df

def context_for(df, T):
    """Return (x_df, x_ts, last_close) for the window starting at unix T, or None.
    Context = last LOOKBACK complete candles, the newest closing exactly at T."""
    target_open = pd.to_datetime(T - 300, unit="s", utc=True).tz_localize(None)
    idx = df.index[df["timestamps"] == target_open]
    if len(idx) == 0 or idx[0] + 1 < LOOKBACK:
        return None
    cut = int(idx[0]) + 1  # rows [cut-LOOKBACK, cut) are the context; row cut-1 closes at T
    x = df.iloc[cut - LOOKBACK:cut]
    return x[["open", "high", "low", "close", "volume"]], x["timestamps"], float(x["close"].iloc[-1]), cut

# ---------- LightGBM ----------
def lgbm_path(sym):
    return os.path.join(BASE, "paper", f"lgbm_{sym}.pkl")

def train_lgbm(sym, df):
    import lightgbm as lgb
    ts = df["timestamps"].values
    cuts = [c for c in range(LOOKBACK, len(df), 30)
            if ts[c] - ts[c - 1] == np.timedelta64(5, "m")]
    X = pd.DataFrame([features(df, c) for c in cuts])
    y = np.array([1 if df["close"].iloc[c] > df["close"].iloc[c - 1] else 0 for c in cuts])
    n_val = max(50, int(len(cuts) * 0.15))
    model = lgb.LGBMClassifier(objective="binary", n_estimators=800, learning_rate=0.03,
                               num_leaves=31, min_child_samples=40, subsample=0.8,
                               colsample_bytree=0.8, reg_lambda=1.0, verbose=-1)
    model.fit(X.iloc[:-n_val], y[:-n_val], eval_set=[(X.iloc[-n_val:], y[-n_val:])],
              callbacks=[lgb.early_stopping(60, verbose=False)])
    with open(lgbm_path(sym), "wb") as f:
        pickle.dump({"model": model, "cols": list(X.columns), "trained_at": time.time()}, f)
    log.info(f"{sym} LightGBM retrained on {len(cuts)} windows")
    return model, list(X.columns)

def load_lgbm(sym):
    p = lgbm_path(sym)
    if not os.path.exists(p):
        return None, None, 0
    with open(p, "rb") as f:
        d = pickle.load(f)
    return d["model"], d["cols"], d["trained_at"]

# ---------- market ----------
def market_prices(asset, T):
    """(up_bid, up_ask, down_bid, down_ask, gamma_up) or None if market not found."""
    slug = f"{asset.lower()}-updown-5m-{T}"
    data = http_json(f"https://gamma-api.polymarket.com/markets?slug={slug}")
    if not data:
        return None
    m = data[0]
    gamma_up = float(json.loads(m["outcomePrices"])[0])
    toks = json.loads(m["clobTokenIds"])
    out = {"gamma_up": gamma_up}
    for side, tok in (("up", toks[0]), ("down", toks[1])):
        try:
            book = http_json(f"https://clob.polymarket.com/book?token_id={tok}")
            bids = [float(b["price"]) for b in book.get("bids", [])]
            asks = [float(a["price"]) for a in book.get("asks", [])]
            out[f"{side}_bid"] = max(bids) if bids else None
            out[f"{side}_ask"] = min(asks) if asks else None
        except Exception:
            out[f"{side}_bid"] = out[f"{side}_ask"] = None
        if out[f"{side}_ask"] is None:  # fallback to gamma last price
            p = gamma_up if side == "up" else 1 - gamma_up
            out[f"{side}_bid"] = out[f"{side}_ask"] = p
    return out

def market_outcome(asset, T):
    slug = f"{asset.lower()}-updown-5m-{T}"
    data = http_json(f"https://gamma-api.polymarket.com/markets?slug={slug}&closed=true")
    if not data or not data[0].get("closed"):
        return None
    finals = json.loads(data[0]["outcomePrices"])
    return 1 if float(finals[0]) > 0.5 else 0

# ---------- db ----------
def db():
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("""CREATE TABLE IF NOT EXISTS windows(
        asset TEXT, window_start INTEGER, logged_at REAL, kronos_p REAL, lgbm_p REAL,
        up_bid REAL, up_ask REAL, down_bid REAL, down_ask REAL, gamma_up REAL,
        outcome_up INTEGER, PRIMARY KEY(asset, window_start))""")
    con.execute("""CREATE TABLE IF NOT EXISTS trades(
        id INTEGER PRIMARY KEY, asset TEXT, window_start INTEGER, model TEXT, side TEXT,
        price REAL, stake REAL, model_p REAL, edge REAL, pnl REAL, won INTEGER,
        UNIQUE(asset, window_start, model))""")
    return con

# ---------- cycle ----------
class Trader:
    def __init__(self):
        from model import Kronos, KronosTokenizer, KronosPredictor
        import torch
        torch.set_num_threads(2)
        log.info("Loading Kronos-small...")
        tok = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
        model = Kronos.from_pretrained("NeoQuasar/Kronos-small")
        self.predictor = KronosPredictor(model, tok, device="cpu", max_context=512)
        self.lgbm = {sym: load_lgbm(sym) for sym in ASSETS}
        self.con = db()

    def kronos_probs(self, contexts):
        """contexts: {sym: (x_df, x_ts, last_close, cut)} -> {sym: P(up)}"""
        syms = list(contexts)
        ups = {s: 0 for s in syms}
        y_ts = [pd.Series([pd.to_datetime(T_NEXT, unit="s", utc=True).tz_localize(None)]) for _ in syms]
        for _ in range(KRONOS_ROUNDS):
            outs = self.predictor.predict_batch(
                df_list=[contexts[s][0] for s in syms],
                x_timestamp_list=[contexts[s][1] for s in syms],
                y_timestamp_list=y_ts, pred_len=1, T=1.0, top_p=0.9, sample_count=1, verbose=False)
            for s, o in zip(syms, outs):
                ups[s] += float(o["close"].iloc[-1]) > contexts[s][2]
        return {s: ups[s] / KRONOS_ROUNDS for s in syms}

    def run_window(self, T):
        global T_NEXT
        T_NEXT = T
        contexts, dfs = {}, {}
        for sym in ASSETS:
            try:
                df = refresh_candles(sym)
                dfs[sym] = df
                ctx = context_for(df, T)
                if ctx is None:
                    log.warning(f"{sym} window {T}: candle context unavailable, skipping predictions")
                else:
                    contexts[sym] = ctx
            except Exception as e:
                log.error(f"{sym} candle fetch failed: {e}")
        if not contexts:
            return False
        kp = self.kronos_probs(contexts)
        for sym, ctx in contexts.items():
            # LightGBM (train on first ever run, before predicting)
            model, cols, trained_at = self.lgbm[sym]
            if model is None:
                model, cols = train_lgbm(sym, dfs[sym])
                self.lgbm[sym] = (model, cols, time.time())
            f = features(dfs[sym], ctx[3])
            lp = float(model.predict_proba(pd.DataFrame([f])[cols])[:, 1][0])
            try:
                mp = market_prices(sym, T)
            except Exception as e:
                log.error(f"{sym} market fetch failed: {e}")
                mp = None
            if mp is None:
                log.warning(f"{sym} window {T}: no market found, logging predictions only")
                mp = {"up_bid": None, "up_ask": None, "down_bid": None, "down_ask": None, "gamma_up": None}
            self.con.execute(
                "INSERT OR REPLACE INTO windows VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (sym, T, time.time(), kp[sym], lp, mp["up_bid"], mp["up_ask"],
                 mp["down_bid"], mp["down_ask"], mp["gamma_up"], None))
            for name, p in (("kronos", kp[sym]), ("lgbm", lp)):
                if mp["up_ask"] is None:
                    continue
                e_up, e_dn = p - mp["up_ask"], (1 - p) - mp["down_ask"]
                if max(e_up, e_dn) >= EDGE:
                    side = "up" if e_up >= e_dn else "down"
                    price = mp["up_ask"] if side == "up" else mp["down_ask"]
                    edge = e_up if side == "up" else e_dn
                    self.con.execute(
                        "INSERT OR IGNORE INTO trades(asset,window_start,model,side,price,stake,model_p,edge) VALUES (?,?,?,?,?,?,?,?)",
                        (sym, T, name, side, price, STAKE, p if side == "up" else 1 - p, edge))
                    log.info(f"PAPER {sym} {name}: buy {side} @ {price:.2f} (model {p:.2f}, edge {edge:.2f}) window {T}")
            self.con.commit()
            log.info(f"{sym} window {T}: kronos {kp[sym]:.2f} | lgbm {lp:.2f} | market up ask {mp['up_ask']}")
        return True
        # daily retrain AFTER predictions are logged
        for sym in contexts:
            model, cols, trained_at = self.lgbm[sym]
            if time.time() - trained_at > 24 * 3600:
                try:
                    m2, c2 = train_lgbm(sym, dfs[sym])
                    self.lgbm[sym] = (m2, c2, time.time())
                except Exception as e:
                    log.error(f"{sym} retrain failed: {e}")

    def settle(self):
        cur = self.con.execute(
            "SELECT asset, window_start FROM windows WHERE outcome_up IS NULL AND window_start < ?",
            (int(time.time()) - 300,)).fetchall()
        for sym, T in cur:
            try:
                out = market_outcome(sym, T)
            except Exception:
                continue
            if out is None:
                continue
            self.con.execute("UPDATE windows SET outcome_up=? WHERE asset=? AND window_start=?", (out, sym, T))
            for tid, side, price, stake in self.con.execute(
                    "SELECT id, side, price, stake FROM trades WHERE asset=? AND window_start=? AND pnl IS NULL", (sym, T)):
                won = 1 if (side == "up") == (out == 1) else 0
                pnl = stake * (1.0 / price - 1.0) if won else -stake
                self.con.execute("UPDATE trades SET pnl=?, won=? WHERE id=?", (round(pnl, 2), won, tid))
            self.con.commit()
            log.info(f"settled {sym} window {T}: {'UP' if out else 'DOWN'}")

T_NEXT = None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    tr = Trader()
    if args.once:
        T = int(time.time()) // 300 * 300
        tr.run_window(T)
        tr.settle()
        return
    last = None
    while True:
        try:
            now = time.time()
            T = int(now) // 300 * 300
            if T != last and T + 4 <= now <= T + 90:
                if tr.run_window(T) or now > T + 90:
                    last = T
            elif T != last and now > T + 90:
                last = T  # window too stale to enter honestly; skip it
            tr.settle()
        except Exception as e:
            log.error(f"cycle error: {e}")
        time.sleep(15)

if __name__ == "__main__":
    main()
