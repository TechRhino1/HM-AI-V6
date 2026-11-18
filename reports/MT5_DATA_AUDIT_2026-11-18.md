# MT5 data audit — 2026-11-17 20:27 UTC

Server `XMGlobal-MT5 5`, account currency USD, equity 519.86, leverage 1:1000, terminal max bars 100000.

Broker clock: freshest tick − UTC = 7199 s → 2.0 h; `BROKER_TZ` calendar = 2.0 h → **OK**.

## Alias resolution

| canonical | broker | trade_mode | registered |
|---|---|---|---|
| EURUSD | `EURUSD#` | 4 | True |
| GBPUSD | `GBPUSD#` | 4 | True |
| USDJPY | `USDJPY#` | 4 | True |
| XAUUSD | `GOLD.i#` | 4 | True |
| BTCUSD | `BTCUSD#` | 4 | True |
| ETHUSD | `ETHUSD#` | 4 | True |
| SOLUSD | `SOLUSD#` | 4 | True |
| AUDUSD | `AUDUSD#` | 4 | True |
| USDCAD | `USDCAD#` | 4 | True |
| USDCHF | `USDCHF#` | 4 | True |
| ETHBTC | `ETHBTC#` | 4 | True |
| US30 | `US30Cash#` | 4 | True |
| NAS100 | `US100Cash#` | 4 | True |
| US500 | `US500Cash#` | 4 | True |
| WTI | `OILCash#` | 4 | True |

## Bar depth and gaps (UTC)

`gaps` = bar-to-bar jumps > 1.5 bars; `weekend` = the Fri→Sun close; `short` = ≤ 3 h (daily CFD session break, crypto maintenance); `odd` = everything else (holidays, outages, sparse old history); `lag` = minutes since last bar open.

| symbol | tf | bars | first | last | lag min | gaps | weekend | short | odd | odd last 2y | biggest odd h |
|---|---|---|---|---|---|---|---|---|---|---|---|
| EURUSD | M5 | 99999 | 2025-07-15 14:10 | 2026-11-17 20:25 | 1.5 | 72 | 70 | 0 | 2 | 2 | 36.1 |
| EURUSD | M15 | 99999 | 2022-11-07 20:15 | 2026-11-17 20:15 | 11.5 | 214 | 210 | 0 | 4 | 4 | 36.2 |
| EURUSD | H1 | 99999 | 2010-10-06 16:00 | 2026-11-17 20:00 | 26.5 | 890 | 862 | 2 | 26 | 4 | 39.0 |
| EURUSD | H4 | 50634 | 1971-01-03 22:00 | 2026-11-17 18:00 | 146.5 | 8700 | 2872 | 0 | 5828 | 4 | 240.0 |
| EURUSD | D1 | 14484 | 1971-01-03 22:00 | 2026-11-16 22:00 | 1346.5 | 2979 | 2814 | 0 | 165 | 4 | 240.0 |
| GBPUSD | M5 | 99999 | 2025-07-15 12:10 | 2026-11-17 20:25 | 1.6 | 81 | 70 | 9 | 2 | 2 | 36.1 |
| GBPUSD | M15 | 99999 | 2022-11-07 19:45 | 2026-11-17 20:15 | 11.6 | 216 | 210 | 2 | 4 | 4 | 36.2 |
| GBPUSD | H1 | 99999 | 2010-10-06 16:00 | 2026-11-17 20:00 | 26.6 | 889 | 862 | 2 | 25 | 4 | 39.0 |
| GBPUSD | H4 | 45016 | 1993-05-11 21:00 | 2026-11-17 18:00 | 146.6 | 3088 | 1872 | 0 | 1216 | 4 | 100.0 |
| GBPUSD | D1 | 8871 | 1993-05-11 21:00 | 2026-11-16 22:00 | 1346.6 | 1763 | 1734 | 0 | 29 | 4 | 96.0 |
| USDJPY | M5 | 99999 | 2025-07-15 13:10 | 2026-11-17 20:25 | 1.6 | 74 | 70 | 2 | 2 | 2 | 36.1 |
| USDJPY | M15 | 99999 | 2022-11-07 19:15 | 2026-11-17 20:15 | 11.6 | 215 | 210 | 1 | 4 | 4 | 36.2 |
| USDJPY | H1 | 99999 | 2010-10-07 01:00 | 2026-11-17 20:00 | 26.6 | 890 | 862 | 2 | 26 | 4 | 39.0 |
| USDJPY | H4 | 50706 | 1971-01-03 22:00 | 2026-11-17 18:00 | 146.6 | 8785 | 2963 | 0 | 5822 | 4 | 432.0 |
| USDJPY | D1 | 14565 | 1971-01-03 22:00 | 2026-11-16 22:00 | 1346.6 | 2980 | 2826 | 0 | 154 | 4 | 432.0 |
| XAUUSD | M5 | 99999 | 2025-06-20 06:15 | 2026-11-17 20:25 | 1.8 | 365 | 74 | 283 | 8 | 8 | 36.1 |
| XAUUSD | M15 | 99999 | 2022-08-24 04:15 | 2026-11-17 20:15 | 11.8 | 1092 | 221 | 841 | 30 | 15 | 36.2 |
| XAUUSD | H1 | 84134 | 2001-06-03 22:00 | 2026-11-17 20:00 | 26.8 | 5685 | 1349 | 1750 | 2586 | 15 | 96.0 |
| XAUUSD | H4 | 23992 | 2001-06-03 21:00 | 2026-11-17 18:00 | 146.8 | 3893 | 1349 | 0 | 2544 | 4 | 96.0 |
| XAUUSD | D1 | 6621 | 2001-06-03 21:00 | 2026-11-16 22:00 | 1346.8 | 1346 | 1297 | 0 | 49 | 6 | 96.0 |
| BTCUSD | M5 | 99999 | 2025-12-04 12:05 | 2026-11-17 20:25 | 1.9 | 53 | 0 | 53 | 0 | 0 | 0.0 |
| BTCUSD | M15 | 99999 | 2024-01-09 12:15 | 2026-11-17 20:15 | 11.9 | 152 | 0 | 152 | 0 | 0 | 0.0 |
| BTCUSD | H1 | 73461 | 2013-01-01 22:00 | 2026-11-17 20:00 | 26.9 | 1246 | 0 | 10 | 1236 | 0 | 2711.0 |
| BTCUSD | H4 | 19120 | 2013-01-01 22:00 | 2026-11-17 18:00 | 146.9 | 1234 | 0 | 0 | 1234 | 0 | 2711.0 |
| BTCUSD | D1 | 3993 | 2013-01-01 22:00 | 2026-11-16 22:00 | 1346.9 | 463 | 0 | 0 | 463 | 0 | 2711.0 |
| ETHUSD | M5 | 99999 | 2025-12-04 12:05 | 2026-11-17 20:25 | 2.0 | 53 | 0 | 53 | 0 | 0 | 0.0 |
| ETHUSD | M15 | 99999 | 2024-01-09 12:15 | 2026-11-17 20:15 | 12.0 | 152 | 0 | 152 | 0 | 0 | 0.0 |
| ETHUSD | H1 | 76122 | 2016-11-07 22:00 | 2026-11-17 20:00 | 27.0 | 283 | 0 | 17 | 266 | 0 | 82.0 |
| ETHUSD | H4 | 19073 | 2016-11-07 22:00 | 2026-11-17 18:00 | 147.0 | 263 | 0 | 0 | 263 | 0 | 84.0 |
| ETHUSD | D1 | 3209 | 2016-11-07 22:00 | 2026-11-16 22:00 | 1347.0 | 228 | 0 | 0 | 228 | 0 | 96.0 |
| SOLUSD | M5 | 99999 | 2025-12-04 12:05 | 2026-11-17 20:25 | 2.0 | 53 | 0 | 53 | 0 | 0 | 0.0 |
| SOLUSD | M15 | 99999 | 2024-01-09 12:15 | 2026-11-17 20:15 | 12.0 | 152 | 0 | 152 | 0 | 0 | 0.0 |
| SOLUSD | H1 | 45173 | 2021-09-18 07:00 | 2026-11-17 20:00 | 27.0 | 9 | 0 | 6 | 3 | 0 | 52.0 |
| SOLUSD | H4 | 11297 | 2021-09-18 05:00 | 2026-11-17 18:00 | 147.0 | 2 | 0 | 0 | 2 | 0 | 52.0 |
| SOLUSD | D1 | 1885 | 2021-09-17 21:00 | 2026-11-16 22:00 | 1347.0 | 2 | 0 | 0 | 2 | 0 | 48.0 |
| AUDUSD | M5 | 99999 | 2025-07-15 13:55 | 2026-11-17 20:25 | 2.0 | 73 | 70 | 1 | 2 | 2 | 36.1 |
| AUDUSD | M15 | 99999 | 2022-11-07 20:15 | 2026-11-17 20:15 | 12.0 | 214 | 210 | 0 | 4 | 4 | 36.2 |
| AUDUSD | H1 | 56317 | 2007-06-06 21:00 | 2026-11-17 20:00 | 27.0 | 3401 | 1135 | 0 | 2266 | 4 | 96.0 |
| AUDUSD | H4 | 16323 | 2007-06-06 21:00 | 2026-11-17 18:00 | 147.0 | 3401 | 1135 | 0 | 2266 | 4 | 96.0 |
| AUDUSD | D1 | 5203 | 2007-06-06 21:00 | 2026-11-16 22:00 | 1347.0 | 1030 | 1005 | 0 | 25 | 4 | 96.0 |
| USDCAD | M5 | 99999 | 2025-07-15 12:25 | 2026-11-17 20:25 | 2.1 | 74 | 70 | 2 | 2 | 2 | 36.1 |
| USDCAD | M15 | 99999 | 2022-11-07 18:45 | 2026-11-17 20:15 | 12.1 | 215 | 210 | 1 | 4 | 4 | 36.2 |
| USDCAD | H1 | 99999 | 2010-10-07 05:00 | 2026-11-17 20:00 | 27.1 | 889 | 862 | 2 | 25 | 4 | 39.0 |
| USDCAD | H4 | 45039 | 1993-04-27 21:00 | 2026-11-17 18:00 | 147.1 | 3111 | 1888 | 0 | 1223 | 4 | 104.0 |
| USDCAD | D1 | 8895 | 1993-04-27 21:00 | 2026-11-16 22:00 | 1347.1 | 1766 | 1738 | 0 | 28 | 4 | 96.0 |
| USDCHF | M5 | 99999 | 2025-07-15 11:15 | 2026-11-17 20:25 | 2.1 | 76 | 70 | 4 | 2 | 2 | 36.1 |
| USDCHF | M15 | 99999 | 2022-11-07 18:30 | 2026-11-17 20:15 | 12.1 | 217 | 210 | 3 | 4 | 4 | 36.2 |
| USDCHF | H1 | 99999 | 2010-10-06 23:00 | 2026-11-17 20:00 | 27.1 | 890 | 862 | 3 | 25 | 4 | 39.0 |
| USDCHF | H4 | 50666 | 1971-01-03 22:00 | 2026-11-17 18:00 | 147.1 | 8740 | 2934 | 0 | 5806 | 4 | 240.0 |
| USDCHF | D1 | 14522 | 1971-01-03 22:00 | 2026-11-16 22:00 | 1347.1 | 3000 | 2796 | 0 | 204 | 4 | 240.0 |
| ETHBTC | M5 | 99999 | 2025-12-04 12:05 | 2026-11-17 20:25 | 2.2 | 53 | 0 | 53 | 0 | 0 | 0.0 |
| ETHBTC | M15 | 99999 | 2024-01-09 12:15 | 2026-11-17 20:15 | 12.2 | 152 | 0 | 152 | 0 | 0 | 0.0 |
| ETHBTC | H1 | 68976 | 2019-01-01 22:00 | 2026-11-17 20:00 | 27.2 | 26 | 0 | 17 | 9 | 0 | 15.0 |
| ETHBTC | H4 | 17256 | 2019-01-01 22:00 | 2026-11-17 18:00 | 147.2 | 4 | 0 | 0 | 4 | 0 | 12.0 |
| ETHBTC | D1 | 2877 | 2019-01-01 22:00 | 2026-11-16 22:00 | 1347.2 | 0 | 0 | 0 | 0 | 0 | 0.0 |
| US30 | M5 | 99999 | 2025-06-19 15:25 | 2026-11-17 20:25 | 2.2 | 368 | 74 | 282 | 12 | 12 | 36.1 |
| US30 | M15 | 99999 | 2022-08-22 07:30 | 2026-11-17 20:15 | 12.2 | 1098 | 221 | 841 | 36 | 19 | 36.2 |
| US30 | H1 | 63144 | 2011-08-09 21:00 | 2026-11-17 20:00 | 27.2 | 4116 | 957 | 2085 | 1074 | 19 | 119.0 |
| US30 | H4 | 17539 | 2011-08-09 21:00 | 2026-11-17 18:00 | 147.2 | 2021 | 955 | 0 | 1066 | 16 | 119.0 |
| US30 | D1 | 4107 | 2011-08-09 21:00 | 2026-11-16 22:00 | 1347.2 | 813 | 777 | 0 | 36 | 5 | 119.0 |
| NAS100 | M5 | 99999 | 2025-06-19 15:30 | 2026-11-17 20:25 | 2.3 | 368 | 74 | 282 | 12 | 12 | 36.1 |
| NAS100 | M15 | 99999 | 2022-08-22 07:30 | 2026-11-17 20:15 | 12.3 | 1099 | 221 | 842 | 36 | 19 | 36.2 |
| NAS100 | H1 | 63106 | 2011-09-18 21:00 | 2026-11-17 20:00 | 27.3 | 4084 | 951 | 2085 | 1048 | 19 | 216.0 |
| NAS100 | H4 | 17506 | 2011-09-18 21:00 | 2026-11-17 18:00 | 147.3 | 1988 | 949 | 0 | 1039 | 16 | 216.0 |
| NAS100 | D1 | 4074 | 2011-09-18 21:00 | 2026-11-16 22:00 | 1347.3 | 807 | 770 | 0 | 37 | 5 | 216.0 |
| US500 | M5 | 99999 | 2025-06-19 15:25 | 2026-11-17 20:25 | 2.4 | 368 | 74 | 282 | 12 | 12 | 36.1 |
| US500 | M15 | 99999 | 2022-08-22 07:45 | 2026-11-17 20:15 | 12.4 | 1098 | 221 | 841 | 36 | 19 | 36.2 |
| US500 | H1 | 63141 | 2011-08-07 21:00 | 2026-11-17 20:00 | 27.4 | 4118 | 961 | 2087 | 1070 | 19 | 312.0 |
| US500 | H4 | 17539 | 2011-08-07 21:00 | 2026-11-17 18:00 | 147.4 | 2021 | 959 | 0 | 1062 | 16 | 312.0 |
| US500 | D1 | 4107 | 2011-08-07 21:00 | 2026-11-16 22:00 | 1347.4 | 812 | 775 | 0 | 37 | 5 | 312.0 |
| WTI | M5 | 99999 | 2025-06-17 10:25 | 2026-11-17 20:25 | 2.5 | 388 | 74 | 303 | 11 | 11 | 36.1 |
| WTI | M15 | 99999 | 2022-08-15 10:00 | 2026-11-17 20:15 | 12.5 | 1103 | 222 | 849 | 32 | 17 | 36.2 |
| WTI | H1 | 64976 | 2010-08-15 21:00 | 2026-11-17 20:00 | 27.5 | 4355 | 980 | 2152 | 1223 | 17 | 96.0 |
| WTI | H4 | 18160 | 2010-08-15 21:00 | 2026-11-17 18:00 | 147.5 | 2165 | 980 | 0 | 1185 | 4 | 96.0 |
| WTI | D1 | 4337 | 2010-08-15 21:00 | 2026-11-16 22:00 | 1347.5 | 863 | 827 | 0 | 36 | 6 | 96.0 |

## Contract fields (broker)

| symbol | digits | tick size | tick value | contract | vol min/step | stops lvl | profit ccy | pip $/lot broker | registry | profile |
|---|---|---|---|---|---|---|---|---|---|---|
| EURUSD | 5 | 1e-05 | 1.0 | 100000.0 | 0.01/0.01 | 0 | USD | 10.0 | 10.0 | 10.0 |
| GBPUSD | 5 | 1e-05 | 1.0 | 100000.0 | 0.01/0.01 | 0 | USD | 10.0 | 10.0 | 10.0 |
| USDJPY | 3 | 0.001 | 0.627447 | 100000.0 | 0.01/0.01 | 0 | JPY | 6.2745 | 6.28 | 6.28 |
| XAUUSD | 2 | 0.01 | 1.0 | 100.0 | 0.01/0.01 | 0 | USD | 10.0 | 10.0 | 10.0 |
| BTCUSD | 2 | 0.01 | 0.01 | 1.0 | 0.01/0.01 | 0 | USD | 0.01 | 0.01 | 0.01 |
| ETHUSD | 2 | 0.01 | 0.01 | 1.0 | 0.02/0.01 | 0 | USD | 0.01 | 0.01 | 0.01 |
| SOLUSD | 2 | 0.01 | 0.1 | 10.0 | 0.05/0.01 | 0 | USD | 0.1 | 0.1 | 0.1 |
| AUDUSD | 5 | 1e-05 | 1.0 | 100000.0 | 0.01/0.01 | 0 | USD | 10.0 | 10.0 | 10.0 |
| USDCAD | 5 | 1e-05 | 0.699648 | 100000.0 | 0.01/0.01 | 0 | CAD | 6.9965 | 7.0 | 7.0 |
| USDCHF | 5 | 1e-05 | 1.190533 | 100000.0 | 0.01/0.01 | 0 | CHF | 11.9053 | 11.9 | 11.9 |
| ETHBTC | 5 | 1e-05 | 1.0 | 100000.0 | 0.01/0.01 | 0 | USD | 1.0 | 1.0 | 1.0 |
| US30 | 2 | 0.01 | 0.01 | 1.0 | 0.1/0.1 | 0 | USD | 1.0 | 1.0 | 1.0 |
| NAS100 | 2 | 0.01 | 0.01 | 1.0 | 0.1/0.1 | 0 | USD | 1.0 | 1.0 | 1.0 |
| US500 | 2 | 0.01 | 0.01 | 1.0 | 0.1/0.1 | 0 | USD | 1.0 | 1.0 | 1.0 |
| WTI | 2 | 0.01 | 1.0 | 100.0 | 0.01/0.01 | 0 | USD | 1.0 | 1.0 | 1.0 |

## Spread (pips, registry pip size) and commission

Median / p95 over the last ~20 days of M5 bar spreads.

| symbol | live | median | p95 | registry typ/max | profile typ/max | commission measured (deals) | profile |
|---|---|---|---|---|---|---|---|
| EURUSD | 1.1 | 1.0 | 1.1 | 1.0/2.0 | 1.0/3.5 | 0.0 (255) | 0.0 |
| GBPUSD | 1.4 | 1.0 | 1.4 | 0.9/2.5 | 1.0/3.8 | 0.0 (133) | 0.0 |
| USDJPY | 1.1 | 0.8 | 1.4 | 0.8/2.5 | 0.8/3.8 | 0.0 (22) | 0.0 |
| XAUUSD | 2.6 | 2.0 | 2.2 | 2.0/5.0 | 2.0/5.0 | 0.0 (2053) | 0.0 |
| BTCUSD | 1500.0 | 1500.0 | 1500.0 | 1500.0/3000.0 | 1500.0/3000.0 | 0.0 (640) | 0.0 |
| ETHUSD | 190.0 | 190.0 | 190.0 | 190.0/450.0 | 190.0/300.0 | 0.0 (255) | 0.0 |
| SOLUSD | 51.0 | 51.0 | 51.0 | 51.0/105.0 | 45.0/105.0 | 0.0 (105) | 0.0 |
| AUDUSD | 1.4 | 1.3 | 1.4 | 1.3/2.5 | 1.3/3.8 | 0.0 (28) | 0.0 |
| USDCAD | 2.1 | 1.9 | 2.4 | 1.9/8.5 | 1.9/2.5 | 0.0 (40) | 0.0 |
| USDCHF | 1.5 | 1.3 | 1.5 | 1.3/4.0 | 1.3/2.5 | 0.0 (4) | 0.0 |
| ETHBTC | 11.0 | 11.0 | 11.0 | 11.0/25.0 | 11.0/25.0 | 0.0 (38) | 0.0 |
| US30 | 4.0 | 4.0 | 4.0 | 3.9/12.0 | 4.0/8.0 | 0.0 (6) | 0.0 |
| NAS100 | 1.95 | 1.95 | 1.95 | 2.0/6.0 | 2.0/7.0 | 0.0 (12) | 0.0 |
| US500 | 0.65 | 0.65 | 0.65 | 0.6/6.0 | 0.6/2.5 | 0.0 (6) | 0.0 |
| WTI | 3.0 | 3.0 | 8.0 | 3.0/25.0 | 3.0/25.0 | 0.0 (60) | 0.0 |

## Min-lot risk (1.5×ATR(14) H1 stop at volume_min; caps: per-trade 1.0%, min-lot 2.5%)

| symbol | ATR H1 | stop | loss $ | % equity | ≥ stops level |
|---|---|---|---|---|---|
| EURUSD | 0.00115 | 0.00173 | 1.73 | 0.33 | True |
| GBPUSD | 0.00128 | 0.00192 | 1.92 | 0.37 | True |
| USDJPY | 0.163 | 0.245 | 1.54 | 0.3 | True |
| XAUUSD | 15.27 | 22.91 | 22.91 | 4.41 ⚠ | True |
| BTCUSD | 561.66 | 842.49 | 8.42 | 1.62 (>per-trade) | True |
| ETHUSD | 21.13 | 31.7 | 0.63 | 0.12 | True |
| SOLUSD | 0.95 | 1.43 | 0.72 | 0.14 | True |
| AUDUSD | 0.00091 | 0.00136 | 1.36 | 0.26 | True |
| USDCAD | 0.00109 | 0.00163 | 1.14 | 0.22 | True |
| USDCHF | 0.00115 | 0.00173 | 2.06 | 0.4 | True |
| ETHBTC | 0.00015 | 0.00022 | 0.22 | 0.04 | True |
| US30 | 188.95 | 283.42 | 28.34 | 5.45 ⚠ | True |
| NAS100 | 183.19 | 274.79 | 27.48 | 5.29 ⚠ | True |
| US500 | 32.17 | 48.25 | 4.83 | 0.93 | True |
| WTI | 0.59 | 0.88 | 0.88 | 0.17 | True |

## Mismatches

None. (The first run found 21; the fixes are below, and this report is the re-run after them.)

## Fixes applied (first run → now)

The first run used tolerances of ±25% for the typical spread and 5% for non-USD pip value. It found these mismatches; each was fixed in
`jarvis/data/symbol_registry.py` (registry) and `jarvis/intelligence/symbol_profile_config.py` (profile):

| symbol | field | was | now (measured) |
|---|---|---|---|
| EURUSD | registry / profile typical spread | 0.7 / 1.6 | 1.0 |
| GBPUSD | profile typical spread | 1.8 | 1.0 |
| USDJPY | registry + profile pip $/lot | 6.80 | 6.28 (broker 6.275) |
| USDJPY | profile typical spread | 1.8 | 0.8 |
| ETHUSD | registry / profile typical spread | 345 / 120 | 190 |
| SOLUSD | registry typical spread | 35 | 51 |
| AUDUSD | registry / profile typical spread | 0.9 / 1.8 | 1.3 |
| USDCAD | registry + profile pip $/lot | 7.50 | 7.00 (broker 6.996) |
| USDCAD | registry / profile typical spread | 2.7 / 1.1 | 1.9 |
| USDCHF | registry + profile pip $/lot | 10.0 | 11.90 (broker 11.906) |
| USDCHF | registry typical spread | 2.4 | 1.3 |
| US30 | profile typical spread | 2.5 | 4.0 |
| WTI | registry + profile typical spread | 13.0 | 3.0 (p95 8.0) |

These were already correct and unchanged: alias resolution, digits, contract size, volume min/step, commission ($0 on 3,656 deals), and
every max-spread gate (none below the measured p95). `tests/test_symbol_registry.py::test_xm_broker_names_round_trip_to_their_canonical_spec`
pins the XM names above. `tests/test_position_monitor_spread_guard.py` used 1.5 pips as an "EURUSD blowout"; with the corrected
typical spread the 2× guard sits at 2.0, so its probe is now 2.5.

## Remaining flags, explained

- **Min-lot risk (XAUUSD 4.4%, US30 5.5%, NAS100 5.3%, BTCUSD 1.6%).** These are not spec errors. At $520 equity, the broker's
  `volume_min` with a 1.5×ATR H1 stop already exceeds the risk caps. XAUUSD, US30 and NAS100 exceed `min_lot_max_risk_pct` 2.5%
  outright, so the calibration should treat them as untradeable at this equity, or test them only with tighter (shorter-TF) stops.
  BTCUSD fits only under the min-lot exception. The cost per 0.01 lot is in the table above.
- **Spreads are a 20-day M5 snapshot.** XM's crypto spreads are fixed and step-change. ETHUSD was a flat 345 through 2026 H1
  (`reports/spread_calibration_measured.json`) and is now 190. Re-run this audit before each calibration batch instead of
  trusting the constants.
- **Pip value for non-USD-quoted pairs drifts with the FX rate.** Live sizing uses the broker's `trade_tick_value`
  (`get_dollar_risk_per_price_unit`), so only offline/backtest sizing uses these constants. EURJPY/GBPJPY (6.80) are stale for the
  same reason but are not traded, so they were not audited.
- **Gaps.** Over the last two years the only "odd" gaps are exchange holidays (FX 2–4 around year-end, ≤36 h; gold, indices and oil
  15–19 US holidays). From 2020-01-01 every H1 series is dense (~42.7k bars for 24/5 FX, ~40.6k for CFDs with a daily break,
  ~54.9k for 24/7 crypto). Holes longer than 4 days exist only before 2017 (BTCUSD 2017-03, US indices 2016-03). Pre-2014 H1/H4
  history is sparse (e.g. AUDUSD H1 has the same 3,401 gaps as its H4, so its old H1 bars look H4-spaced; FX D1/H4 starts in 1971), so calibration windows should start
  at 2020 or later.
- **Depth is capped by the terminal.** `maxbars` = 100,000 and `copy_rates_from_pos` refuses count ≥ maxbars, so M5/M15 stop at
  99,999 bars (~16 months of M5, ~4 years of M15). Raise "Max bars in chart" in the terminal if longer M5 history is needed.
- **`config/symbol_profiles.json` is not read by any code.** It was used only for the symbol list. Its spreads (e.g. XAUUSD typical 0.5)
  are stale but have no effect.

## Notes

- XAUUSD: min-lot risk 4.41% > min_lot_max_risk_pct 2.5% -> untradeable at this equity
- BTCUSD: min-lot risk 1.62% > max_risk_per_trade_pct 1.0% (allowed only via min-lot cap 2.5%)
- US30: min-lot risk 5.45% > min_lot_max_risk_pct 2.5% -> untradeable at this equity
- NAS100: min-lot risk 5.29% > min_lot_max_risk_pct 2.5% -> untradeable at this equity
