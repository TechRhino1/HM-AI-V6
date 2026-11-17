# Portfolio router research: trend universe, portfolio, regimes, meta-label (Phase C, 2026-11-17)

Research only. Nothing under `jarvis/` changed. Tools: `tools/strategy_research.py` (extended), `tools/portfolio_research.py` (new). Both have `--selftest` with look-ahead perturbation checks, and both pass.

## 1. Verdict

| Question | Answer |
|---|---|
| **Components that may be funded on the $545 account** | **None.** 12 symbol × strategy rows pass the per-component edge rule. Combined into the pre-registered portfolio, they **fail the gate at every min-lot cap from 1% to 5%**, in the pre-registered period (1974–2026) and in the modern sensitivity period (2016-11 to 2026). |
| **Why it fails** | **Drawdown.** The worst peak-to-trough drawdown is 64–85% (pre-registered) and 30–53% (modern), against the 20% halt. It is **not caused by the min-lot cap**: fractional lots (no min lot) also reach 64% in the pre-registered run. It comes from open-profit giveback: the vol target only resizes new entries, so a BTC/ETH trend trade that has run +100R swings the account by tens of percent. In the modern run, the Sharpe ratio also loses to equal-weight buy-and-hold (crypto-heavy, 1.13). |
| **Recommended min-lot cap** | **Keep 2.5%. Do not raise it to 5%.** No cap in 1–5% keeps drawdown inside the 20% halt, so the rule "reduce the cap until it does" has no answer. A 5% cap raises return but not safety (modern worst DD: 38% at 5% vs 53% at 2.5%, 30% at 4.5%: path noise, not a trend). |
| **Regime eligibility table** | **No regime filter adopted.** The pre-registered fit (folds 1–2) finds no losing cell, so everything stays eligible. Four cells flip sign on folds 3–4. The modern sensitivity marks two cells ineligible, but only one confirms out of sample (Donchian D1 entered in TREND, n = 89, −0.18R), and the pre-registered run contradicts it (+0.09R). |
| **News (±30 min of USD events)** | **No rule.** D1 entries never fall in the window. H4 entries rarely do (n = 12–53 per cell), and inside vs outside does not differ consistently. |
| **Meta-label v2** | **Rejected.** Mean out-of-sample AUC is 0.546, below the 0.55 bar. The top half did beat the bottom half in 5 of 5 folds, so there is a weak signal, but it does not clear the pre-registered gate. |
| **What still deserves demo forward-testing** | The **crypto Donchian** components: ETHUSD Donchian H4 / D1 and BTCUSD Donchian H4. Each is positive in all 4 modern folds on its own. ETHUSD Donchian H4 is already forward-tested. The forex components' edge is historical: since 2016 their expectancy is about 0 (EURUSD −0.19 to +0.02R, USDJPY +0.01 to +0.05R). |

Phase D consequence: the router may run the trend portfolio **on demo only**. Nothing qualifies for live allocation, and the live promotion rule (≥ 100 closed trades, mean ≥ +0.05R, drawdown inside the backtest band) applies unchanged.

## 2. Method

**Data.** Frozen closed bars from the XM terminal (`strategy_research.py --fetch-universe`), H1 (spread model) + H4 + D1, for 17 symbols:

- crypto: BTC, ETH, SOL;
- metals: XAU (`GOLD.i#`), XAG (`SILVER.i#`);
- forex: EUR, GBP, JPY, CAD, AUD, NZD, CHF majors (`#` symbols);
- indices: `US30Cash#`, `US100Cash#` (NAS100), `US500Cash#`, `GER40Cash#`, `UK100Cash#`.

Index CFDs start in 2011, metals in 2001/2006, forex in 1971–2007, crypto in 2013–2021.

**Candidates.** Unchanged from 2026-11-16, with fixed a-priori parameters:

- Donchian ensemble: 20/10, 55/20 and 100/20, with a 3×ATR trail;
- TSMOM ensemble: 1/3/6-month sign, with a fixed 3×ATR stop.

Both run on H4 and D1. Cost rules are unchanged: next-open entry, real per-bar spread (the recent median before the real-spread era), slippage, broker swap, and the stop assumed first.

**Per-component verdict.** `sr.verdict` is unchanged. Adoption into the portfolio uses `sr.edge_passes`: every verdict rule except min-lot affordability, because the account simulation applies the cap itself. The table now also reports the share of trades whose min lot fits **5% of $545** next to 2.5%.

**Portfolio (pre-registered in `tools/portfolio_research.py`; nothing fitted).**

- **Target risk per position:** equity at the previous UTC close × 1% (`max_risk_per_trade_pct`) × vol scale × HRP multiplier. Every stop is 3×ATR, so equal $ risk is ATR risk parity.
- **Vol scale:** clip(10% / annualised std of the account's own last 63 daily returns, 0.25, 2). It uses only past returns and a fixed target, with no full-sample constant (the Moreira-Muir look-ahead critique).
- **Correlation cap:** the multiplier is clip(w × N, 0, 2), where w comes from `jarvis.risk.hrp_allocator.allocate_hrp_weights` (imported read-only) on the components' daily R over the 756 days before each quarter.
- **Min lot:** lots are floored to the broker step. Below one min lot, take the min lot only if its risk ≤ cap × equity, else skip (`min_lot_max_risk_pct` semantics).
- **Live RiskEngine limits:** 3 open positions, 2 per symbol, first come first served. A 6-position variant is shown as sensitivity.
- **Marking:** daily mark-to-market at bar closes; swap booked at exit.
- **Folds:** 4 equal calendar folds, starting on the day half the components are live. Each fold is also a fresh $545 account.
- **Gate:** final equity > start in ≥ 3/4 folds, Sharpe > equal-weight buy-and-hold Sharpe, and max DD < 20% in the full run and every fold. The drawdown is measured from peak, because the live `DrawdownGuard` uses peak equity.

**Regime.** `smc_research.regime` on the trade's own TF, decision bar (completed): HIGH_VOL_SHOCK if ATR5/ATR50 > 1.8; TREND if ADX ≥ 25; DEAD if BB-width percentile < 0.2 and ATR ratio < 0.8; else RANGE. A family × regime cell is ineligible if folds 1–2 hold ≥ 30 trades with expectancy ≤ 0. The filter is adopted only if the ineligible cells lose on folds 3–4 (≥ 30 trades) and the eligible ones beat the unfiltered set.

**Meta-label v2.**

- **Trades:** 2018+ trades only, where news coverage exists (6,626 trades).
- **Features (new):** regime one-hot, variance ratio, hours since / to the nearest USD event, side × US500 20-day return, ATR5/ATR50, entry session one-hot.
- **Model:** logistic regression, label R > 0.
- **CV:** `jarvis.learning.walk_forward.PurgedKFold` (5 splits, 2% embargo). On top of it, train trades whose life overlaps the test window are purged, because `PurgedKFold` only embargoes and does not purge by label span.

**Selftests (`--selftest`).**

- `strategy_research`: Donchian/TSMOM signals and exit flags up to bar k are identical when bars after k are perturbed.
- `portfolio_research`:
  - a trade entering on day 30 leaves equity and sizing before day 30 unchanged;
  - HRP multipliers for a quarter ignore later data;
  - regime labels and the cross-asset feature at bar k ignore later bars;
  - min-lot cap and position-limit arithmetic match hand-computed values.
- The refactored `strategy_research` reproduces every crypto/gold row of `CRYPTO_GOLD_RESEARCH_2026-11-16.md` exactly.

## 3. Per-component results (68 rows, H4/D1)

Exp R is per trade, net of costs and swap. "Real-spread era" is 2018-10+ for forex and indices (H1 history start), 2018+ for gold and crypto.

| Symbol | Candidate | TF | n | Exp R | PF | 1st / 2nd half | Spread x2 | Always long | Flipped | Real-spread era: n, strat / long / flip | Min-lot risk (median) | Fit $545 @2.5% | Fit $545 @5% | Edge verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTCUSD | donchian_ens | D1 | 223 | +0.637 | 2.74 | +1.214 / +0.064 | +0.634 | +0.657 | -0.317 | 88: 0.074 / 0.27 / 0.003 | $24.95 | 37% | 53% | rejected: not above always-long |
| BTCUSD | tsmom_ens | D1 | 385 | +1.896 | 6.73 | +3.577 / +0.223 | +1.892 | +1.858 | -0.157 | 159: 0.23 / 0.31 / -0.035 | $22.65 | 36% | 55% | **passes** |
| BTCUSD | donchian_ens | H4 | 1036 | +0.338 | 1.85 | +0.546 / +0.130 | +0.329 | +0.267 | -0.141 | 465: 0.178 / 0.227 / -0.021 | $16.28 | 48% | 69% | **passes** |
| BTCUSD | tsmom_ens | H4 | 799 | +1.107 | 3.84 | +2.019 / +0.197 | +1.061 | +1.073 | -0.090 | 426: 0.205 / 0.333 / 0.02 | $14.29 | 49% | 71% | **passes** |
| ETHUSD | donchian_ens | D1 | 175 | +0.236 | 1.73 | +0.428 / +0.047 | +0.230 | +0.144 | -0.270 | 79: 0.119 / 0.075 / -0.141 | $5.42 | 92% | 100% | **passes** |
| ETHUSD | tsmom_ens | D1 | 330 | +0.476 | 2.6 | +0.957 / -0.006 | +0.466 | +0.471 | -0.115 | 192: 0.002 / 0.06 / -0.025 | $4.70 | 93% | 100% | rejected: a half is negative |
| ETHUSD | donchian_ens | H4 | 1042 | +0.219 | 1.47 | +0.358 / +0.081 | +0.198 | +0.140 | -0.197 | 465: 0.114 / 0.081 / -0.012 | $1.95 | 100% | 100% | **passes** |
| ETHUSD | tsmom_ens | H4 | 838 | +0.847 | 3.04 | +1.650 / +0.044 | +0.825 | +0.869 | -0.078 | 491: 0.045 / 0.098 / -0.033 | $1.93 | 100% | 100% | rejected: not above always-long |
| SOLUSD | donchian_ens | D1 | 92 | +0.357 | 1.91 | +0.901 / -0.186 | +0.339 | +0.301 | -0.234 | 80: 0.364 / 0.47 / -0.252 | $10.68 | 64% | 100% | rejected: a half is negative |
| SOLUSD | tsmom_ens | D1 | 180 | +0.253 | 1.72 | +0.723 / -0.217 | +0.220 | +0.228 | -0.212 | 155: 0.265 / 0.336 / -0.196 | $8.50 | 69% | 98% | rejected: a half is negative |
| SOLUSD | donchian_ens | H4 | 635 | -0.026 | 0.94 | +0.047 / -0.098 | -0.106 | -0.086 | -0.196 | 488: -0.017 / -0.027 / -0.209 | $3.98 | 99% | 100% | rejected: loses after costs+swap; PF 0.94 <= 1.1; a half is negative; fails spread x2 |
| SOLUSD | tsmom_ens | H4 | 512 | +0.157 | 1.33 | +0.522 / -0.207 | +0.102 | +0.157 | -0.203 | 414: 0.175 / 0.23 / -0.221 | $3.14 | 99% | 100% | rejected: a half is negative; not above always-long |
| XAUUSD | donchian_ens | D1 | 390 | +0.155 | 1.44 | +0.107 / +0.203 | +0.152 | +0.315 | -0.125 | 119: 0.37 / 0.542 / -0.244 | $55.33 | 2% | 17% | rejected: not above always-long |
| XAUUSD | tsmom_ens | D1 | 893 | +0.124 | 1.48 | +0.143 / +0.105 | +0.119 | +0.218 | -0.015 | 256: 0.204 / 0.322 / -0.012 | $51.82 | 2% | 18% | rejected: not above always-long |
| XAUUSD | donchian_ens | H4 | 1225 | +0.108 | 1.29 | +0.131 / +0.085 | +0.095 | +0.166 | -0.090 | 729: 0.109 / 0.2 / -0.081 | $27.76 | 6% | 47% | rejected: not above always-long |
| XAUUSD | tsmom_ens | H4 | 1335 | +0.217 | 1.64 | +0.186 / +0.248 | +0.209 | +0.270 | -0.012 | 686: 0.238 / 0.334 / -0.002 | $24.16 | 5% | 59% | rejected: not above always-long |
| EURUSD | donchian_ens | D1 | 923 | +0.466 | 2.29 | +0.858 / +0.075 | +0.460 | +0.262 | -0.175 | 150: -0.26 / -0.013 / 0.128 | $23.39 | 21% | 62% | **passes** |
| EURUSD | tsmom_ens | D1 | 1922 | +0.305 | 2.1 | +0.532 / +0.079 | +0.300 | +0.207 | -0.064 | 317: -0.014 / -0.068 / -0.051 | $25.25 | 16% | 55% | **passes** |
| EURUSD | donchian_ens | H4 | 3013 | +0.072 | 1.19 | +0.208 / -0.064 | +0.066 | +0.017 | -0.056 | 782: -0.065 / -0.074 / -0.004 | $11.87 | 64% | 94% | rejected: a half is negative |
| EURUSD | tsmom_ens | H4 | 3043 | +0.101 | 1.29 | +0.185 / +0.017 | +0.093 | +0.074 | +0.002 | 826: -0.036 / -0.059 / -0.014 | $11.20 | 68% | 94% | **passes** |
| GBPUSD | donchian_ens | D1 | 546 | -0.089 | 0.78 | -0.053 / -0.125 | -0.090 | -0.039 | +0.031 | 144: -0.165 / -0.118 / 0.017 | $36.56 | 0% | 16% | rejected: loses after costs+swap; PF 0.78 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped |
| GBPUSD | tsmom_ens | D1 | 1350 | -0.003 | 0.99 | +0.012 / -0.019 | -0.006 | +0.001 | -0.005 | 345: -0.072 / -0.055 / -0.021 | $36.69 | 0% | 16% | rejected: loses after costs+swap; PF 0.99 <= 1.1; a half is negative; fails spread x2; not above always-long |
| GBPUSD | donchian_ens | H4 | 2656 | -0.024 | 0.94 | -0.044 / -0.003 | -0.029 | +0.006 | +0.016 | 802: -0.093 / -0.039 / 0.046 | $14.32 | 44% | 95% | rejected: loses after costs+swap; PF 0.94 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped |
| GBPUSD | tsmom_ens | H4 | 2924 | +0.002 | 1.01 | +0.028 / -0.024 | -0.005 | -0.012 | -0.023 | 915: -0.117 / -0.058 / 0.012 | $13.75 | 49% | 95% | rejected: PF 1.01 <= 1.1; a half is negative; fails spread x2 |
| USDJPY | donchian_ens | D1 | 948 | +0.701 | 2.83 | +1.319 / +0.083 | +0.698 | +0.181 | -0.204 | 138: 0.036 / 0.082 / 0.0 | $17.96 | 27% | 87% | **passes** |
| USDJPY | tsmom_ens | D1 | 1964 | +0.457 | 2.6 | +0.845 / +0.069 | +0.453 | +0.132 | -0.063 | 290: 0.021 / 0.138 / 0.014 | $18.79 | 25% | 86% | **passes** |
| USDJPY | donchian_ens | H4 | 3001 | +0.130 | 1.34 | +0.221 / +0.040 | +0.125 | +0.037 | -0.060 | 795: 0.007 / 0.064 / -0.011 | $7.98 | 85% | 97% | **passes** |
| USDJPY | tsmom_ens | H4 | 3066 | +0.180 | 1.53 | +0.243 / +0.118 | +0.173 | +0.050 | -0.033 | 748: 0.026 / 0.097 / -0.022 | $7.57 | 90% | 98% | **passes** |
| USDCAD | donchian_ens | D1 | 505 | +0.028 | 1.07 | +0.079 / -0.024 | +0.023 | +0.102 | +0.046 | 133: -0.113 / 0.125 / 0.114 | $17.52 | 17% | 92% | rejected: PF 1.07 <= 1.1; a half is negative; not above always-long; not above flipped |
| USDCAD | tsmom_ens | D1 | 1384 | -0.014 | 0.94 | +0.013 / -0.041 | -0.021 | +0.024 | +0.000 | 357: -0.068 / 0.002 / -0.019 | $17.42 | 20% | 91% | rejected: loses after costs+swap; PF 0.94 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped |
| USDCAD | donchian_ens | H4 | 2576 | -0.037 | 0.91 | -0.105 / +0.032 | -0.053 | -0.014 | -0.015 | 760: -0.028 / -0.007 / -0.011 | $7.42 | 95% | 100% | rejected: loses after costs+swap; PF 0.91 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped |
| USDCAD | tsmom_ens | H4 | 3205 | -0.048 | 0.86 | -0.040 / -0.057 | -0.063 | -0.015 | -0.026 | 943: -0.09 / -0.022 / -0.026 | $7.15 | 95% | 100% | rejected: loses after costs+swap; PF 0.86 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped |
| AUDUSD | donchian_ens | D1 | 301 | +0.016 | 1.04 | +0.230 / -0.197 | +0.012 | -0.046 | +0.054 | 136: -0.206 / -0.038 / 0.166 | $22.03 | 7% | 69% | rejected: PF 1.04 <= 1.1; a half is negative; not above flipped |
| AUDUSD | tsmom_ens | D1 | 820 | +0.004 | 1.01 | +0.054 / -0.047 | -0.002 | -0.032 | -0.015 | 366: -0.067 / -0.055 / -0.02 | $21.51 | 6% | 69% | rejected: PF 1.01 <= 1.1; a half is negative; fails spread x2 |
| AUDUSD | donchian_ens | H4 | 1018 | -0.058 | 0.86 | +0.032 / -0.149 | -0.076 | -0.054 | +0.048 | 805: -0.101 / -0.049 / 0.051 | $7.92 | 82% | 92% | rejected: loses after costs+swap; PF 0.86 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped |
| AUDUSD | tsmom_ens | H4 | 1156 | -0.038 | 0.88 | +0.029 / -0.105 | -0.052 | -0.070 | -0.054 | 921: -0.057 / -0.063 / -0.056 | $7.40 | 84% | 94% | rejected: loses after costs+swap; PF 0.88 <= 1.1; a half is negative; fails spread x2 |
| NZDUSD | donchian_ens | D1 | 325 | -0.152 | 0.63 | -0.103 / -0.202 | -0.158 | -0.101 | +0.017 | 145: -0.194 / -0.205 / -0.0 | $21.40 | 5% | 74% | rejected: loses after costs+swap; PF 0.63 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped |
| NZDUSD | tsmom_ens | D1 | 815 | -0.045 | 0.82 | +0.021 / -0.110 | -0.053 | -0.059 | -0.025 | 371: -0.117 / -0.099 / -0.011 | $21.08 | 5% | 79% | rejected: loses after costs+swap; PF 0.82 <= 1.1; a half is negative; fails spread x2; not above flipped |
| NZDUSD | donchian_ens | H4 | 1014 | -0.078 | 0.81 | -0.019 / -0.138 | -0.092 | -0.065 | -0.001 | 799: -0.09 / -0.065 / 0.001 | $7.48 | 82% | 92% | rejected: loses after costs+swap; PF 0.81 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped |
| NZDUSD | tsmom_ens | H4 | 1165 | -0.123 | 0.66 | -0.090 / -0.156 | -0.147 | -0.117 | -0.008 | 914: -0.123 / -0.118 / -0.038 | $7.17 | 84% | 94% | rejected: loses after costs+swap; PF 0.66 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped |
| USDCHF | donchian_ens | D1 | 953 | +0.332 | 1.81 | +0.676 / -0.011 | +0.329 | -0.002 | -0.147 | 130: -0.142 / -0.08 / -0.012 | $39.61 | 2% | 28% | rejected: a half is negative |
| USDCHF | tsmom_ens | D1 | 2084 | +0.227 | 1.75 | +0.524 / -0.070 | +0.223 | -0.001 | -0.041 | 367: -0.076 / -0.056 / 0.009 | $39.02 | 1% | 32% | rejected: a half is negative |
| USDCHF | donchian_ens | H4 | 2977 | +0.045 | 1.11 | +0.105 / -0.016 | +0.033 | -0.034 | -0.036 | 788: -0.084 / -0.051 / -0.005 | $14.36 | 47% | 82% | rejected: a half is negative |
| USDCHF | tsmom_ens | H4 | 3345 | -0.015 | 0.96 | +0.080 / -0.110 | -0.025 | -0.068 | -0.016 | 927: -0.064 / -0.061 / -0.019 | $13.71 | 50% | 86% | rejected: loses after costs+swap; PF 0.96 <= 1.1; a half is negative; fails spread x2 |
| US30 | donchian_ens | D1 | 272 | -0.148 | 0.65 | -0.063 / -0.232 | -0.158 | +0.012 | -0.019 | 158: -0.237 / -0.109 / -0.058 | $96.74 | 0% | 0% | rejected: loses after costs+swap; PF 0.65 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped |
| US30 | tsmom_ens | D1 | 533 | -0.114 | 0.62 | -0.115 / -0.112 | -0.118 | -0.039 | -0.091 | 282: -0.13 / -0.09 / -0.15 | $96.10 | 0% | 0% | rejected: loses after costs+swap; PF 0.62 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped |
| US30 | donchian_ens | H4 | 1125 | -0.041 | 0.9 | -0.015 / -0.066 | -0.054 | +0.048 | +0.019 | 856: -0.042 / 0.016 / 0.016 | $45.70 | 2% | 17% | rejected: loses after costs+swap; PF 0.9 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped |
| US30 | tsmom_ens | H4 | 959 | -0.106 | 0.72 | -0.060 / -0.152 | -0.114 | -0.015 | -0.052 | 759: -0.14 / -0.05 / -0.044 | $49.59 | 1% | 12% | rejected: loses after costs+swap; PF 0.72 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped |
| NAS100 | donchian_ens | D1 | 270 | -0.070 | 0.81 | -0.200 / +0.059 | -0.077 | +0.143 | -0.065 | 98: -0.007 / 0.204 / 0.006 | $36.07 | 21% | 43% | rejected: loses after costs+swap; PF 0.81 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped |
| NAS100 | tsmom_ens | D1 | 445 | -0.020 | 0.94 | -0.037 / -0.003 | -0.027 | +0.113 | -0.044 | 164: 0.009 / 0.088 / -0.057 | $38.86 | 19% | 42% | rejected: loses after costs+swap; PF 0.94 <= 1.1; a half is negative; fails spread x2; not above always-long |
| NAS100 | donchian_ens | H4 | 1151 | -0.027 | 0.93 | -0.045 / -0.009 | -0.036 | +0.073 | -0.069 | 602: -0.021 / 0.052 / -0.062 | $24.23 | 28% | 56% | rejected: loses after costs+swap; PF 0.93 <= 1.1; a half is negative; fails spread x2; not above always-long |
| NAS100 | tsmom_ens | H4 | 783 | +0.041 | 1.1 | +0.069 / +0.014 | +0.031 | +0.175 | -0.056 | 435: 0.031 / 0.083 / -0.075 | $30.11 | 27% | 46% | rejected: PF 1.1 <= 1.1; not above always-long |
| US500 | donchian_ens | D1 | 281 | -0.154 | 0.6 | -0.160 / -0.148 | -0.159 | -0.014 | -0.085 | 165: -0.147 / -0.019 / -0.119 | $11.41 | 57% | 90% | rejected: loses after costs+swap; PF 0.6 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped |
| US500 | tsmom_ens | D1 | 466 | -0.086 | 0.71 | -0.118 / -0.054 | -0.092 | +0.007 | -0.105 | 250: -0.078 / -0.001 / -0.105 | $11.01 | 57% | 90% | rejected: loses after costs+swap; PF 0.71 <= 1.1; a half is negative; fails spread x2; not above always-long |
| US500 | donchian_ens | H4 | 1185 | -0.116 | 0.73 | -0.106 / -0.126 | -0.125 | +0.010 | +0.027 | 898: -0.091 / 0.009 / 0.028 | $5.83 | 95% | 100% | rejected: loses after costs+swap; PF 0.73 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped |
| US500 | tsmom_ens | H4 | 825 | -0.019 | 0.95 | -0.043 / +0.004 | -0.029 | +0.052 | -0.085 | 661: -0.021 / 0.034 / -0.086 | $6.89 | 96% | 100% | rejected: loses after costs+swap; PF 0.95 <= 1.1; a half is negative; fails spread x2; not above always-long |
| GER40 | donchian_ens | D1 | 272 | -0.198 | 0.55 | -0.127 / -0.269 | -0.201 | -0.045 | +0.031 | 35: -0.357 / 0.038 / 0.238 | $56.32 | 0% | 3% | rejected: loses after costs+swap; PF 0.55 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped |
| GER40 | tsmom_ens | D1 | 569 | -0.093 | 0.68 | -0.107 / -0.080 | -0.097 | -0.002 | -0.008 | 85: -0.194 / -0.051 / 0.008 | $58.65 | 0% | 3% | rejected: loses after costs+swap; PF 0.68 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped |
| GER40 | donchian_ens | H4 | 1070 | -0.034 | 0.92 | +0.010 / -0.078 | -0.039 | +0.051 | +0.017 | 186: -0.146 / 0.028 / 0.051 | $25.01 | 3% | 56% | rejected: loses after costs+swap; PF 0.92 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped |
| GER40 | tsmom_ens | H4 | 1065 | -0.066 | 0.83 | -0.057 / -0.075 | -0.073 | +0.008 | -0.064 | 227: -0.3 / -0.142 / -0.035 | $25.67 | 2% | 56% | rejected: loses after costs+swap; PF 0.83 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped |
| UK100 | donchian_ens | D1 | 245 | -0.282 | 0.38 | -0.329 / -0.235 | -0.287 | -0.108 | +0.024 | 42: -0.148 / 0.261 / -0.101 | $26.08 | 0% | 61% | rejected: loses after costs+swap; PF 0.38 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped |
| UK100 | tsmom_ens | D1 | 670 | -0.184 | 0.41 | -0.198 / -0.170 | -0.190 | -0.109 | -0.005 | 112: -0.126 / 0.101 / 0.035 | $25.62 | 1% | 58% | rejected: loses after costs+swap; PF 0.41 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped |
| UK100 | donchian_ens | H4 | 1036 | -0.128 | 0.7 | -0.147 / -0.109 | -0.142 | -0.084 | -0.064 | 255: -0.127 / -0.047 / -0.06 | $10.58 | 71% | 97% | rejected: loses after costs+swap; PF 0.7 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped |
| UK100 | tsmom_ens | H4 | 1272 | -0.191 | 0.5 | -0.171 / -0.211 | -0.207 | -0.133 | -0.077 | 329: -0.163 / -0.054 / -0.063 | $10.78 | 69% | 96% | rejected: loses after costs+swap; PF 0.5 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped |
| XAGUSD | donchian_ens | D1 | 296 | +0.087 | 1.22 | +0.113 / +0.061 | +0.050 | +0.162 | +0.003 | 117: 0.121 / 0.335 / 0.076 | $81.88 | 0% | 0% | rejected: not above always-long |
| XAGUSD | tsmom_ens | D1 | 786 | -0.007 | 0.98 | +0.029 / -0.043 | -0.030 | +0.076 | -0.009 | 333: -0.018 / 0.131 / -0.008 | $79.63 | 0% | 0% | rejected: loses after costs+swap; PF 0.98 <= 1.1; a half is negative; fails spread x2; not above always-long |
| XAGUSD | donchian_ens | H4 | 987 | -0.033 | 0.92 | -0.075 / +0.010 | -0.066 | -0.013 | -0.078 | 749: -0.026 / 0.001 / -0.07 | $41.29 | 7% | 21% | rejected: loses after costs+swap; PF 0.92 <= 1.1; a half is negative; fails spread x2; not above always-long |
| XAGUSD | tsmom_ens | H4 | 1126 | -0.020 | 0.95 | +0.011 / -0.051 | -0.054 | +0.066 | -0.060 | 879: -0.029 / 0.094 / -0.025 | $38.29 | 6% | 22% | rejected: loses after costs+swap; PF 0.95 <= 1.1; a half is negative; fails spread x2; not above always-long |

**Components passing the edge rule (12):**

- BTCUSD: TSMOM D1, Donchian H4, TSMOM H4;
- ETHUSD: Donchian D1, Donchian H4;
- EURUSD: Donchian D1, TSMOM D1, TSMOM H4;
- USDJPY: Donchian D1/H4, TSMOM D1/H4.

Forex note: all four USDJPY and three EURUSD rows pass on 1971–2026, but in the real-spread era (2018-10+) EURUSD is negative (−0.26 to −0.01R) and USDJPY is below always-long (+0.01 to +0.04R vs +0.06 to +0.14R). Their edge is the 1970s–2000s trend era. Verdict rules do not look at the real-era column, so they enter the portfolio. The modern-period run below shows the cost of that.

## 4. Portfolio results

Rows are sizing variants:

- `fractional`: no min lot, the pure design;
- `minlot_X`: broker min lot with cap X;
- `_open6`: 6 positions instead of 3.

Fold cells show the final $ of a fresh $545 account and its max drawdown.

### 4a. Pre-registered period (start = day half the components are live = 1974-08)

| Run | CAGR | Sharpe | Max DD (full) | Folds: final $ / max DD | Worst DD | Positive folds | Trades taken | Skipped (over cap) | Skipped (position limits) | Gate |
|---|---|---|---|---|---|---|---|---|---|---|
| Buy & hold, equal weight | 10.9% | 0.48 | 62% | 474 / 27% · 455 / 27% · 1,859 / 31% · 49,543 / 62% | | | | | | benchmark |
| fractional | 14.4% | 0.87 | 64% | 10,623 / 21% · 1,405 / 16% · 775 / 25% · 6,901 / 64% | 64% | 4/4 | 2714 | 0.0% | 15280 | fail: max DD 63.9% >= 20% halt |
| minlot_0.050 | 13.8% | 0.84 | 64% | 8,295 / 24% · 1,908 / 33% · 1,498 / 59% · 2,731 / 73% | 73% | 4/4 | 2714 | 0.0% | 15280 | fail: max DD 72.6% >= 20% halt |
| minlot_0.045 | 13.8% | 0.84 | 64% | 8,295 / 24% · 1,652 / 33% · 1,120 / 64% · 2,523 / 84% | 84% | 4/4 | 2714 | 0.0% | 15280 | fail: max DD 84.0% >= 20% halt |
| minlot_0.040 | 13.2% | 0.8 | 64% | 6,419 / 42% · 1,796 / 33% · 270 / 85% · 2,698 / 84% | 85% | 3/4 | 2738 | 0.0% | 15255 | fail: max DD 85.2% >= 20% halt |
| minlot_0.035 | 13.2% | 0.8 | 64% | 6,429 / 41% · 1,948 / 29% · 304 / 82% · 1,794 / 79% | 82% | 3/4 | 2737 | 0.1% | 15254 | fail: max DD 82.0% >= 20% halt |
| minlot_0.030 | 14.0% | 0.86 | 64% | 9,471 / 20% · 1,932 / 27% · 366 / 75% · 2,006 / 78% | 78% | 3/4 | 2742 | 0.2% | 15247 | fail: max DD 78.1% >= 20% halt |
| minlot_0.025 | 13.0% | 0.8 | 64% | 6,019 / 22% · 2,176 / 18% · 446 / 63% · 2,070 / 44% | 64% | 3/4 | 2732 | 0.4% | 15252 | fail: max DD 63.9% >= 20% halt |
| minlot_0.020 | 13.5% | 0.83 | 64% | 7,033 / 20% · 1,503 / 16% · 1,894 / 37% · 2,172 / 39% | 64% | 4/4 | 2728 | 0.8% | 15244 | fail: max DD 63.9% >= 20% halt |
| minlot_0.015 | 13.3% | 0.82 | 64% | 6,435 / 20% · 2,129 / 16% · 1,060 / 33% · 2,458 / 42% | 64% | 4/4 | 2706 | 3.3% | 15197 | fail: max DD 63.9% >= 20% halt |
| minlot_0.010 | 12.7% | 0.8 | 64% | 4,743 / 19% · 1,982 / 16% · 902 / 31% · 2,187 / 43% | 64% | 4/4 | 2678 | 13.2% | 14910 | fail: max DD 63.9% >= 20% halt |
| minlot_0.050_open6 | 13.0% | 0.89 | 41% | 11,962 / 22% · 1,955 / 34% · 2,027 / 66% · 1,327 / 78% | 78% | 4/4 | 4557 | 0.0% | 13437 | fail: max DD 78.3% >= 20% halt |
| minlot_0.025_open6 | 12.9% | 0.86 | 41% | 11,437 / 20% · 2,230 / 20% · 1,797 / 55% · 1,506 / 69% | 69% | 4/4 | 4581 | 0.3% | 13401 | fail: max DD 69.4% >= 20% halt |
| fractional_open6 | 13.1% | 0.89 | 41% | 12,066 / 19% · 1,965 / 20% · 1,119 / 33% · 2,437 / 41% | 41% | 4/4 | 4557 | 0.0% | 13437 | fail: max DD 40.8% >= 20% halt |

Components alone (min lot at cap 5%, same sizing):

| Component | n in period | Exp R in period | CAGR | Sharpe | Max DD | Skipped over cap | Fold finals $ |
|---|---|---|---|---|---|---|---|
| BTCUSD donchian_ens H4 | 1036 | +0.338 | 3.5% | 0.46 | 27% | 0.0% | – · – · 573 · 4,089 |
| BTCUSD tsmom_ens D1 | 385 | +1.896 | 5.3% | 0.42 | 58% | 0.0% | – · – · 875 · 5,146 |
| BTCUSD tsmom_ens H4 | 799 | +1.107 | 4.8% | 0.42 | 53% | 0.0% | – · – · 525 · 6,325 |
| ETHUSD donchian_ens D1 | 175 | +0.236 | 0.9% | 0.24 | 14% | 0.0% | – · – · – · 889 |
| ETHUSD donchian_ens H4 | 1042 | +0.219 | 3.0% | 0.45 | 24% | 0.0% | – · – · – · 2,585 |
| EURUSD donchian_ens D1 | 870 | +0.329 | 5.5% | 0.62 | 34% | 0.0% | 3,657 · 1,076 · 1,127 · 448 |
| EURUSD tsmom_ens D1 | 1833 | +0.214 | 5.2% | 0.56 | 30% | 0.0% | 3,030 · 1,605 · 1,466 · 654 |
| EURUSD tsmom_ens H4 | 3036 | +0.103 | 2.7% | 0.25 | 53% | 0.2% | 1,546 · 602 · 1,511 · 496 |
| USDJPY donchian_ens D1 | 886 | +0.438 | 7.0% | 0.72 | 28% | 0.0% | 6,459 · 1,451 · 537 · 717 |
| USDJPY donchian_ens H4 | 3001 | +0.130 | 6.6% | 0.6 | 44% | 0.0% | 6,459 · 1,390 · 284 · 852 |
| USDJPY tsmom_ens D1 | 1865 | +0.328 | 7.7% | 0.72 | 31% | 0.0% | 9,208 · 1,567 · 647 · 478 |
| USDJPY tsmom_ens H4 | 3066 | +0.180 | 4.2% | 0.38 | 51% | 0.0% | 2,840 · 632 · 382 · 957 |

Walk-forward selection (components chosen on trades closed before each fold):

- fold 2: 7 components; final $1,908, Sharpe 0.59, max DD 33%, 510 trades
- fold 3: 7 components; final $1,498, Sharpe 0.41, max DD 59%, 1356 trades
- fold 4: 7 components; final $920, Sharpe 0.28, max DD 67%, 1079 trades

### 4b. Modern sensitivity (start 2016-11-08, when every component is live; chosen after seeing 4a, so not a gate)

| Run | CAGR | Sharpe | Max DD (full) | Folds: final $ / max DD | Worst DD | Positive folds | Trades taken | Skipped (over cap) | Skipped (position limits) | Gate |
|---|---|---|---|---|---|---|---|---|---|---|
| Buy & hold, equal weight | 40.8% | 1.13 | 62% | 2,838 / 62% · 2,949 / 37% · 597 / 49% · 545 / 34% | | | | | | benchmark |
| fractional | 10.5% | 0.97 | 11% | 693 / 11% · 666 / 11% · 759 / 6% · 560 / 12% | 12% | 4/4 | 734 | 0.0% | 6575 | fail: Sharpe 0.97 <= buy-hold 1.13 |
| minlot_0.050 | 20.8% | 1.05 | 25% | 866 / 25% · 1,394 / 24% · 768 / 34% · 619 / 38% | 38% | 4/4 | 712 | 0.7% | 6592 | fail: Sharpe 1.05 <= buy-hold 1.13; max DD 38.1% >= 20% halt |
| minlot_0.045 | 17.9% | 0.92 | 25% | 866 / 25% · 1,394 / 24% · 1,190 / 30% · 680 / 29% | 30% | 4/4 | 781 | 1.1% | 6519 | fail: Sharpe 0.92 <= buy-hold 1.13; max DD 29.7% >= 20% halt |
| minlot_0.040 | 17.5% | 0.85 | 35% | 750 / 35% · 1,370 / 23% · 933 / 28% · 662 / 24% | 35% | 4/4 | 742 | 2.9% | 6545 | fail: Sharpe 0.85 <= buy-hold 1.13; max DD 35.0% >= 20% halt |
| minlot_0.035 | 18.9% | 0.87 | 35% | 678 / 35% · 1,563 / 19% · 1,007 / 25% · 614 / 26% | 35% | 4/4 | 830 | 3.6% | 6448 | fail: Sharpe 0.87 <= buy-hold 1.13; max DD 34.8% >= 20% halt |
| minlot_0.030 | 19.5% | 0.89 | 39% | 590 / 39% · 1,393 / 30% · 443 / 33% · 650 / 27% | 39% | 3/4 | 774 | 6.0% | 6486 | fail: Sharpe 0.89 <= buy-hold 1.13; max DD 39.4% >= 20% halt |
| minlot_0.025 | 12.9% | 0.63 | 47% | 452 / 47% · 1,344 / 33% · 342 / 53% · 438 / 33% | 53% | 1/4 | 1043 | 18.1% | 6035 | fail: positive in 1/4 folds; Sharpe 0.63 <= buy-hold 1.13; max DD 52.7% >= 20% halt |
| minlot_0.020 | 14.5% | 0.75 | 39% | 575 / 39% · 1,498 / 25% · 519 / 36% · 403 / 38% | 39% | 2/4 | 1019 | 18.3% | 6061 | fail: positive in 2/4 folds; Sharpe 0.75 <= buy-hold 1.13; max DD 38.7% >= 20% halt |
| minlot_0.015 | 14.4% | 0.71 | 52% | 867 / 52% · 1,090 / 12% · 578 / 32% · 346 / 40% | 52% | 3/4 | 862 | 19.6% | 6237 | fail: Sharpe 0.71 <= buy-hold 1.13; max DD 51.9% >= 20% halt |
| minlot_0.010 | 8.5% | 0.54 | 46% | 869 / 42% · 990 / 17% · 814 / 12% · 496 / 18% | 46% | 3/4 | 1262 | 35.1% | 5364 | fail: Sharpe 0.54 <= buy-hold 1.13; max DD 46.3% >= 20% halt |
| minlot_0.050_open6 | 16.0% | 0.72 | 33% | 1,011 / 31% · 951 / 42% · 1,150 / 45% · 263 / 80% | 80% | 3/4 | 1877 | 0.6% | 5420 | fail: Sharpe 0.72 <= buy-hold 1.13; max DD 79.6% >= 20% halt |
| minlot_0.025_open6 | 9.1% | 0.45 | 46% | 748 / 45% · 823 / 34% · 587 / 32% · 166 / 72% | 72% | 3/4 | 2051 | 15.5% | 4883 | fail: Sharpe 0.45 <= buy-hold 1.13; max DD 71.6% >= 20% halt |
| fractional_open6 | 10.1% | 0.81 | 19% | 775 / 19% · 685 / 11% · 644 / 12% · 601 / 12% | 19% | 4/4 | 1744 | 0.0% | 5565 | fail: Sharpe 0.81 <= buy-hold 1.13 |

Components alone (min lot at cap 5%, same sizing):

| Component | n in period | Exp R in period | CAGR | Sharpe | Max DD | Skipped over cap | Fold finals $ |
|---|---|---|---|---|---|---|---|
| BTCUSD donchian_ens H4 | 994 | +0.313 | 17.7% | 0.96 | 31% | 0.0% | 1,456 · 967 · 864 · 679 |
| BTCUSD tsmom_ens D1 | 306 | +0.637 | 14.0% | 0.74 | 27% | 16.5% | 829 · 1,319 · 587 · 545 |
| BTCUSD tsmom_ens H4 | 779 | +0.916 | 36.0% | 1.09 | 58% | 0.0% | 2,449 · 1,721 · 1,225 · 557 |
| ETHUSD donchian_ens D1 | 175 | +0.236 | 5.0% | 0.56 | 14% | 0.0% | 603 · 704 · 561 · 583 |
| ETHUSD donchian_ens H4 | 1042 | +0.219 | 16.9% | 1.03 | 24% | 0.0% | 904 · 850 · 675 · 692 |
| EURUSD donchian_ens D1 | 181 | -0.188 | -6.3% | -0.5 | 61% | 64.1% | 511 · 440 · 438 · 522 |
| EURUSD tsmom_ens D1 | 381 | +0.017 | 1.2% | 0.16 | 40% | 13.2% | 630 · 451 · 462 · 644 |
| EURUSD tsmom_ens H4 | 995 | -0.008 | -0.4% | 0.1 | 39% | 0.0% | 572 · 512 · 570 · 505 |
| USDJPY donchian_ens D1 | 168 | +0.051 | 3.7% | 0.32 | 28% | 2.3% | 632 · 461 · 791 · 530 |
| USDJPY donchian_ens H4 | 970 | +0.009 | 0.9% | 0.14 | 33% | 0.0% | 594 · 507 · 590 · 528 |
| USDJPY tsmom_ens D1 | 367 | +0.023 | -0.8% | 0.03 | 44% | 4.9% | 637 · 475 · 732 · 339 |
| USDJPY tsmom_ens H4 | 951 | +0.038 | 4.0% | 0.32 | 38% | 0.0% | 654 · 425 · 943 · 411 |

Walk-forward selection (components chosen on trades closed before each fold):

- fold 2: 12 components; final $1,394, Sharpe 1.08, max DD 24%, 139 trades
- fold 3: 12 components; final $768, Sharpe 0.52, max DD 34%, 280 trades
- fold 4: 12 components; final $619, Sharpe 0.32, max DD 38%, 273 trades

**Reading 4a and 4b together.**

- The portfolio earns money in almost every fold, with full-period Sharpe 0.84–0.89 vs buy-and-hold 0.48 (pre-registered).
- It cannot stay inside a 20% peak-to-trough drawdown at 1% risk per position with 3 slots, at any cap.
- Results depend heavily on the path. With the first-come 3-slot limit, overlapping windows give fractional drawdowns from 11% (2016–2026) to 64% (2013–2026). The difference is which BTC trades held the slots through 2017–19.
- The walk-forward selection check uses only components that had passed an edge rule on earlier trades. It keeps every component that has history before the fold, so it does not protect against the forex decay (fold 4, pre-registered: $920 final, DD 67%).

## 5. Regime eligibility table

Strategy family × regime on the decision bar. "Eligible" is fitted on folds 1–2; "Confirmed" checks whether the sign holds on folds 3–4 (needs ≥ 30 trades in both).

### 5a. Pre-registered (folds 1–2 = 1974–2000, forex only; folds 3–4 = 2000–2026)

| Family | Regime | Folds 1–2: n / Exp R | Folds 3–4: n / Exp R | Eligible (fit 1–2) | Confirmed 3–4 |
|---|---|---|---|---|---|
| donchian_ens D1 | TREND | 258 / +0.269 | 279 / +0.089 | yes | yes |
| donchian_ens D1 | RANGE | 535 / +0.735 | 628 / +0.124 | yes | yes |
| donchian_ens D1 | HIGH_VOL_SHOCK | 61 / +0.806 | 45 / -0.257 | yes | no |
| donchian_ens D1 | DEAD | 77 / +1.446 | 26 / -0.096 | yes | – |
| donchian_ens H4 | TREND | 152 / +0.243 | 1510 / +0.098 | yes | yes |
| donchian_ens H4 | RANGE | 339 / +0.551 | 2544 / +0.155 | yes | yes |
| donchian_ens H4 | HIGH_VOL_SHOCK | 45 / +0.823 | 256 / +0.281 | yes | yes |
| donchian_ens H4 | DEAD | 40 / +1.434 | 133 / +0.176 | yes | yes |
| tsmom_ens D1 | TREND | 404 / +0.127 | 562 / +0.501 | yes | yes |
| tsmom_ens D1 | RANGE | 993 / +0.486 | 1552 / +0.105 | yes | yes |
| tsmom_ens D1 | HIGH_VOL_SHOCK | 56 / +1.848 | 62 / -0.254 | yes | no |
| tsmom_ens D1 | DEAD | 234 / +0.944 | 179 / +2.328 | yes | yes |
| tsmom_ens H4 | TREND | 469 / +0.202 | 2536 / +0.289 | yes | yes |
| tsmom_ens H4 | RANGE | 445 / +0.683 | 2821 / +0.123 | yes | yes |
| tsmom_ens H4 | HIGH_VOL_SHOCK | 47 / +0.461 | 212 / +0.378 | yes | yes |
| tsmom_ens H4 | DEAD | 55 / +1.762 | 281 / +0.246 | yes | yes |


Out-of-sample check (folds 3–4): 'exp34_all': 0.206, 'n34_all': 13735, 'exp34_eligible': 0.206, 'n34_eligible': 13735, 'exp34_ineligible': None, 'n34_ineligible': 0, 'adopt_filter': False

### 5b. Modern sensitivity (folds 1–2 = 2016-11 to 2021-11; folds 3–4 = 2021-11 to 2026-11)

| Family | Regime | Folds 1–2: n / Exp R | Folds 3–4: n / Exp R | Eligible (fit 1–2) | Confirmed 3–4 |
|---|---|---|---|---|---|
| donchian_ens D1 | TREND | 61 / -0.004 | 89 / -0.184 | **no** | yes |
| donchian_ens D1 | RANGE | 142 / +0.040 | 150 / +0.206 | yes | yes |
| donchian_ens D1 | HIGH_VOL_SHOCK | 22 / -0.236 | 16 / -0.075 | yes | – |
| donchian_ens D1 | DEAD | 11 / +0.227 | 11 / -0.308 | yes | – |
| donchian_ens H4 | TREND | 439 / +0.349 | 590 / -0.037 | yes | no |
| donchian_ens H4 | RANGE | 724 / +0.297 | 942 / +0.164 | yes | yes |
| donchian_ens H4 | HIGH_VOL_SHOCK | 92 / +0.536 | 108 / +0.342 | yes | yes |
| donchian_ens H4 | DEAD | 41 / +0.505 | 50 / -0.302 | yes | no |
| tsmom_ens D1 | TREND | 114 / +0.334 | 155 / +0.057 | yes | yes |
| tsmom_ens D1 | RANGE | 320 / +0.155 | 322 / +0.079 | yes | yes |
| tsmom_ens D1 | HIGH_VOL_SHOCK | 24 / -0.398 | 18 / +0.032 | yes | – |
| tsmom_ens D1 | DEAD | 54 / +1.709 | 47 / +0.098 | yes | yes |
| tsmom_ens H4 | TREND | 612 / +0.855 | 570 / +0.116 | yes | yes |
| tsmom_ens H4 | RANGE | 569 / +0.218 | 681 / -0.053 | yes | no |
| tsmom_ens H4 | HIGH_VOL_SHOCK | 52 / +0.946 | 74 / +0.315 | yes | yes |
| tsmom_ens H4 | DEAD | 83 / -0.192 | 84 / +0.087 | **no** | no |


Out-of-sample check (folds 3–4): 'exp34_all': 0.068, 'n34_all': 3907, 'exp34_eligible': 0.073, 'n34_eligible': 3734, 'exp34_ineligible': -0.052, 'n34_ineligible': 173, 'adopt_filter': True

The mechanical rule fires here: the 173 ineligible trades lose −0.052R against +0.073R for eligible ones. It is not adopted because this period was picked after seeing 4a, the effect is +0.005R on the kept set, and one of the two ineligible cells (TSMOM H4 DEAD) is positive on folds 3–4.

**Router eligibility to use in Phase D: every regime eligible for every trend family.**

- No pre-registered cell qualifies as ineligible.
- The only modern cell that both fails and confirms (Donchian D1 entered in TREND, folds 1–2 −0.004R / n 61, folds 3–4 −0.184R / n 89) is contradicted by 2000–2026 (+0.089R, n 279).
- HIGH_VOL_SHOCK on D1 flips from strongly positive (1974–2000) to −0.25R (2000–2026, n 45–62). That is a watch item, not a rule.

**Intraday engine styles:** not in the table. `tools/gate_attribution.py` shadow trades were not re-run (optional in the brief; it needs an engine replay). The engine's ungated expectancy is −0.024R over 4,525 signals (earlier research), so no regime cell would be funded.

## 6. News (entry within ±30 min of a `data/news_history_usd.json` event, 2018+)

| Family | Folds | Entry within ±30 min: n / Exp R | Outside: n / Exp R |
|---|---|---|---|
| donchian_ens D1 | 1-2 | 0 / – | 205 / -0.009 |
| donchian_ens D1 | 3-4 | 0 / – | 266 / 0.037 |
| donchian_ens H4 | 1-2 | 15 / 0.646 | 1000 / 0.278 |
| donchian_ens H4 | 3-4 | 53 / 0.081 | 1637 / 0.092 |
| tsmom_ens D1 | 1-2 | 0 / – | 425 / 0.338 |
| tsmom_ens D1 | 3-4 | 0 / – | 542 / 0.073 |
| tsmom_ens H4 | 1-2 | 12 / 0.178 | 1062 / 0.495 |
| tsmom_ens H4 | 3-4 | 38 / 0.046 | 1371 / 0.043 |

D1 entries (broker midnight, about 21–22 UTC) never coincide with releases. H4 entries do so rarely, and the inside/outside difference flips between fold halves. **No trend-specific news rule.** The general ±30 min blackout costs these components almost nothing and can stay as risk policy.

## 7. Meta-label v2

| Fold | Train (after purge) | Test | AUC | Top-half Exp R | Bottom-half Exp R |
|---|---|---|---|---|---|
| 1 | 5131 | 1299 | 0.552 | +0.219 | +0.118 |
| 2 | 4429 | 1299 | 0.509 | +0.573 | +0.519 |
| 3 | 5016 | 1299 | 0.557 | +0.269 | +0.035 |
| 4 | 4890 | 1299 | 0.56 | +0.140 | +0.075 |
| 5 | 5265 | 1299 | 0.55 | +0.081 | -0.168 |

6626 trades (2018+), base rate (R > 0) 0.339, mean OOS AUC **0.546**, adopt: **False**.

**Rejected:** mean AUC 0.546 ≤ 0.55, and fold 2 is at 0.509. The top-half > bottom-half condition held in all 5 folds, but the pre-registered rule needs both. Do not wire a meta-label into the router. Re-test only with a new feature idea, never by re-tuning this one.

## 8. Rejected items and reasons

| Item | Reason |
|---|---|
| **Trend portfolio of the 12 edge-passing components, any cap 1–5%, 3 or 6 slots, both periods** | Max DD 30–85% ≥ 20% halt. Modern period: Sharpe also ≤ buy-and-hold. |
| Raising `min_lot_max_risk_pct_trend` to 5% | No cap passes the drawdown gate, and 5% is not safer than 2.5% in either period. |
| EURUSD Donchian D1, TSMOM D1/H4; USDJPY Donchian D1/H4, TSMOM D1/H4 (as live candidates) | Pass on 1971–2026, but real-era / 2016+ expectancy is about 0 or negative; standalone fold-4 accounts finish below $545 for 5 of 7. |
| BTCUSD TSMOM D1/H4 (as live candidates) | Edge passes, but drawdown alone is 27–58%. In 2023+ they are below always-long (earlier report). Min lot risks $14–23 (3–4% of $545). |
| US30, NAS100, US500, GER40, UK100: Donchian/TSMOM, H4 and D1 (20 rows) | Lose after costs and swap (19 of 20). NAS100 TSMOM H4 has PF 1.10 and is below always-long. Index CFD swap is about 6%/yr. US30/GER40 min lot does not fit $545 even at 5%. |
| XAGUSD (4 rows) | Donchian D1 is below always-long; the other three lose after costs. Min lot does not fit $545 even at 5% (0–22%). |
| GBPUSD, USDCAD, AUDUSD, NZDUSD (16 rows) | Lose after costs or PF ≤ 1.1; a half is negative. |
| USDCHF (4 rows) | Second half negative (D1 +0.33/+0.23R carried by the 1970s–90s); TSMOM H4 loses. |
| XAUUSD (4 rows) | Below always-long gold (unchanged from 2026-11-16). |
| SOLUSD (4 rows), ETHUSD TSMOM D1/H4, BTCUSD Donchian D1 | A half is negative, loses, or below always-long (unchanged). |
| Regime filter (any cell) | Pre-registered fit finds no ineligible cell. The modern fit is post hoc and only one cell confirms, contradicted by 2000–2026. |
| News-proximity rule for trend entries | Too few entries near events; no consistent effect. |
| Meta-label v2 | OOS AUC 0.546 ≤ 0.55. |
| Current-engine benchmark | Not re-run: the engine has no edge (−0.024R/trade ungated), so it cannot beat anything here. |

## 9. Limits and what this does not show

- **Costs.** XM reports `swap_mode` 0 (no swap) for the `#` forex symbols, gold and silver, so no swap is charged there. If the account is charged, forex carry changes the forex rows. Before 2018, spreads are the recent median, which understates 1970s–90s forex costs. Commissions and margin are not modelled.
- **Risk limits not modelled.**
  - The live `ADAPTIVE_GATE_8` caps projected portfolio risk at 8% / $60 for $500–1,000 equity. A 5% min-lot trade would therefore block a second concurrent one, which is stricter than the simulation.
  - Daily and weekly loss halts (5% / 10%) are not modelled either. Live would be more constrained, not less.
- **Selection bias.** Components are selected on the full sample, about 104 rows across this and the 2026-11-16 round. The walk-forward selection check keeps every component that has prior history.
- **Sizing design.** The vol target resizes only new entries. A vol overlay that also trims open positions is the obvious design to test next for the drawdown problem, but on $545 most positions are already at the broker minimum and cannot be trimmed. The structural fix is equity: at 1% risk, the median BTC/forex min-lot risk of $8–25 needs roughly $1,000–2,500.
- **Time stamps.** Exit times are the close of the exit bar, so marks can lag by up to one bar.

## 10. Reproduce

Scratchpad paths are session-local; use any directory.

```
python tools/strategy_research.py --selftest
python tools/portfolio_research.py --selftest
python tools/strategy_research.py --fetch-universe <dir>/universe.pkl
python tools/strategy_research.py <dir>/universe.pkl <dir>/universe_sr.json --trend
python tools/portfolio_research.py <dir>/universe.pkl <dir>/universe_sr.json <dir>/pf_main
python tools/portfolio_research.py <dir>/universe.pkl <dir>/universe_sr.json <dir>/pf_2016 --start 2016-11-08
```

Outputs: `portfolio_results.json` (every number above), `portfolio_equity.csv` (daily equity per sizing variant), `portfolio_trades.parquet` (each trade with its regime, news and meta features, for the Phase D equivalence tests).

## Demo router (built 2026-11-17)

`jarvis/forward_tests/trend_router.py` runs the 11 components that passed alone. ETHUSD Donchian H4
is left to the existing `FT_DCH_H4` forward test. It runs on **demo only**, with the research rules
unchanged: Donchian (20,10)/(55,20)/(100,20) with a 3×ATR trail, and TSMOM over 1/3/6 months with a
fixed 3×ATR stop. Each sub-system holds one position.

On every completed bar it decides each component and writes the decision to the journal (`kind=router`):

| Input | How the router uses it |
|---|---|
| Regime (TREND / RANGE / HIGH_VOL_SHOCK / DEAD) | Logged only; no regime filter passed out of sample |
| News | No new entry within ±30 min of a HIGH-impact release (the adopted N1 rule) |
| Capital | Circuit breaker and drawdown halt; at most 3 router positions and 2 per symbol; 1%/3 per sub-system; a min-lot entry is skipped above the 2.5% cap |
| Meta-label | Not used (out-of-sample AUC 0.546 < 0.55) |

- **Comments and strategy names:** order comments are `FT_TR_<SYMBOL>_<TF>_<D20|D55|D100|T1|T3|T6>`.
  Each component logs strategy `TREND_<DONCHIAN|TSMOM>_<SYMBOL>_<TF>`, so
  `/api/analytics/performance?by=strategy` reports it separately.
- **Promotion rule (unchanged):** ≥ 100 closed trades per component, a live mean ≥ +0.05R after costs,
  and portfolio drawdown inside the 20% halt.
- **Tests:** `tests/test_forward_test_trend_router.py` checks the signals against
  `strategy_research.donchian`/`tsmom` bar for bar, plus every decision path.
