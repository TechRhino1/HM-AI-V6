# Calibration report 2026-11-19

Out-of-sample (purged walk-forward) results on real candles, from `config/winrate_profiles.json`.
PSR = P(Sharpe > 0). DSR deflates that for the number of configurations tried; new strategies need DSR >= 0.9 to go live. Min TRL = trades needed for PSR 95%.

| Symbol | OOS trades | Exp R | Total R | Win % | PF | In-sample max DD R | PSR | DSR | Min TRL | Trials | Live | Reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AUDUSD | 79 | -0.140 | -11.1 | 55.7 | 0.65 | 17.0 | 0.04 | 0.00 | n/a | 320 | no | EXPECTANCY_GATE: AUDUSD out-of-sample -0.140R over 79 trades (needs >= +0.015R over >= 25) |
| BTCUSD | 33 | -0.158 | -5.2 | 33.3 | 0.66 | 6.8 | 0.21 | 0.05 | n/a | 320 | no | EXPECTANCY_GATE: BTCUSD out-of-sample -0.158R over 33 trades (needs >= +0.020R over >= 10) |
| ETHUSD | 10 | +0.068 | +0.7 | 30.0 | 1.14 | 5.4 | 0.56 | 0.31 | 910 | 320 | yes | clears asset-class hurdle |
| EURUSD | 73 | +0.045 | +3.3 | 34.2 | 1.09 | 12.4 | 0.62 | 0.19 | 2007 | 320 | yes | clears asset-class hurdle |
| GBPUSD | 26 | +0.001 | +0.0 | 50.0 | 1.00 | 8.6 | 0.50 | 0.25 | 12353321 | 320 | no | EXPECTANCY_GATE: GBPUSD out-of-sample +0.001R over 26 trades (needs >= +0.015R over >= 25) |
| GER40 | 64 | +0.072 | +4.6 | 34.4 | 1.11 | 13.7 | 0.65 | 0.23 | 1112 | 320 | yes | clears asset-class hurdle |
| NAS100 | 237 | -0.009 | -2.1 | 75.1 | 0.96 | 12.8 | 0.40 | 0.01 | n/a | 320 | no | EXPECTANCY_GATE: NAS100 out-of-sample -0.009R over 237 trades (needs >= +0.020R over >= 30) |
| NZDUSD | 52 | +0.024 | +1.2 | 36.5 | 1.04 | 6.1 | 0.55 | 0.13 | 8695 | 320 | yes | clears asset-class hurdle |
| SOLUSD | 26 | +0.306 | +8.0 | 38.5 | 2.56 | 4.7 | 0.96 | 0.70 | 23 | 320 | yes | clears asset-class hurdle |
| UK100 | 60 | +0.089 | +5.3 | 36.7 | 1.24 | 14.9 | 0.76 | 0.39 | 311 | 320 | yes | clears asset-class hurdle |
| US30 | 39 | +0.088 | +3.5 | 46.2 | 1.18 | 9.7 | 0.68 | 0.35 | 461 | 320 | yes | clears asset-class hurdle |
| USDCAD | 90 | -0.000 | -0.0 | 74.4 | 1.00 | 6.8 | 0.50 | 0.02 | n/a | 320 | no | EXPECTANCY_GATE: USDCAD out-of-sample -0.000R over 90 trades (needs >= +0.015R over >= 25) |
| USDCHF | 63 | +0.055 | +3.5 | 65.1 | 1.23 | 11.1 | 0.75 | 0.36 | 368 | 320 | yes | clears asset-class hurdle |
| USDJPY | 28 | -0.397 | -11.1 | 17.9 | 0.48 | 23.1 | 0.09 | 0.02 | n/a | 320 | no | EXPECTANCY_GATE: USDJPY out-of-sample -0.397R over 28 trades (needs >= +0.015R over >= 25) |
| XAGUSD | 761 | +0.091 | +69.2 | 49.1 | 1.18 | 27.7 | 0.98 | 0.00 | 531 | 320 | yes | clears asset-class hurdle |
| XAUUSD | 959 | +0.041 | +39.4 | 57.7 | 1.11 | 26.7 | 0.93 | 0.01 | 1144 | 320 | yes | clears asset-class hurdle |

Live-eligible: 10/16 (ETHUSD, EURUSD, GER40, NZDUSD, SOLUSD, UK100, US30, USDCHF, XAGUSD, XAUUSD).
Geometry per symbol: AUDUSD `tp1_beoff_pc0.5x0.5_troff@2_mb48_s0.3512`; BTCUSD `tp2.5_be1_pcoffx0.5_troff@2_mb48_s0.50564`; ETHUSD `tp2.5_beoff_pcoffx0.5_troff@2_mb48_s0.54`; EURUSD `tp2.5_beoff_pcoffx0.5_troff@2_mb24_s0.4555`; GBPUSD `tp2_beoff_pcoffx0.5_troff@2_mb24_s0.3775`; GER40 `tp2.5_beoff_pcoffx0.5_troff@2_mb48_s0.4442`; NAS100 `tp0.4_beoff_pcoffx0.5_troff@2_mb48_s0.41`; NZDUSD `tp2.5_beoff_pcoffx0.5_troff@2_mb48_s0.3751`; SOLUSD `tp2_beoff_pcoffx0.5_troff@2_mb48_s0.481275`; UK100 `tp2.5_beoff_pc0.5x0.5_troff@2_mb48_s0.3`; US30 `tp2_beoff_pcoffx0.5_troff@2_mb24_s0.3765`; USDCAD `tp0.4_beoff_pcoffx0.5_troff@2_mb48_s0.4921`; USDCHF `tp0.75_beoff_pc0.5x0.5_troff@2_mb48_s0.4199`; USDJPY `tp2.5_beoff_pcoffx0.5_troff@2_mb48_s0.3637`; XAGUSD `tp2.5_be1_pcoffx0.5_troff@2_mb24_s0.4373`; XAUUSD `tp1.5_beoff_pc0.5x0.5_troff@2_mb24_s0.34`
