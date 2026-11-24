# Exit research on live trades 2026-11-24

441 closed live demo trades, real MT5 M1 bars (48 h each), replayed through `evaluate_exit`. R per trade; pessimistic intrabar order (adverse before favourable). The legacy core excludes the monitor's live-only layers, which only the `actual` row includes.

| Exits | Total R | Avg R | Win % | 1st half | 2nd half | crypto | metals | indices | FX |
|---|---|---|---|---|---|---|---|---|---|
| actual | -142.9 | -0.324 | 33 | -124.0 | -18.8 | -48.2 | -25.9 | -1.9 | -66.8 |
| fixed stop/target | -22.0 | -0.050 | 31 | -108.2 | +86.3 | +46.5 | -22.4 | -6.0 | -40.1 |
| legacy core | +172.2 | +0.391 | 50 | +131.9 | +40.3 | +25.1 | +35.2 | -2.3 | +114.2 |
| institutional lock | +101.8 | +0.231 | 49 | +57.9 | +43.8 | +31.7 | +49.3 | -2.8 | +23.6 |
