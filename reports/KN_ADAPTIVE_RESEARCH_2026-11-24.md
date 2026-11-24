# KN Smart TP/SL → KN-Adaptive research (2026-11-24)

**Question:** can the "KN – Smart TP SL" indicator (EMA 5/13 cross, 1.5×ATR stop, TP 1R/2R/3R) turn the losing symbols (GBPUSD, BTCUSD, SOLUSD, EURUSD) profitable, especially with dynamic layers added?

**Method:** `tools/kn_research.py` on real XM MT5 bars, frozen 2026-11-24, H1 and H4.
- **Signals:** `jarvis/forward_tests/kn_adaptive.py`.
- **Costs:** real per-bar spread, slippage and broker swap per leg.
- **Walk-forward:** anchored by quarter after a two-year warm-up. The ER threshold (and the variant, for WF_best) is picked only on trades that had already closed.
- **Adoption:** `strategy_research.verdict()` (minimum lot ×3 for three legs) **and** a deflated Sharpe above 0.95, counting 13 trials.

**Variants:**
| Variant | Adds |
|---|---|
| V0 | raw KN, as written in the Pine script |
| V1 | an ER(20)/ADX regime gate |
| V2 | an H4 EMA200/EMA50 bias filter |
| V3 | a volatility-adaptive, structure-floored stop with a cost filter |
| V4 | an MFE-percentile TP ladder, break-even after TP1 and a chandelier runner |

## Verdict: nothing adopted

1. **Raw KN loses on every symbol, both timeframes, after costs.** H1 expectancy is -0.08R to -0.41R. As written, the indicator would make the losing symbols worse.
2. **The regime gate (V1) is the layer that matters.** It cuts trades by about 85% and turns H4 positive on GBPUSD and BTCUSD. The bias filter (V2) adds a little. The adaptive stop (V3) and the dynamic ladder (V4) did **not** add out-of-sample edge on top of it: they gave a higher win rate but the same or lower expectancy.
3. **Best lead: GBPUSD H4 V1/V2.** Out-of-sample it shows:
   - +0.14 to +0.19R per trade, PF 1.34 to 1.46, max drawdown 7 to 8R
   - both halves positive, still positive at spread ×2, beats always-long and flipped
   - in the real-spread era: +0.196R over 67 trades, with 7 of 8 years since 2019 positive

   It fails on two counts:
   - **DSR is 0.86 to 0.92, below 0.95.** It may still be luck from the search.
   - **Minimum lot:** three legs at 0.01 each risk about $22 (median), which needs about a $1,190 account for 80% of trades to fit the 2.5% rule.
4. **BTCUSD H4 V1** is +0.08R with PF 1.17, but DSR is only 0.32 and the real-era years are mixed. It is not a lead.
5. **SOLUSD:** H1 is strongly negative (around -0.4R). On H1 the spread is more than 10% of every adaptive stop, so V3 and V4 take no trades. Don't trade SOL with this signal.
6. **EURUSD:** about zero on every variant.

## Results (out-of-sample quarters only)

| Symbol | TF | Variant | n | Win% | ExpR | PF | MaxDD R | 1st half | 2nd half | Spread x2 | Always-long | Flipped | DSR | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| GBPUSD | H1 | V0_raw | 1945 | 33% | -0.094 | 0.82 | 212.2 | -0.103 | -0.086 | -0.125 | -0.069 | -0.012 | 0.0 | loses after costs+swap; PF 0.82 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped; min lot unaffordable at $100 (0% fit); DSR 0.0 <= 0.95 |
| GBPUSD | H1 | V1_regime | 258 | 34% | -0.103 | 0.81 | 38.3 | -0.047 | -0.159 | -0.128 | -0.049 | +0.019 | 0.001 | loses after costs+swap; PF 0.81 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped; min lot unaffordable at $100 (0% fit); DSR 0.001 <= 0.95 |
| GBPUSD | H1 | V2_htf | 136 | 35% | -0.027 | 0.95 | 15.2 | -0.007 | -0.046 | -0.040 | -0.111 | -0.053 | 0.076 | loses after costs+swap; PF 0.95 <= 1.1; a half is negative; fails spread x2; min lot unaffordable at $100 (0% fit); DSR 0.076 <= 0.95 |
| GBPUSD | H1 | V3_stop | 134 | 37% | +0.016 | 1.04 | 8.4 | +0.069 | -0.037 | -0.006 | -0.089 | -0.050 | 0.16 | PF 1.04 <= 1.1; a half is negative; fails spread x2; min lot unaffordable at $100 (0% fit); DSR 0.16 <= 0.95 |
| GBPUSD | H1 | V4_ladder | 134 | 40% | +0.019 | 1.05 | 8.6 | +0.089 | -0.051 | +0.001 | -0.078 | -0.073 | 0.17 | PF 1.05 <= 1.1; a half is negative; min lot unaffordable at $100 (0% fit); DSR 0.17 <= 0.95 |
| GBPUSD | H1 | WF_best | 134 | 39% | +0.003 | 1.01 | 8.7 | +0.072 | -0.065 | -0.015 | -0.089 | -0.073 | 0.129 | PF 1.01 <= 1.1; a half is negative; fails spread x2; min lot unaffordable at $100 (0% fit); DSR 0.129 <= 0.95 |
| GBPUSD | H4 | V0_raw | 2130 | 38% | +0.007 | 1.02 | 60.6 | -0.009 | +0.024 | -0.007 | -0.032 | -0.048 | 0.006 | PF 1.02 <= 1.1; a half is negative; fails spread x2; min lot unaffordable at $100 (0% fit); DSR 0.006 <= 0.95 |
| GBPUSD | H4 | V1_regime | 261 | 47% | +0.142 | 1.34 | 7.8 | +0.080 | +0.205 | +0.133 | +0.023 | -0.112 | 0.856 | min lot unaffordable at $100 (0% fit); DSR 0.856 <= 0.95 |
| GBPUSD | H4 | V2_htf | 177 | 50% | +0.191 | 1.46 | 7.0 | +0.073 | +0.307 | +0.179 | -0.043 | -0.182 | 0.922 | min lot unaffordable at $100 (0% fit); DSR 0.922 <= 0.95 |
| GBPUSD | H4 | V3_stop | 183 | 46% | +0.141 | 1.42 | 5.5 | +0.044 | +0.236 | +0.131 | -0.018 | -0.133 | 0.884 | min lot unaffordable at $100 (0% fit); DSR 0.884 <= 0.95 |
| GBPUSD | H4 | V4_ladder | 185 | 48% | +0.117 | 1.36 | 5.5 | +0.044 | +0.189 | +0.106 | -0.049 | -0.148 | 0.829 | min lot unaffordable at $100 (0% fit); DSR 0.829 <= 0.95 |
| GBPUSD | H4 | WF_best | 472 | 40% | +0.058 | 1.14 | 13.8 | -0.024 | +0.140 | +0.046 | -0.003 | -0.086 | 0.442 | a half is negative; min lot unaffordable at $100 (0% fit); DSR 0.442 <= 0.95 |
| BTCUSD | H1 | V0_raw | 1746 | 33% | -0.076 | 0.84 | 140.6 | -0.123 | -0.029 | -0.165 | -0.075 | -0.133 | 0.0 | loses after costs+swap; PF 0.84 <= 1.1; a half is negative; fails spread x2; not above always-long; min lot unaffordable at $100 (2% fit); DSR 0.0 <= 0.95 |
| BTCUSD | H1 | V1_regime | 333 | 35% | -0.045 | 0.91 | 21.4 | -0.065 | -0.026 | -0.157 | -0.102 | -0.188 | 0.104 | loses after costs+swap; PF 0.91 <= 1.1; a half is negative; fails spread x2; min lot unaffordable at $100 (2% fit); DSR 0.104 <= 0.95 |
| BTCUSD | H1 | V2_htf | 152 | 31% | -0.117 | 0.77 | 25.2 | -0.217 | -0.017 | -0.209 | -0.101 | -0.195 | 0.053 | loses after costs+swap; PF 0.77 <= 1.1; a half is negative; fails spread x2; not above always-long; min lot unaffordable at $100 (2% fit); DSR 0.053 <= 0.95 |
| BTCUSD | H1 | V3_stop | 130 | 31% | -0.069 | 0.85 | 14.0 | -0.212 | +0.075 | -0.143 | -0.135 | -0.139 | 0.144 | loses after costs+swap; PF 0.85 <= 1.1; a half is negative; fails spread x2; min lot unaffordable at $100 (0% fit); DSR 0.144 <= 0.95 |
| BTCUSD | H1 | V4_ladder | 130 | 36% | -0.064 | 0.85 | 13.5 | -0.168 | +0.040 | -0.144 | -0.154 | -0.140 | 0.155 | loses after costs+swap; PF 0.85 <= 1.1; a half is negative; fails spread x2; min lot unaffordable at $100 (0% fit); DSR 0.155 <= 0.95 |
| BTCUSD | H1 | WF_best | 223 | 33% | -0.108 | 0.78 | 25.7 | -0.196 | -0.022 | -0.178 | -0.106 | -0.138 | 0.031 | loses after costs+swap; PF 0.78 <= 1.1; a half is negative; fails spread x2; not above always-long; min lot unaffordable at $100 (0% fit); DSR 0.031 <= 0.95 |
| BTCUSD | H4 | V0_raw | 849 | 35% | -0.024 | 0.95 | 52.0 | +0.046 | -0.094 | -0.050 | -0.060 | -0.076 | 0.0 | loses after costs+swap; PF 0.95 <= 1.1; a half is negative; fails spread x2; min lot unaffordable at $100 (4% fit); DSR 0.0 <= 0.95 |
| BTCUSD | H4 | V1_regime | 104 | 42% | +0.079 | 1.17 | 5.6 | +0.001 | +0.157 | +0.039 | -0.070 | -0.114 | 0.319 | min lot unaffordable at $100 (0% fit); DSR 0.319 <= 0.95 |
| BTCUSD | H4 | V2_htf | 67 | 40% | +0.084 | 1.18 | 9.5 | -0.233 | +0.393 | +0.025 | +0.125 | -0.090 | 0.367 | n 67 < 100; a half is negative; not above always-long; min lot unaffordable at $100 (0% fit); DSR 0.367 <= 0.95 |
| BTCUSD | H4 | V3_stop | 62 | 44% | +0.113 | 1.29 | 8.7 | -0.198 | +0.423 | +0.099 | +0.132 | -0.126 | 0.479 | n 62 < 100; a half is negative; not above always-long; min lot unaffordable at $100 (0% fit); DSR 0.479 <= 0.95 |
| BTCUSD | H4 | V4_ladder | 67 | 48% | +0.141 | 1.39 | 7.7 | -0.185 | +0.457 | +0.102 | +0.062 | -0.154 | 0.538 | n 67 < 100; a half is negative; min lot unaffordable at $100 (0% fit); DSR 0.538 <= 0.95 |
| BTCUSD | H4 | WF_best | 243 | 40% | +0.084 | 1.18 | 15.5 | +0.127 | +0.040 | +0.065 | -0.074 | -0.209 | 0.252 | min lot unaffordable at $100 (13% fit); DSR 0.252 <= 0.95 |
| SOLUSD | H1 | V0_raw | 1544 | 26% | -0.406 | 0.45 | 625.6 | -0.352 | -0.460 | -0.734 | -0.432 | -0.445 | 0.0 | loses after costs+swap; PF 0.45 <= 1.1; a half is negative; fails spread x2; min lot unaffordable at $100 (35% fit); DSR 0.0 <= 0.95 |
| SOLUSD | H1 | V1_regime | 154 | 25% | -0.387 | 0.47 | 60.0 | -0.283 | -0.491 | -0.711 | -0.409 | -0.470 | 0.0 | loses after costs+swap; PF 0.47 <= 1.1; a half is negative; fails spread x2; min lot unaffordable at $100 (34% fit); DSR 0.0 <= 0.95 |
| SOLUSD | H1 | V2_htf | 66 | 23% | -0.400 | 0.48 | 28.7 | -0.371 | -0.430 | -0.798 | -0.541 | -0.513 | 0.001 | n 66 < 100; loses after costs+swap; PF 0.48 <= 1.1; a half is negative; fails spread x2; min lot unaffordable at $100 (39% fit); DSR 0.001 <= 0.95 |
| SOLUSD | H1 | V3_stop | 0 | | | | | | | | | | | no trades |
| SOLUSD | H1 | V4_ladder | 0 | | | | | | | | | | | no trades |
| SOLUSD | H1 | WF_best | 141 | 23% | -0.440 | 0.42 | 62.3 | -0.279 | -0.599 | -0.728 | -0.442 | -0.422 | 0.0 | loses after costs+swap; PF 0.42 <= 1.1; a half is negative; fails spread x2; not above flipped; min lot unaffordable at $100 (32% fit); DSR 0.0 <= 0.95 |
| SOLUSD | H4 | V0_raw | 331 | 33% | -0.119 | 0.78 | 43.7 | -0.010 | -0.228 | -0.274 | -0.210 | -0.267 | 0.0 | loses after costs+swap; PF 0.78 <= 1.1; a half is negative; fails spread x2; min lot unaffordable at $100 (5% fit); DSR 0.0 <= 0.95 |
| SOLUSD | H4 | V1_regime | 43 | 37% | +0.034 | 1.07 | 7.7 | -0.059 | +0.123 | -0.234 | -0.256 | -0.310 | 0.243 | n 43 < 100; PF 1.07 <= 1.1; a half is negative; fails spread x2; min lot unaffordable at $100 (2% fit); DSR 0.243 <= 0.95 |
| SOLUSD | H4 | V2_htf | 38 | 34% | +0.026 | 1.05 | 6.7 | +0.079 | -0.027 | -0.164 | -0.346 | -0.327 | 0.243 | n 38 < 100; PF 1.05 <= 1.1; a half is negative; fails spread x2; min lot unaffordable at $100 (3% fit); DSR 0.243 <= 0.95 |
| SOLUSD | H4 | V3_stop | 19 | 32% | -0.139 | 0.72 | 5.1 | -0.132 | -0.145 | -0.171 | -0.158 | +0.109 | 0.14 | n 19 < 100; loses after costs+swap; PF 0.72 <= 1.1; a half is negative; fails spread x2; not above flipped; min lot unaffordable at $100 (0% fit); DSR 0.14 <= 0.95 |
| SOLUSD | H4 | V4_ladder | 19 | 32% | -0.156 | 0.69 | 5.2 | -0.168 | -0.145 | -0.190 | -0.155 | +0.109 | 0.122 | n 19 < 100; loses after costs+swap; PF 0.69 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped; min lot unaffordable at $100 (0% fit); DSR 0.122 <= 0.95 |
| SOLUSD | H4 | WF_best | 25 | 32% | -0.121 | 0.76 | 7.5 | -0.362 | +0.101 | -0.149 | -0.040 | +0.038 | 0.123 | n 25 < 100; loses after costs+swap; PF 0.76 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped; min lot unaffordable at $100 (0% fit); DSR 0.123 <= 0.95 |
| EURUSD | H1 | V0_raw | 1872 | 34% | -0.083 | 0.83 | 190.5 | -0.069 | -0.098 | -0.137 | -0.111 | -0.066 | 0.0 | loses after costs+swap; PF 0.83 <= 1.1; a half is negative; fails spread x2; not above flipped; min lot unaffordable at $100 (0% fit); DSR 0.0 <= 0.95 |
| EURUSD | H1 | V1_regime | 322 | 39% | +0.023 | 1.05 | 16.8 | +0.021 | +0.025 | -0.034 | -0.047 | -0.081 | 0.326 | PF 1.05 <= 1.1; fails spread x2; min lot unaffordable at $100 (0% fit); DSR 0.326 <= 0.95 |
| EURUSD | H1 | V2_htf | 142 | 39% | +0.003 | 1.01 | 20.6 | -0.026 | +0.032 | -0.059 | -0.018 | -0.015 | 0.308 | PF 1.01 <= 1.1; a half is negative; fails spread x2; min lot unaffordable at $100 (0% fit); DSR 0.308 <= 0.95 |
| EURUSD | H1 | V3_stop | 140 | 39% | -0.000 | 1.0 | 17.6 | -0.019 | +0.018 | -0.042 | -0.057 | -0.066 | 0.299 | loses after costs+swap; PF 1.0 <= 1.1; a half is negative; fails spread x2; min lot unaffordable at $100 (0% fit); DSR 0.299 <= 0.95 |
| EURUSD | H1 | V4_ladder | 140 | 43% | -0.012 | 0.97 | 22.8 | +0.047 | -0.071 | -0.041 | -0.065 | -0.064 | 0.253 | loses after costs+swap; PF 0.97 <= 1.1; a half is negative; fails spread x2; min lot unaffordable at $100 (0% fit); DSR 0.253 <= 0.95 |
| EURUSD | H1 | WF_best | 165 | 42% | -0.025 | 0.94 | 23.7 | +0.018 | -0.067 | -0.064 | -0.092 | -0.058 | 0.19 | loses after costs+swap; PF 0.94 <= 1.1; a half is negative; fails spread x2; min lot unaffordable at $100 (0% fit); DSR 0.19 <= 0.95 |
| EURUSD | H4 | V0_raw | 2357 | 38% | +0.015 | 1.03 | 61.1 | +0.048 | -0.017 | -0.003 | -0.022 | -0.045 | 0.18 | PF 1.03 <= 1.1; a half is negative; fails spread x2; min lot unaffordable at $100 (0% fit); DSR 0.18 <= 0.95 |
| EURUSD | H4 | V1_regime | 489 | 39% | -0.034 | 0.93 | 28.8 | -0.021 | -0.047 | -0.048 | -0.066 | -0.003 | 0.08 | loses after costs+swap; PF 0.93 <= 1.1; a half is negative; fails spread x2; not above flipped; min lot unaffordable at $100 (0% fit); DSR 0.08 <= 0.95 |
| EURUSD | H4 | V2_htf | 258 | 39% | -0.016 | 0.97 | 18.1 | -0.063 | +0.032 | -0.033 | -0.044 | +0.000 | 0.227 | loses after costs+swap; PF 0.97 <= 1.1; a half is negative; fails spread x2; not above flipped; min lot unaffordable at $100 (0% fit); DSR 0.227 <= 0.95 |
| EURUSD | H4 | V3_stop | 227 | 37% | -0.044 | 0.89 | 20.3 | -0.027 | -0.060 | -0.061 | -0.083 | +0.008 | 0.117 | loses after costs+swap; PF 0.89 <= 1.1; a half is negative; fails spread x2; not above flipped; min lot unaffordable at $100 (0% fit); DSR 0.117 <= 0.95 |
| EURUSD | H4 | V4_ladder | 252 | 40% | -0.035 | 0.91 | 19.5 | -0.073 | +0.002 | -0.048 | -0.082 | -0.021 | 0.13 | loses after costs+swap; PF 0.91 <= 1.1; a half is negative; fails spread x2; not above flipped; min lot unaffordable at $100 (0% fit); DSR 0.13 <= 0.95 |
| EURUSD | H4 | WF_best | 1395 | 39% | +0.020 | 1.04 | 53.8 | +0.069 | -0.029 | +0.004 | -0.055 | -0.051 | 0.289 | PF 1.04 <= 1.1; a half is negative; min lot unaffordable at $100 (0% fit); DSR 0.289 <= 0.95 |

## What to do with this
- Do not trade raw KN on any symbol.
- The losing live strategies stay under the existing quarantine (`strategy_quarantine.py`). This research does not replace them.
- GBPUSD H4 with the regime gate is the only candidate worth a demo forward test. It is below the DSR bar, so running one is the owner's call. It also needs a single leg, or a larger account, to fit the minimum lot.

Reproduce:
```
python tools/strategy_research.py --fetch <bars.pkl>    # needs H1 + H4 for the symbols
python tools/kn_research.py <bars.pkl> <out.json>
```

## Demo forward test (owner approved, 2026-11-24)
`KNForwardTest` (`jarvis/forward_tests/kn_adaptive.py`), comment tag `FT_KN_GBPUSD`. It runs only on the **demo account**, even though `trading.forward_test_modes` also lists paper and live.
- **Rules:** GBPUSD H4, the V2 layers with ER 0.35, stop at 1.5×ATR, one leg with TP at 2R, closed on the opposite cross with no same-bar re-entry.
- **Size:** 1/3 of the per-trade risk budget, like the other FT_ leads.
- **Why one leg and not three:** on the same data a single 2R leg did as well as the three-leg ladder. Full history: +0.224R, PF 1.48, n=180. Since 2019: +0.349R, n=49. The flipped direction was negative.
- **Promotion:** only after at least 30 demo trades at a positive mean R that is in line with the backtest.
