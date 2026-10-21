"""Daily paper-trading digest: last-24h activity + all-time scorecard. Prints chat-ready text."""
import os, sqlite3, subprocess, time
import numpy as np

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper.db")
con = sqlite3.connect(DB)
now = int(time.time())
day_ago = now - 24 * 3600

def svc():
    try:
        return subprocess.run(["systemctl", "is-active", "kronos-paper.service"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return "unknown"

def trade_stats(model, since=None):
    q = "SELECT COUNT(*), SUM(won), SUM(pnl), SUM(stake) FROM trades WHERE model=? AND pnl IS NOT NULL"
    args = [model]
    if since:
        q += " AND window_start>=?"
        args.append(since)
    t = con.execute(q, args).fetchone()
    open_q = "SELECT COUNT(*) FROM trades WHERE model=? AND pnl IS NULL"
    open_n = con.execute(open_q, [model]).fetchone()[0]
    if not t[0]:
        return f"  {model}: no settled trades ({open_n} open)"
    return (f"  {model}: {t[0]} settled | win {t[1] / t[0]:.0%} | P&L ${t[2]:+.2f} on ${t[3]:.0f} staked "
            f"(ROI {100 * t[2] / t[3]:+.1f}%) | {open_n} open")

def scorecard(since=None):
    wq = "SELECT COUNT(*) FROM windows WHERE outcome_up IS NOT NULL"
    args = []
    if since:
        wq += " AND window_start>=?"
        args.append(since)
    n = con.execute(wq, args).fetchone()[0]
    if not n:
        return "  no settled windows yet"
    lines = [f"  settled windows: {n}"]
    for name, col in (("kronos", "kronos_p"), ("lgbm", "lgbm_p"), ("market", "gamma_up")):
        q = f"SELECT {col}, outcome_up FROM windows WHERE outcome_up IS NOT NULL AND {col} IS NOT NULL"
        if since:
            q += " AND window_start>=?"
        rows = con.execute(q, args).fetchall()
        if rows:
            p = np.array([r[0] for r in rows]); y = np.array([r[1] for r in rows])
            lines.append(f"  {name}: acc {np.mean((p > 0.5) == (y == 1)):.1%} | brier {np.mean((p - y) ** 2):.3f}")
    return "\n".join(lines)

cov24 = con.execute("SELECT COUNT(*) FROM windows WHERE window_start>=?", (day_ago,)).fetchone()[0]
print("📋 **Paper trading digest** (Polymarket 5-min, BTC+ETH)")
print(f"Logger: {svc()} | windows logged last 24h: {cov24} of 576")
print("\n**Last 24h trades**")
print(trade_stats("kronos", day_ago))
print(trade_stats("lgbm", day_ago))
print("\n**Last 24h scorecard** (vs market's own price)")
print(scorecard(day_ago))
print("\n**All-time**")
print(trade_stats("kronos"))
print(trade_stats("lgbm"))
print(scorecard())
top = con.execute("""SELECT datetime(window_start,'unixepoch'), asset, model, side, price, pnl
                     FROM trades WHERE pnl IS NOT NULL AND window_start>=?
                     ORDER BY ABS(pnl) DESC LIMIT 4""", (day_ago,)).fetchall()
if top:
    print("\n**Biggest settled trades (24h)**")
    for r in top:
        print(f"  {r[0]} UTC {r[1]} {r[2]} {r[3]} @ {r[4]:.2f} -> ${r[5]:+.2f}")
