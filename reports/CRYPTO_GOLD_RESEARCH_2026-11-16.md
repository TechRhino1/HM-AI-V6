# Crypto + gold strategy research: 2026-11-16

Tool: `tools/strategy_research.py` (generalises `tools/gold_research.py`). Data: real closed bars from the connected XM MT5 terminal (`BTCUSD#`, `ETHUSD#`, `SOLUSD#`, `GOLD.i#`; M5/H1/H4/D1 at the terminal's 100k-bar maximum). Every candidate uses fixed, textbook parameters; nothing was tuned.

## 1. Answer

**No candidate is adopted under the agreed criteria.** Every candidate fails at least one rule. The results split into three groups:

| Group | What happened |
|---|---|
| **M5 scalping (all symbols)** | Loses money after costs on BTC (−0.11R), ETH (−0.32R) and SOL (−0.73R). The spread is a large part of an M5 stop: SOL's $0.45 spread is about half its median M5 stop ($0.92); ETH's $3.45 is about a quarter of a $13 stop; BTC's $22.50 is about 8% of a $280 stop. Gold M5 scalping is the only small positive (+0.03 to +0.04R, beats both benchmarks) but its second half is negative and PF is ≈ 1.1, so it fails. This matches the earlier gold research, where the M5 scalp had no edge. |
| **RSI(2) trend pullback (H1/H4)** | Negative on every symbol and timeframe (−0.02R on gold up to −0.40R on ETH H1). It often wins more than half its trades (WR 32–58%) but loses money: the small wins don't cover spread plus the occasional 3×ATR stop. |
| **Trend following (Donchian ensemble, TSMOM ensemble, 10-day-high), D1/H4** | The only family with an edge after costs and swaps, in line with the literature. Seven symbol×timeframe rows **pass every edge rule** (profit after costs and swaps, PF > 1.1, both halves positive, survives a doubled spread, beats always-long and flipped, enough trades). **They fail only on affordability:** at a 3×ATR stop, 0.01 BTC risks $14–26 and 0.02 ETH risks $2–5, against a 2.5% budget of $2.50 on a $100 account. On gold, trend following makes money but **does not beat simply being long gold** (gold rose ~14× since 2001), and the minimum gold lot risks $24–55. |

The closest to tradeable, ranked by how strong the edge is in the **real-spread era (2023+ for crypto)**, where the broker's recorded spreads are real:

| Rank | Candidate | Full-sample Exp R / PF | 2023+ Exp R vs always-long / flipped | Min-lot risk (median) | Account where 80% of trades fit 2.5% |
|---|---|---|---|---|---|
| 1 | **ETHUSD Donchian ensemble, H4** | +0.220 / 1.47 (n 1,042) | **+0.115** vs +0.082 / −0.011 | $1.95 | **$157**: 100% of trades fit at $545 |
| 2 | **ETHUSD Donchian ensemble, D1** | +0.237 / 1.73 (n 175) | **+0.120** vs +0.076 / −0.141 | $5.42 | $380: 92% fit at $545 |
| 3 | **BTCUSD 10-day-high (long only), D1** | +0.087 / 1.66 (n 341) | **+0.079** vs −0.026 / −0.076 | $26.08 | $3,114 |
| 4 | ETHUSD 10-day-high, D1 | +0.070 / 1.64 (n 275) | +0.015 vs +0.011 / −0.034 (no real margin) | $5.03 | $387 |
| — | BTCUSD TSMOM D1 / Donchian H4 / TSMOM H4 | pass all edge rules on the full sample | **below always-long in 2023+** (0.23 vs 0.31; 0.18 vs 0.23; 0.21 vs 0.33): BTC's recent drift, not timing | $14–23 | $1,270–3,050 |

**Recommendation.** Do not wire any of these into live trading yet, and do not trade crypto from a $100 account. The best evidence is for **ETHUSD Donchian ensemble H4** (with D1 as its slower twin). It fits the user's current **$545** account (100% of trades within 2.5%) but not $100. It is the candidate to forward-test on the demo, unchanged, with a pre-registered rule: at least 100 trades, live expectancy ≥ +0.05R after costs and swaps. About 36 rows were tested, so a single +0.1R row needs out-of-sample confirmation (see §6).

## 2. Method

Same honesty rules as `gold_research.py`:

- Decisions only on **completed bars**; entry at the **next bar's open**; **BUY at the ask** (open + bar spread), SELL exits pay the spread.
- **Real per-bar spread** from MT5 (`spread × point`). XM's old history has zero spreads (gold before 2019, crypto before 2018) and implausible ones (BTC 2018–21 ≈ $600–1,260). Those bars get the **last-12-month median spread** instead: in bps of price for crypto, in dollars for gold (conservative for gold at old, low prices). They are flagged, and results are also reported for the **real-spread era** (from the first year after which ≥ 95% of every year's bars carry a real spread: crypto 2023+, gold 2019+).
- **Slippage** of half the recent median spread on every stop, time and signal exit (gold $0.10, the gold_research value; BTC $11.25, ETH $1.73, SOL $0.23).
- **Stop first** when stop and target are inside one bar; a gap through the stop fills at the open.
- **Swap** (below) charged for every broker rollover the position crosses.
- **One position at a time** per (sub-)system. Ensembles run three independent sub-systems (each 1/3 of capital) whose trades are pooled in time order.
- **Benchmarks at the same entries with the same exit rule:** always long, and flipped direction. For the long-only 10-day-high rule, "always long at the same entries" would equal the strategy, so its benchmark is a long on 5 seeded random days, held the same number of bars with the same ATR-scaled stop.
- **R** = net P&L ÷ initial stop distance; "$ at min lot" = the sum over all trades at the broker's minimum lot.

### Per-symbol costs (from `mt5.symbol_info`, 2026-11-16)

| Symbol | Price | Min lot (contract) | Recent median spread | Swap per night, long / short (per lot) | Swap at min lot, long | Swap as % of notional per night |
|---|---|---|---|---|---|---|
| BTCUSD# | 64,566 | 0.01 (1 BTC) | $22.50 | −$28.03 / −$18.69 | −$0.28 | 0.043% (≈ 16%/yr) |
| ETHUSD# | 1,808 | 0.02 (1 ETH) | $3.45 | −$0.80 / −$0.53 | −$0.016 | 0.044% (≈ 16%/yr) |
| SOLUSD# | 71.42 | 0.05 (10 SOL) | $0.45 | −$0.63 / −$0.63 | −$0.032 | 0.089% (≈ 32%/yr) |
| GOLD.i# | 3,873 | 0.01 (100 oz) | $0.20 | swap mode 0 = **disabled** (points −75.42 / +16.17 shown but not charged) | $0 | 0 |

**Swap conversion** (`swap_px` in the tool): XM reports crypto swaps in **points** (`swap_mode` 1), so one night costs `swap × point` in price units per contract unit, and `× tick_value/tick_size × lots` in dollars. Other modes are handled too: 2 = base currency, 3/4 = margin/deposit currency, 5/6 = annual interest ÷ 360. Crypto charges **every** night, weekends included (`swap_rollover3days` = 7, i.e. no triple day). Gold would charge Mon–Fri with a Wednesday triple. Today's swap is applied to the whole history **scaled by entry price ÷ today's price**, because a fixed $28/BTC/night would be 28% a night on 2013's $100 BTC. The real rate history is unknown. Swaps cost the crypto trend systems 0.06–0.13R per trade, which is included in every number.

**Gold swap caveat:** `GOLD.i#` reports swap mode 0 (disabled), so no swap is charged here. If the account were charged −75.42 points per night long, gold trend trades held for days would do worse (not measured). That doesn't change any gold verdict, because they are rejected anyway.

**Affordability:** min-lot $ risk at each trade's own stop = stop distance × tick value/tick size × minimum lot. It is compared with 2.5% of $100 ($2.50) and of $545 ($13.63). A candidate is affordable when ≥ 80% of its trades fit. The criterion uses $100 for crypto and $545 for gold. In an ensemble, all three sub-systems can be open at once, i.e. up to 3× that risk.

### Candidates (fixed parameters)

1. **Donchian ensemble (D1, H4):** close beyond the prior 20/55/100-bar high or low (three sub-systems). Exit on the opposite 10/20/20-bar channel or a 3×ATR(14) trailing stop; initial stop 3×ATR.
2. **TSMOM ensemble (D1, H4):** sign of the 1/3/6-month return (bars per month measured from the last year of data), re-evaluated each close. Exit and flip on a sign change; fixed 3×ATR stop.
3. **10-day-high, long only (D1), Quantpedia "MAX":** long while the close is the 10-day closing high; exit at the next open after it isn't; 3×ATR catastrophic stop.
4. **Trend-filtered RSI(2) (H1, H4):** close > EMA200 and RSI(2) < 10 → long (mirror: < EMA200, > 90 → short). Exit at RSI(2) > 70 (< 30) or after 5 bars; 3×ATR stop.
5. **Trend-filtered M5 scalp:** decisions 12:30–16:00 UTC; H1 EMA50 > EMA200 permission (mirror for shorts). Price pulls back to EMA20 or daily VWAP within 3 bars, then closes beyond the previous bar's high and above EMA20. Stop beyond the 3-bar swing + spread + 0.3 ATR, never inside 1 ATR. 1.0R or 1.5R target; 45-minute stagnation exit (< +0.1R).

### Adoption criteria (all required)

Profit after costs and swaps (Exp R > 0); PF > 1.1; both halves of the trade sequence positive; Exp R > 0 with the spread doubled; beats always-long and flipped; n ≥ 100 (n ≥ 40 on D1, flagged low-confidence below 100); affordable at $100 (crypto) / $545 (gold).

### Data span

| Symbol | M5 | H1 / H4 / D1 | Real spreads from |
|---|---|---|---|
| BTCUSD# | 2025-12-03 → 2026-11-16 (100k bars) | 2013-01 → 2026-11 | 2023 |
| ETHUSD# | 2025-12-03 → 2026-11-16 | 2016-11 → 2026-11 | 2023 |
| SOLUSD# | 2025-12-03 → 2026-11-16 | 2021-09 → 2026-11 | 2023 |
| GOLD.i# | 2025-06-18 → 2026-11-16 | 2001-06 → 2026-11 | 2019 |

## 3. Results: every symbol × candidate × timeframe

Exp R is per trade, net of spread, slippage and swap. "Real-spread era" columns are strategy / always-long / flipped Exp R on trades since the real-spread year.

| Symbol | Candidate | TF | n | WR | Exp R | PF | 1st half | 2nd half | Spread x2 | Always long | Flipped | Real-spread era n: strat / long / flip | Swap R/trade | $ at min lot | Min-lot risk (median) | Fit $100 | Fit $545 | Account for 80% fit | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTCUSD | donchian_ens | D1 | 223 | 44% | +0.637 | 2.75 | +1.215 | +0.065 | +0.634 | +0.657 | -0.317 | 88: 0.074 / 0.271 / 0.003 | -0.084 | +233 | $24.95 | 21% | 37% | $3,172 | rejected: not above always-long; min lot unaffordable at $100 (21% fit) |
| BTCUSD | tsmom_ens | D1 | 385 | 34% | +1.897 | 6.74 | +3.578 | +0.224 | +1.892 | +1.859 | -0.157 | 159: 0.231 / 0.311 / -0.035 | -0.131 | +2,403 | $22.65 | 20% | 36% | $3,052 | **edge passes**, rejected only on min lot: min lot unaffordable at $100 (20% fit) |
| BTCUSD | donchian_ens | H4 | 1036 | 41% | +0.338 | 1.85 | +0.546 | +0.130 | +0.329 | +0.267 | -0.141 | 465: 0.178 / 0.228 / -0.021 | -0.040 | +758 | $16.28 | 12% | 48% | $1,273 | **edge passes**, rejected only on min lot: min lot unaffordable at $100 (12% fit) |
| BTCUSD | tsmom_ens | H4 | 799 | 28% | +1.108 | 3.84 | +2.020 | +0.198 | +1.062 | +1.073 | -0.089 | 426: 0.205 / 0.334 / 0.02 | -0.127 | +2,209 | $14.29 | 11% | 49% | $1,280 | **edge passes**, rejected only on min lot: min lot unaffordable at $100 (11% fit) |
| BTCUSD | max10_long | D1 | 341 | 36% | +0.087 | 1.66 | +0.123 | +0.051 | +0.083 | -0.011 | -0.172 | 133: 0.079 / -0.026 / -0.076 | -0.010 | +449 | $26.08 | 18% | 35% | $3,114 | **edge passes**, rejected only on min lot: min lot unaffordable at $100 (18% fit) |
| BTCUSD | rsi2_trend | H1 | 3117 | 54% | -0.056 | 0.71 | -0.057 | -0.056 | -0.082 | -0.050 | -0.086 | 1468: -0.054 / -0.051 / -0.052 | -0.003 | -1,127 | $7.42 | 23% | 72% | $638 | rejected: loses after costs+swap; PF 0.71 <= 1.1; a half is negative; fails spread x2; not above always-long; min lot unaffordable at $100 (23% fit) |
| BTCUSD | rsi2_trend | H4 | 821 | 53% | -0.067 | 0.68 | -0.102 | -0.031 | -0.078 | -0.052 | -0.027 | 364: -0.012 / -0.048 / -0.05 | -0.006 | -225 | $15.36 | 10% | 47% | $1,330 | rejected: loses after costs+swap; PF 0.68 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped; min lot unaffordable at $100 (10% fit) |
| BTCUSD | m5_scalp_1.0R | M5 | 973 | 38% | -0.113 | 0.75 | -0.212 | -0.014 | -0.193 | -0.154 | -0.120 | 973: -0.113 / -0.154 / -0.12 | -0.000 | -183 | $2.80 | 42% | 100% | $197 | rejected: loses after costs+swap; PF 0.75 <= 1.1; a half is negative; fails spread x2; min lot unaffordable at $100 (42% fit) |
| BTCUSD | m5_scalp_1.5R | M5 | 880 | 31% | -0.122 | 0.76 | -0.213 | -0.032 | -0.200 | -0.153 | -0.093 | 880: -0.122 / -0.153 / -0.093 | -0.000 | -138 | $2.76 | 43% | 100% | $196 | rejected: loses after costs+swap; PF 0.76 <= 1.1; a half is negative; fails spread x2; not above flipped; min lot unaffordable at $100 (43% fit) |
| ETHUSD | donchian_ens | D1 | 175 | 49% | +0.237 | 1.73 | +0.428 | +0.048 | +0.231 | +0.145 | -0.270 | 79: 0.12 / 0.076 / -0.141 | -0.061 | +139 | $5.42 | 32% | 92% | $380 | **edge passes**, rejected only on min lot: min lot unaffordable at $100 (32% fit) |
| ETHUSD | tsmom_ens | D1 | 330 | 32% | +0.477 | 2.61 | +0.958 | -0.005 | +0.467 | +0.471 | -0.115 | 192: 0.003 / 0.061 / -0.025 | -0.071 | +188 | $4.70 | 26% | 93% | $368 | rejected: a half is negative; min lot unaffordable at $100 (26% fit) |
| ETHUSD | donchian_ens | H4 | 1042 | 38% | +0.220 | 1.47 | +0.358 | +0.081 | +0.198 | +0.141 | -0.197 | 465: 0.115 / 0.082 / -0.011 | -0.028 | +93 | $1.95 | 59% | 100% | $157 | **edge passes**, rejected only on min lot: min lot unaffordable at $100 (59% fit) |
| ETHUSD | tsmom_ens | H4 | 838 | 26% | +0.848 | 3.04 | +1.651 | +0.044 | +0.825 | +0.870 | -0.078 | 491: 0.046 / 0.099 / -0.033 | -0.077 | +206 | $1.93 | 60% | 100% | $147 | rejected: not above always-long; min lot unaffordable at $100 (60% fit) |
| ETHUSD | max10_long | D1 | 275 | 34% | +0.070 | 1.64 | +0.118 | +0.021 | +0.060 | +0.015 | -0.099 | 130: 0.015 / 0.011 / -0.034 | -0.007 | +30 | $5.03 | 30% | 95% | $387 | **edge passes**, rejected only on min lot: min lot unaffordable at $100 (30% fit) |
| ETHUSD | rsi2_trend | H1 | 3238 | 43% | -0.404 | 0.2 | -0.710 | -0.098 | -0.456 | -0.407 | -0.423 | 1444: -0.104 / -0.102 / -0.087 | -0.002 | -267 | $0.82 | 90% | 100% | $74 | rejected: loses after costs+swap; PF 0.2 <= 1.1; a half is negative; fails spread x2 |
| ETHUSD | rsi2_trend | H4 | 870 | 52% | -0.127 | 0.51 | -0.249 | -0.004 | -0.150 | -0.137 | -0.134 | 393: 0.004 / -0.072 / -0.089 | -0.004 | -57 | $1.89 | 62% | 100% | $161 | rejected: loses after costs+swap; PF 0.51 <= 1.1; a half is negative; fails spread x2; min lot unaffordable at $100 (62% fit) |
| ETHUSD | m5_scalp_1.0R | M5 | 916 | 25% | -0.324 | 0.43 | -0.338 | -0.310 | -0.580 | -0.355 | -0.342 | 916: -0.324 / -0.355 / -0.342 | +0.000 | -70 | $0.27 | 100% | 100% | $17 | rejected: loses after costs+swap; PF 0.43 <= 1.1; a half is negative; fails spread x2 |
| ETHUSD | m5_scalp_1.5R | M5 | 867 | 19% | -0.334 | 0.44 | -0.334 | -0.334 | -0.606 | -0.369 | -0.369 | 867: -0.334 / -0.369 / -0.369 | -0.000 | -63 | $0.26 | 100% | 100% | $16 | rejected: loses after costs+swap; PF 0.44 <= 1.1; a half is negative; fails spread x2 |
| SOLUSD | donchian_ens | D1 | 92 | 40% | +0.357 | 1.91 | +0.900 | -0.187 | +0.338 | +0.300 | -0.234 | 80: 0.363 / 0.469 / -0.252 | -0.109 | -90 | $10.68 | 17% | 64% | $664 | rejected: a half is negative; min lot unaffordable at $100 (17% fit) |
| SOLUSD | tsmom_ens | D1 | 180 | 29% | +0.252 | 1.72 | +0.722 | -0.218 | +0.219 | +0.228 | -0.213 | 155: 0.264 / 0.335 / -0.196 | -0.130 | -126 | $8.50 | 23% | 69% | $659 | rejected: a half is negative; min lot unaffordable at $100 (23% fit) |
| SOLUSD | donchian_ens | H4 | 635 | 32% | -0.026 | 0.94 | +0.047 | -0.099 | -0.106 | -0.087 | -0.196 | 488: -0.017 / -0.027 / -0.209 | -0.046 | -291 | $3.98 | 32% | 99% | $269 | rejected: loses after costs+swap; PF 0.94 <= 1.1; a half is negative; fails spread x2; min lot unaffordable at $100 (32% fit) |
| SOLUSD | tsmom_ens | H4 | 512 | 22% | +0.156 | 1.33 | +0.521 | -0.208 | +0.101 | +0.157 | -0.204 | 414: 0.174 / 0.229 / -0.222 | -0.128 | -165 | $3.14 | 45% | 99% | $247 | rejected: a half is negative; not above always-long; min lot unaffordable at $100 (45% fit) |
| SOLUSD | max10_long | D1 | 139 | 36% | +0.032 | 1.27 | +0.074 | -0.009 | +0.009 | -0.063 | -0.145 | 121: 0.046 / -0.065 / -0.161 | -0.011 | -18 | $8.62 | 19% | 70% | $635 | rejected: a half is negative; min lot unaffordable at $100 (19% fit) |
| SOLUSD | rsi2_trend | H1 | 1989 | 32% | -0.253 | 0.19 | -0.292 | -0.215 | -0.388 | -0.251 | -0.273 | 1494: -0.255 / -0.261 / -0.291 | -0.003 | -676 | $1.83 | 66% | 100% | $134 | rejected: loses after costs+swap; PF 0.19 <= 1.1; a half is negative; fails spread x2; not above always-long; min lot unaffordable at $100 (66% fit) |
| SOLUSD | rsi2_trend | H4 | 504 | 45% | -0.126 | 0.46 | -0.122 | -0.129 | -0.188 | -0.142 | -0.124 | 392: -0.14 / -0.135 / -0.11 | -0.007 | -165 | $3.82 | 35% | 98% | $280 | rejected: loses after costs+swap; PF 0.46 <= 1.1; a half is negative; fails spread x2; not above flipped; min lot unaffordable at $100 (35% fit) |
| SOLUSD | m5_scalp_1.0R | M5 | 875 | 9% | -0.728 | 0.11 | -0.769 | -0.686 | -1.224 | -0.742 | -0.723 | 875: -0.728 / -0.742 / -0.723 | +0.000 | -283 | $0.46 | 100% | 100% | $25 | rejected: loses after costs+swap; PF 0.11 <= 1.1; a half is negative; fails spread x2; not above flipped |
| SOLUSD | m5_scalp_1.5R | M5 | 858 | 7% | -0.730 | 0.12 | -0.765 | -0.694 | -1.234 | -0.754 | -0.741 | 858: -0.73 / -0.754 / -0.741 | -0.000 | -276 | $0.46 | 100% | 100% | $25 | rejected: loses after costs+swap; PF 0.12 <= 1.1; a half is negative; fails spread x2 |
| XAUUSD | donchian_ens | D1 | 390 | 40% | +0.155 | 1.44 | +0.107 | +0.203 | +0.152 | +0.315 | -0.125 | 119: 0.37 / 0.542 / -0.244 | +0.000 | +3,518 | $55.33 | 0% | 2% | $3,307 | rejected: not above always-long; min lot unaffordable at $545 (2% fit) |
| XAUUSD | tsmom_ens | D1 | 893 | 34% | +0.124 | 1.48 | +0.143 | +0.105 | +0.119 | +0.218 | -0.015 | 256: 0.204 / 0.322 / -0.012 | +0.000 | +5,883 | $51.82 | 0% | 2% | $3,126 | rejected: not above always-long; min lot unaffordable at $545 (2% fit) |
| XAUUSD | donchian_ens | H4 | 1225 | 39% | +0.108 | 1.29 | +0.131 | +0.085 | +0.095 | +0.166 | -0.090 | 729: 0.109 / 0.2 / -0.081 | +0.000 | +3,900 | $27.76 | 0% | 6% | $1,996 | rejected: not above always-long; min lot unaffordable at $545 (6% fit) |
| XAUUSD | tsmom_ens | H4 | 1335 | 28% | +0.217 | 1.64 | +0.186 | +0.248 | +0.209 | +0.270 | -0.012 | 686: 0.238 / 0.334 / -0.002 | +0.000 | +5,391 | $24.16 | 0% | 5% | $1,607 | rejected: not above always-long; min lot unaffordable at $545 (5% fit) |
| XAUUSD | max10_long | D1 | 686 | 37% | +0.015 | 1.15 | +0.011 | +0.020 | +0.010 | +0.019 | -0.033 | 219: 0.029 / 0.013 / -0.029 | +0.000 | -51 | $52.87 | 0% | 2% | $3,346 | rejected: not above always-long; min lot unaffordable at $545 (2% fit) |
| XAUUSD | rsi2_trend | H1 | 3684 | 58% | -0.018 | 0.9 | -0.034 | -0.002 | -0.033 | -0.021 | -0.043 | 2116: -0.009 / -0.004 / -0.026 | +0.000 | -326 | $12.41 | 0% | 57% | $856 | rejected: loses after costs+swap; PF 0.9 <= 1.1; a half is negative; fails spread x2; min lot unaffordable at $545 (57% fit) |
| XAUUSD | rsi2_trend | H4 | 1019 | 58% | -0.022 | 0.88 | -0.017 | -0.026 | -0.029 | -0.022 | -0.007 | 520: -0.023 / -0.022 / 0.008 | +0.000 | -1,263 | $26.02 | 0% | 7% | $1,819 | rejected: loses after costs+swap; PF 0.88 <= 1.1; a half is negative; fails spread x2; not above always-long; not above flipped; min lot unaffordable at $545 (7% fit) |
| XAUUSD | m5_scalp_1.0R | M5 | 977 | 47% | +0.030 | 1.08 | +0.066 | -0.007 | +0.022 | -0.058 | -0.069 | 977: 0.03 / -0.058 / -0.069 | +0.000 | +270 | $11.58 | 0% | 63% | $719 | rejected: PF 1.08 <= 1.1; a half is negative; min lot unaffordable at $545 (63% fit) |
| XAUUSD | m5_scalp_1.5R | M5 | 864 | 39% | +0.044 | 1.11 | +0.111 | -0.024 | +0.028 | -0.031 | -0.044 | 864: 0.044 / -0.031 / -0.044 | +0.000 | +267 | $11.61 | 0% | 64% | $716 | rejected: a half is negative; min lot unaffordable at $545 (64% fit) |

## 4. Adopted vs rejected

**Adopted: none.**

**Edge passes, rejected only on minimum-lot affordability at $100 (7 rows):**

| Row | Why it still isn't recommended as-is |
|---|---|
| ETHUSD Donchian H4 | Best candidate. In 2023+ it beats always-long (+0.115 vs +0.082). Fits $545 (100%) but only 59% of trades fit $100. **Forward-test at $545.** |
| ETHUSD Donchian D1 | Same edge, slower; n = 175 (79 in 2023+). Fits $545 (92%). |
| BTCUSD 10-day-high D1 | Beats random-day longs in 2023+ (+0.079 vs −0.026), but 0.01 BTC risks ~$26: it needs a ~$3,100 account. |
| ETHUSD 10-day-high D1 | Passes, but the 2023+ margin over random longs is 0.004R: no practical edge. |
| BTCUSD TSMOM D1, Donchian H4, TSMOM H4 | Pass on the full sample (2013+), which is dominated by BTC's early bull run (first-half Exp R +0.5 to +3.6R). **In 2023+ all three are below always-long:** the "edge" is BTC's drift. |

**Rejected for other reasons:**

| Rows | Main reasons |
|---|---|
| All M5 scalps on BTC/ETH/SOL | Lose after costs; fail spread ×2; ETH/SOL lose more than 0.3R per trade |
| Gold M5 scalp 1.0R / 1.5R | Second half negative; PF 1.08 / 1.11; only 63% of trades fit $545 |
| All RSI(2) pullbacks (8 rows) | Lose after costs on every symbol and timeframe |
| Gold Donchian / TSMOM / 10-day-high (5 rows) | Profitable (PF 1.15–1.64) but **below always-long gold**; min lot risks $24–55, so 2–6% of trades fit $545 |
| ETHUSD TSMOM D1 / H4 | D1 second half ≈ 0 (−0.005); H4 below always-long |
| SOLUSD Donchian D1, TSMOM D1/H4, 10-day-high | Second half negative (SOL's history is short: 2021+); Donchian H4 loses after costs |
| BTCUSD Donchian D1 | Below always-long |

## 5. Plan for $100 and for $545 (standard account)

- **$100:** no strategy tested here is both profitable and affordable. The only setups that fit 2.5% of $100 at minimum lot are M5 scalps on ETH/SOL, and those lose 0.3–0.7R per trade to the spread. **Recommendation: don't trade crypto or gold live from $100.** Keep it on demo until the account can carry a 3×ATR stop at minimum lot. A tighter stop was deliberately not tried, because changing the stop to make it fit would be tuning on this data.
- **$545:** ETHUSD Donchian ensemble H4 fits (median min-lot risk $1.95 = 0.36% per sub-system, ≤ ~1.1% with all three open). Forward-test it on the demo exactly as specified here (no parameter changes) before any live use. BTC trend systems need $1,300–3,100. Gold trend systems need $1,600–3,350 and still don't beat buy-and-hold gold.

Context: ESMA's mandatory CFD warnings show 74–89% of retail CFD accounts lose money. The live demo's −0.11R over 285 trades and the 12-month ICT/SMC finding (no directional edge) are consistent with that base rate. The edge found here is small (+0.1R per trade) and comes from trend following on higher timeframes. That matches the literature below, not the M5 scalping the bot does now.

## 6. Caveats

- **Multiple testing:** 36 symbol×candidate×timeframe rows (each with benchmarks and a spread×2 run). At that count, one or two +0.1R rows can appear by chance. The candidates and parameters were fixed before running, but the forward test is still required.
- **Spread history:** before 2023 (crypto) or 2019 (gold), spreads are modeled from the last 12 months; the real-spread-era columns show the recent picture. On D1/H4 the spread is a small share of a 3×ATR stop, so this mostly affects the M5 and H1 rows, and those all use real spreads.
- **Swap history:** today's rates are scaled by price over the whole sample; real past rates differed.
- **Bar spreads** are what MT5 stores per bar, not tick-level. Stop-first intrabar ordering is conservative for targets but can't model stop-hunting wicks inside a bar.
- **Ensemble sizing** is approximated by pooling sub-system trades at equal R; real 1/3-size positions are impossible at minimum lot, so live, each sub-system trades min lot.
- `jarvis/backtesting/engine.py` was not used or changed (another session is fixing its M5 clock). No live trading code was changed.

## 7. Sources

- Moskowitz, Ooi & Pedersen (2012), *Time Series Momentum*, JFE: papers.ssrn.com/abstract=2089463. Sign-of-past-return trend rule (candidate 2).
- Levine & Pedersen, *Which Trend Is Your Friend?*: TSMOM and moving-average/breakout rules are close relatives; costs matter.
- Zarattini, Pagani & Barbon, *Catching Crypto Trends*: ensemble of Donchian channels on crypto (abarbon.com/papers/catching-crypto-trends) (candidate 1).
- Han, Kang & Ryu, crypto time-series momentum and transaction costs: crypto momentum profits shrink sharply after costs at short horizons.
- Quantpedia (2024), *Revisiting Trend-following and Mean-reversion Strategies in Bitcoin*: the 10-day-maximum (MAX) rule (candidate 3).
- ESMA, product-intervention CFD risk warnings: 74–89% of retail CFD accounts lose money.
- freqtrade hyperopt documentation: its warning that optimised parameters overfit; the reason no parameter was tuned here.

## 8. Reproduce

```bash
python tools/strategy_research.py --selftest
python tools/strategy_research.py --fetch bars.pkl
python tools/strategy_research.py bars.pkl results.json
```
