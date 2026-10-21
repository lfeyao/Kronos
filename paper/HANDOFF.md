# Handoff — Kronos + LightGBM paper-trading logger

**From:** Capy (Muse VM) · **Date:** 2026-10-21 · **Status: STOPPED on the VM at Dai's order (2026-10-21 06:41 PT). The other agent takes over running it.**

## What this is

A live paper-trading evaluation of two forecasting models against the market itself, on Polymarket's 5-minute BTC and ETH up/down markets:

- **Kronos** (open-source candlestick foundation model, Kronos-small) → P(up) per window
- **LightGBM** (locally trained classifier) → P(up) per window
- **The market** (Polymarket's own ask prices) as the benchmark

Every 5-minute window, for BTC and ETH: each model's P(up) is logged alongside the market's up/down asks. When a model's probability beats the ask by an **edge ≥ 0.08**, the logger takes a **$10 paper trade**. Windows settle from Polymarket gamma `outcomePrices`. Everything is recorded in SQLite; a daily digest reports trades, P&L, and a model-vs-market scorecard (accuracy + Brier).

## Standing rules (do not bend)

- **PAPER ONLY. Never place a real order, never move funds.** No real-money betting on either model without Dai's explicit new authorization — none exists.
- **Stale-window guard:** never log or enter a window more than 90 seconds old.
- Dai places any real prediction-market bets himself, by hand.

## Why it's moving off the VM

The Muse VM is replaced frequently, and every replacement wipes `/etc` — which deletes the systemd unit and env file and kills the logger. It happened **5 times in ~24 hours** on Oct 20–21. A watchdog cron reinstalled it each time, but each wipe lost up to ~6 hours of windows (only 65 of 576 windows were logged in the final 24h). A stable always-on machine fixes this properly.

## What was stopped (VM, 2026-10-21)

- `kronos-paper.service` (systemd): stopped and disabled (`inactive` / `disabled`, verified).
- Cron `kronos-paper-watchdog` (every 6h, auto-repair): **disabled**.
- Cron `kronos-paper-daily-digest` (daily 05:42 PT): **disabled**.
- Data and code are untouched and remain on the VM at the paths below until copied.

## Components (VM paths — adapt on the new machine)

| Piece | Path |
|---|---|
| Logger daemon | `~/workspace/kronos/paper/paper_trader.py` |
| Digest script | `~/workspace/kronos/paper/digest.py` |
| Database (take a copy — history lives here) | `~/workspace/kronos/paper/paper.db` |
| Trained LightGBM models | `~/workspace/kronos/paper/lgbm_BTC.pkl`, `lgbm_ETH.pkl` (retrains automatically when >24h old) |
| systemd unit (reference) | `~/workspace/kronos/paper/kronos-paper.service` |
| Python env | `~/workspace/venvs/kronos` (Kronos fork: github.com/lfeyao/Kronos, checked out at `~/workspace/kronos`) |
| Log | `~/workspace/kronos/paper/paper_trader.log` |

Database schema: `windows` (per-window model + market probabilities, settlement) and `trades` (id, asset, window_start, model, side, price, stake, model_p, edge, pnl, won).

## How to run it

1. Copy the `paper/` directory **including paper.db** (keeps the all-time stats continuous), plus the Kronos checkout and a Python env with its dependencies.
2. Environment the daemon needs:
   - `HOME` set to the running user's home (Hugging Face cache lives under `~/.cache/huggingface`; Kronos-small weights must be present or downloaded — downloads need `HF_HUB_DISABLE_XET=1`).
   - `HF_HUB_OFFLINE=1` at runtime (prevents per-window network checks to HF).
   - Egress proxy variables if the host needs them (`http_proxy`, `https_proxy`, `all_proxy`, `no_proxy`, both cases) — on the VM these were supplied via an EnvironmentFile (chmod 600).
   - Network access to Polymarket (gamma API for prices/settlement) and the candle data source the script uses.
3. Run: `<venv>/bin/python -u paper/paper_trader.py` from the kronos working directory, under launchd/systemd with auto-restart (`Restart=always`, 15s delay worked fine).
4. Daily digest: run `<venv>/bin/python paper/digest.py` once a day; it prints the full digest (logger health, 24h trades/P&L per model, 24h scorecard, all-time totals, biggest settled trades) to stdout.

## State at handoff (digest run 2026-10-21, ~06:45 PT, after the final stop)

- Windows logged last 24h: 65 of 576 (VM-wipe gaps); **80 settled windows all-time, 114 paper trades, 0 open**.
- All-time: **kronos** 61 settled, win 44%, **P&L +$82.89 on $610 staked (ROI +13.6%)**, acc 57.5%, Brier 0.285 · **lgbm** 53 settled, win 34%, **P&L +$34.98 on $530 staked (ROI +6.6%)**, acc 48.8%, Brier 0.253 · **market** acc 65.3%, Brier 0.233 — the market still out-scores both models on Brier.
- Last trades settled around the 2026-10-21 11:30 UTC window cluster (several large paper wins at 0.20–0.26 prices flatter the recent numbers).

## Read the results with care

- The sample is small (80 windows) and the recent P&L is dominated by a handful of cheap-price wins. The earlier full **backtest verdict stands**: Kronos showed no 5-minute directional edge (~50% accuracy, anti-calibrated; vs real Polymarket prices 41.4% accuracy / Brier 0.351 vs the market's 58.6% / 0.250). LightGBM backtested at 53.8% (BTC) / 56.4% (ETH) accuracy, Brier ~0.248 — calibrated but unproven. Backtest detail: `~/workspace/kronos/results_*.json`.
- This logger exists to keep testing that verdict against live data, not to overturn it on 80 windows.

## Loose ends

- The tracked goal on Capy's side is `goal_6b066df01bbf` (Kronos/LightGBM paper-trading logger); its watchdog/digest history is in `~/workspace/goals/kronos-lightgbm-paper-trading-logger/`.
- If the logger ever runs on the VM again, the watchdog's repair recipe is: copy the unit from `~/workspace/kronos/paper/kronos-paper.service` to `/etc/systemd/system/`, regenerate `/etc/kronos-paper.env` from the process proxy vars (chmod 600), `systemctl daemon-reload && systemctl enable --now kronos-paper.service`, verify `is-active` + a fresh startup line in the log.
