# Exit research on live trades 2026-11-24

353 closed live demo trades, real MT5 M1 bars (48 h each), replayed through `evaluate_exit`. R per trade; pessimistic intrabar order (adverse before favourable). The legacy core excludes the monitor's live-only layers, which only the `actual` row includes.

| Exits | Total R | Avg R | Win % | 1st half | 2nd half | crypto | metals | indices | FX |
|---|---|---|---|---|---|---|---|---|---|
| actual | -40.0 | -0.113 | 41 | -37.3 | -2.7 | -0.6 | -9.9 | -1.9 | -27.5 |
| fixed stop/target | +50.4 | +0.143 | 38 | -47.3 | +97.8 | +75.7 | -8.9 | -4.4 | -11.9 |
| legacy core | +0.3 | +0.001 | 50 | -39.7 | +40.0 | +20.9 | -11.9 | -1.5 | -7.2 |
| institutional lock | +2.5 | +0.007 | 49 | -40.1 | +42.6 | +22.4 | -11.3 | -2.2 | -6.4 |
| lock + hold list | +55.7 | +0.158 | 45 | -35.6 | +91.3 | +75.7 | -11.3 | -2.2 | -6.4 |

**Correction to the first version of this report (441 trades, lock +101.8R):** 88 rows (all recorded 29 Sep to 7 Oct) carry a stop a fraction of a pip from entry, so ordinary moves scored 50-400R and swamped every total. `load_live_trades` now drops trades whose risk is under 25% of the symbol's median or whose planned target is over 10R. No such rows were recorded after 7 Oct.

## Per symbol: lock vs holding to the original stop/target, by chronological half (R)

| Symbol | n | lock H1 | lock H2 | fixed H1 | fixed H2 |
|---|---|---|---|---|---|
| BTCUSD | 74 | -17.2 | +10.5 | -17.1 | +25.6 |
| ETHUSD | 70 | +13.1 | +10.8 | +36.0 | +15.9 |
| XAUUSD | 62 | -14.5 | +3.2 | -16.2 | +6.2 |
| EURUSD | 60 | -6.3 | -1.9 | -12.8 | +4.7 |
| GBPUSD | 27 | +13.8 | -2.3 | +6.4 | +4.0 |
| SOLUSD | 24 | +7.0 | -1.8 | +17.8 | -3.1 |

Crypto (168 trades) holds to its original stop/target better than the lock in both halves (+36.7 / +38.4 vs +2.9 / +18.5), so `trading.exit_hold_symbols = [BTCUSD, ETHUSD, SOLUSD]`. Gold and FX do not, so they keep the lock.

## Per-symbol parameter search: not adopted

A 160-setting grid (trigger 0.5-1.5R, floor 0-0.5R, trail 0.5-2.0R, partial 0/50%) was fitted on one half and scored on the other. The out-of-sample result was below the plain default for every symbol except ETHUSD, and the two halves picked different settings. With 24-74 trades per symbol, per-symbol tuning fits noise, so it is not shipped.

## What exits cannot fix

XAUUSD, EURUSD and BTCUSD lose in the first half under every exit tested, and ETHBTC (13 trades) loses under all of them. Their losses come from entries, which the live-expectancy quarantine addresses. Across symbols, sells beat buys over this period. That reflects the trend, not a rule to hard-code.

Re-run `python tools/exit_research.py --live-trades <out.md>` after 100+ new trades.
