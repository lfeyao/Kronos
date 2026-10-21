"""Paper-trading summary: coverage, per-model P&L, Brier vs the market."""
import os, sqlite3
import numpy as np

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper.db")
con = sqlite3.connect(DB)

n_win = con.execute("SELECT COUNT(*) FROM windows").fetchone()[0]
n_set = con.execute("SELECT COUNT(*) FROM windows WHERE outcome_up IS NOT NULL").fetchone()[0]
rng = con.execute("SELECT datetime(MIN(window_start),'unixepoch'), datetime(MAX(window_start),'unixepoch') FROM windows").fetchone()
print(f"Windows logged: {n_win} ({n_set} settled)  {rng[0]} -> {rng[1]} UTC")

for name, col in (("kronos", "kronos_p"), ("lgbm", "lgbm_p")):
    rows = con.execute(f"SELECT {col}, outcome_up FROM windows WHERE outcome_up IS NOT NULL AND {col} IS NOT NULL").fetchall()
    if rows:
        p = np.array([r[0] for r in rows]); y = np.array([r[1] for r in rows])
        acc = np.mean((p > 0.5) == (y == 1))
        print(f"{name}: settled-window acc {acc:.1%}  brier {np.mean((p - y) ** 2):.3f}  (n={len(rows)})")
mkt = con.execute("SELECT gamma_up, outcome_up FROM windows WHERE outcome_up IS NOT NULL AND gamma_up IS NOT NULL").fetchall()
if mkt:
    p = np.array([r[0] for r in mkt]); y = np.array([r[1] for r in mkt])
    print(f"market (gamma price): acc {np.mean((p > 0.5) == (y == 1)):.1%}  brier {np.mean((p - y) ** 2):.3f}  (n={len(mkt)})")

for model in ("kronos", "lgbm"):
    t = con.execute("SELECT COUNT(*), SUM(won), SUM(pnl), SUM(stake) FROM trades WHERE model=? AND pnl IS NOT NULL", (model,)).fetchone()
    open_n = con.execute("SELECT COUNT(*) FROM trades WHERE model=? AND pnl IS NULL", (model,)).fetchone()[0]
    if t[0]:
        print(f"{model}: {t[0]} settled trades | win {t[1] / t[0]:.1%} | PnL ${t[2]:+.2f} on ${t[3]:.0f} staked (ROI {100 * t[2] / t[3]:+.1f}%) | {open_n} open")
    else:
        print(f"{model}: no settled trades yet ({open_n} open)")

print("\nLast 10 trades:")
for r in con.execute("""SELECT datetime(window_start,'unixepoch'), asset, model, side, price, model_p, pnl
                        FROM trades ORDER BY window_start DESC LIMIT 10"""):
    pnl = f"${r[6]:+.2f}" if r[6] is not None else "open"
    print(f"  {r[0]} UTC {r[1]} {r[2]:6s} {r[3]:4s} @ {r[4]:.2f} (model {r[5]:.2f}) -> {pnl}")
