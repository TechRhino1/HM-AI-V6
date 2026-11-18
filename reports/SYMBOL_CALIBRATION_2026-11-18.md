# Symbol calibration on real MT5 data — 2026-11-18

Data: 730 days of XM demo (`XMGlobal-MT5 5`) bars, fetched with `tools/fetch_real_data.py`; bar times are converted to UTC (spring-forward duplicate bars removed).
Method: `tools/calibrate_winrate.py --days 730 --wide-grid`, purged 4-fold walk-forward, with real spread and commission. Profiles are in `config/winrate_profiles.json`.

## Deployment gate
`RiskEngine.authorize_execution` now refuses any symbol whose profile has out-of-sample (OOS) expectancy below **+0.05R** or fewer than **100** OOS trades (`jarvis/backtesting/exit_geometry.py: deployment_refusal`). Live exits use the same geometry the OOS number was measured with. The verdicts are served at `/api/calibration/deployment` and shown in the dashboard's Performance tab.

| Symbol | OOS trades | OOS win rate | OOS expectancy | Gate |
|---|---:|---:|---:|---|
| XAUUSD | 960 | 58.0% | +0.046R | blocked: expectancy below +0.05R |
| EURUSD | 77 | 31.2% | +0.040R | blocked |
| GBPUSD | 60 | 53.3% | +0.229R | blocked: too few trades |
| USDJPY | 45 | 40.0% | +0.133R | blocked: too few trades |
| USDCAD | 146 | 68.5% | −0.030R | blocked: negative (old profile claimed +0.358R, so it was overfit) |
| BTCUSD | 36 | 36.1% | −0.123R | blocked |
| ETHUSD | 14 | 35.7% | +0.108R | blocked: too few trades |
| SOLUSD | 6 | 33.3% | −0.144R | blocked |

**Result: no symbol passes, so the main engine places no new orders.** This matches the live record (PF 0.49) and the no-gate replay (−0.024R/trade). The engine's signals have no measurable edge after costs.

## Caveats
- `oos_trades` counts cached scan candidates the policy would take, not trades the full live engine takes; engine-backed numbers (`tools/engine_backed_calibration.py`) would be stricter.
- GBPUSD, USDJPY and ETHUSD are positive but on 14–60 trades. They are candidates to re-check as more data accrues, not evidence of an edge.
- At $520 equity, XAUUSD, US30 and NAS100 cannot fit a minimum lot inside the risk cap anyway (`reports/MT5_DATA_AUDIT_2026-11-18.md`).
- The trend router (Donchian/TSMOM forward tests, `FT_` trades) is a separate demo-only path and is not blocked by this gate. Its trades are now isolated from the main daily cap, circuit breaker, learning and stop edits.

## Re-running
Re-calibrate (for example weekly) with:

    python tools/fetch_real_data.py --days 730
    python tools/scan_signals.py --days 730
    python tools/calibrate_winrate.py --days 730 --wide-grid

A symbol unblocks automatically once its profile reaches the thresholds. The thresholds are constants in `exit_geometry.py` (`MIN_OOS_EXPECTANCY_R`, `MIN_OOS_TRADES`).
