# Live-takeable calibration 2026-11-23

Question: what is the out-of-sample edge of the trades the **legacy live path** actually takes?

Same real MT5 H1 bars (730 days), calibrator and cost model as `reports/calibration_2026-11-19.md`, but only on rows live dispatch would trade:
- an EXECUTE, or a WAIT the arbiter promotes (`opportunity_arbiter.is_exec_ready`);
- outside the session blackout and profile window (`signal_scan.live_hour_vetoes`);
- LIMIT orders re-priced, and dropped when unfilled, as `execution_engine` handles them (`signal_scan.apply_limit_fills`). H1 bars can't time the 10-40 min order TTL, so fills are an upper bound.

Run: `tools/calibrate_winrate.py --days 730 --wide-grid --live-takeable`, written to a scratch file and **not deployed**.

| Symbol | Takeable after fills / all reads | Current profile: OOS n, exp R, clears | Live-takeable OOS n | exp R | total R | PSR | DSR | clears hurdle |
|---|---|---|---|---|---|---|---|---|
| AUDUSD | 72/11982 | 79, -0.140, no | 7 | +0.346 | +2.4 | 0.74 | 0.29 | no |
| BTCUSD | 199/17085 | 33, -0.158, no | 2 | +0.989 | +2.0 | 0.00 | 0.00 | no |
| ETHUSD | 120/17157 | 10, +0.068, yes | 5 | +0.723 | +3.6 | 0.91 | 0.58 | no |
| EURUSD | 183/12030 | 73, +0.045, yes | 8 | -0.119 | -1.0 | 0.39 | 0.15 | no |
| GBPUSD | 200/12024 | 26, +0.001, no | 25 | +0.374 | +9.3 | 0.92 | 0.43 | yes |
| GER40 | 107/11172 | 64, +0.072, yes | 16 | +0.081 | +1.3 | 0.70 | 0.15 | no |
| NAS100 | 77/11419 | 237, -0.009, no | 20 | +0.014 | +0.3 | 0.52 | 0.08 | no |
| NZDUSD | 350/12018 | 52, +0.024, yes | 24 | -0.021 | -0.5 | 0.43 | 0.04 | no |
| SOLUSD | 29/17092 | 26, +0.306, yes | 3 | +0.072 | +0.2 | 0.62 | 0.24 | no |
| UK100 | 65/11074 | 60, +0.089, yes | 12 | +0.015 | +0.2 | 0.52 | 0.05 | no |
| US30 | 146/11451 | 39, +0.088, yes | 11 | -0.042 | -0.5 | 0.46 | 0.21 | no |
| USDCAD | 271/11928 | 90, -0.000, no | 32 | +0.108 | +3.4 | 0.69 | 0.12 | yes |
| USDCHF | 164/12068 | 63, +0.055, yes | 27 | +0.031 | +0.8 | 0.61 | 0.05 | yes |
| USDJPY | 93/12023 | 28, -0.397, no | 0 | +0.000 | +0.0 | 0.00 | 0.00 | no |
| XAGUSD | 201/11526 | 761, +0.091, yes | 22 | -0.019 | -0.4 | 0.44 | 0.05 | no |
| XAUUSD | 267/11509 | 959, +0.041, yes | 17 | +0.045 | +0.8 | 0.59 | 0.19 | no |

## Reading
- Live takes 0.2-3% of the directional reads the original calibration validated, so each symbol has 0-32 out-of-sample trades. At that size no result can be told apart from luck: every DSR is at most 0.43.
- Three symbols clear the asset-class hurdle on the live-takeable set: GBPUSD, USDCAD and USDCHF (all FX, all DSR below 0.5).
- **Not deployed.** `config/winrate_profiles.json` keeps the all-directional profiles. They describe exactly what the new CALIBRATED_ROUTE trades (market fill, hand gates off). On the legacy path they act only as an extra veto, which cannot make it trade worse. Swapping in these 0-32-trade profiles would switch the validated route off on noise.
- What this does settle: the legacy gate stack is not a measured edge on any symbol. Which path keeps trading a symbol is decided live by `session_leads.beats_live_verdict` (strategy CALIBRATED_POLICY vs the rest in `/api/analytics/performance?by=strategy`), once each path has 30+ closed trades there.
