# SMC/ICT entry, multi-timeframe bias and regime-switched exits: research (2026-11-17)

**Request:** prove that the pasted SMC/ICT specification improves profit *before* any live code changes.
It covers a liquidity sweep → displacement → FVG → CHoCH entry, HTF pivot-structure bias, premium/discount, sessions, partials and regime-switched trailing.
(`reports/SMC_AUDIT.md` audits where the live detectors sit in `jarvis/`; this report tests whether the rules make money.)

## Short answer

**No component passed the adoption gate, so nothing goes into live code.**

- **The full SMC confluence is too rare to test.** All six filters together leave **44 trades across 6 symbols, 3 styles and all available history**: 1–11 per class × style cell. Where there are trades, the results are noise, and mostly losses.
- **The base setup has no edge after costs.** The base setup is displacement + FVG + CHoCH, with no filters. Mean expectancy across the 9 cells is **−0.036R**. The best cells are gold DAY (+0.11R, PF 1.16) and forex DAY (+0.06R, PF 1.08). Neither clears PF 1.5 or both halves.
- **The HTF structure bias (the "improved MTF bias") never helped forex or crypto.** It made 5 of those 6 cells worse and tied the sixth (crypto SCALP). It helped only gold, and there it does not beat simply being long through gold's bull run.
- **Premium/discount** helped in 4 of 9 cells and hurt in 5. This matches the earlier zone-veto finding (`reports/MTF_ENTRY_RESEARCH_2026-11-17.md`).
- **E2, the FVG-midpoint retrace limit, was worse than entering at the next open** in 6 of 9 cells.
- **Regime-switched exits (X4)** beat the always-on trails they switch between in 5 of 9 cells. They never produced positive expectancy where the base entry loses.
- **Partials (X1) raise the win rate** from 28% to 48% on average across cells, but lower expectancy from −0.036R to −0.057R. That is the same trap as before: win rate is not profit.

**Two near-misses** passed every edge test (both halves positive, all 4 folds positive, spread × 2, beats flipped and always-long). They fail on PF ≤ 1.5 and on min-lot affordability:

| Candidate | n | Exp R | PF | Folds 1–4 | Spread ×2 | Why rejected |
|---|---|---|---|---|---|---|
| crypto SWING (H1), base setup + **X3 chandelier 3 ATR from +1R** | 564 | +0.104 | 1.22 | +0.07 / +0.17 / +0.11 / +0.06 | +0.073 | PF 1.22 ≤ 1.5; min lot fits 27% of trades at $100 (65% at $545) |
| forex DAY (M15), base setup + **session filter only** (07–10, 12–15 UTC) | 281 | +0.195 | 1.29 | +0.23 / +0.46 / +0.12 / +0.03 | +0.170 | PF 1.29 ≤ 1.5; min lot fits 35% at $100 (99% at $545) |

The chandelier exit is the only exit that was **chosen on folds 1–2 and confirmed on folds 3–4** with at least 100 trades: +0.086R against X0's −0.036R on folds 3–4. Both near-misses come out of roughly 150 configurations tested, so treat them as hypotheses for a forward test, not as findings.

## Method: `tools/smc_research.py`

It reuses the cost-honest machinery unchanged:

- `strategy_research`: `arrays`, `pool`, `verdict`, swap, and the fetch;
- `range_research`: `pivots`, `adx` and `prepare` (through `mtf_entry_research.frames`);
- `gold_research`: `attach` and `stats`.

The honesty rules:

- decisions only at completed-bar closes;
- entry at the next open at the real per-bar spread (BUY at the ask);
- slippage of half the median spread on stop exits;
- broker swap;
- **the stop is assumed hit first** whenever it shares a bar with a partial or target;
- if a bar reaches +1R and also the new break-even stop, the remainder is assumed stopped;
- every result is compared with flipped trades, always-long trades and spread × 2, at the same entries and with the same exit.

One position at a time per symbol × style. All parameters were fixed in advance and are listed in the module docstring.

| Item | Rule |
|---|---|
| Styles | SCALP: M5 entry, bias H1+H4. DAY: M15 entry, bias H1+H4. SWING: H1 entry, bias H4+D1. The first bias TF also gives the regime and the premium/discount range. |
| Structure | Fractal pivots K=3, usable from p+3. BOS state flips on a close beyond the last confirmed pivot; a flip from the opposite state is a CHoCH. The swing label is HH+HL or LH+LL. A TF's read is its BOS state unless the swing label opposes it. Bias is the two reads when they agree. |
| Regime | Per completed bias-TF bar: `HIGH_VOL_SHOCK` if ATR5/ATR50 > 1.8; else `TREND` if ADX14 ≥ 25; else `DEAD` if the BB(20,2) width percentile over 500 bars < 0.2 and ATR5/ATR50 < 0.8; else `RANGE`. VR is the Lo-MacKinlay ratio, q = 4 over 100 bars. |
| Setup | Displacement bar: body > 70% of its range, range > 1.5 × ATR14, closing as a CHoCH in its direction, and leaving an FVG (next bar's low > the high two bars back). Decision at the close of the FVG bar. |
| Sweep | Within the 10 bars before the displacement, a wick through PDH/PDL, the Asian high/low (00–07 UTC, usable from 07:00), the London high/low (07–12 UTC, usable from 12:00), or EQH/EQL (two of the last 5 pivots within 0.1 ATR), closing back inside. |
| E1 / E2 | E1 enters at the next open. E2 places a limit at the FVG midpoint for 12 bars. It fills only if a bar trades a spread through the level, and only the stop is checked on the fill bar. |
| Stop | Beyond the extreme from the sweep bar to the decision bar, plus 0.5 ATR (forex) or 1.0 ATR (gold, crypto). |
| Exits | X0: 2.5R. X1: 50% at 1R, then stop to entry + spread, rest at 2.5R. X2: X1 plus a trail beyond the last confirmed entry-TF pivot. X3: chandelier 3 ATR from +1R, no target. X4a/X4b: X2/X3 when the entry regime is TREND and VR > 1, otherwise X0. |
| Validation | 4 equal calendar folds per class × style. The exit is picked on folds 1–2 by expectancy, per class × style (never per symbol or per cell), then checked on folds 3–4. |
| Gate | Higher pooled expectancy **and** lower max drawdown than the layer below; passes `sr.verdict`; PF > 1.5; positive in at least 3 of 4 folds. Win rate is reported only. |

**Spec choices.** These are the places where the specification was ambiguous or had to be extended:

- **SCALP bias frames.** The bias section says H1+H4 for SCALP and the style list says H1/M15, so H1+H4 was used.
- **X4.** "X2/X3" was split into X4a and X4b, both fixed in advance.
- **Additive filter view.** The full filter stack is too rare for ALL-vs-ALL-minus-one to say anything (n ≤ 11), so each filter alone on top of the base setup (`+f`) was added. Both views are gated.
- **E2 benchmarks.** They reuse the strategy's fill bar and price.

**Selftest** (`python tools/smc_research.py --selftest`, passes) checks:

- the CHoCH flip on a falling zigzag;
- displacement + FVG + sweep, and the stop arithmetic, with a mirrored SELL;
- no setup without the gap;
- session-level timing;
- the E2 fill rule and its 12-bar expiry;
- partial-exit arithmetic: BUY and SELL, stop-first, break-even after 1R, target, chandelier;
- the E2 fill bar;
- **no look-ahead:** after perturbing every M5 bar after time T (and rebuilding H1/H4), all 109 setups decided before T are identical, while the total set changes (165 vs 112).

### Data

Real XM MT5 bars were frozen on 2026-11-17 (`strategy_research.fetch`, terminal max 50,000 bars):

| Entry TF | Span |
|---|---|
| M5 | Mar 2026 (forex, gold) or May 2026 (crypto) to Nov 2026 |
| M15 | Oct–Nov 2024 (forex, gold) or Jun 2025 (crypto) to Nov 2026 |
| H1 | 2018 (forex, gold) or 2020 (crypto) to Nov 2026 |

SCALP folds are therefore about 6 weeks each. Groups:

- forex = EURUSD, GBPUSD, USDJPY;
- gold = XAUUSD;
- crypto = BTCUSD, ETHUSD.

## Results: per group (E1, X0 2.5R, R per trade after all costs)

| Class | Style | Filters | n | WR | Exp R | PF | Max DD R | Folds 1–4 | Spread ×2 | Flipped / always-long | Fails `sr.verdict` on |
|---|---|---|---|---|---|---|---|---|---|---|---|
| forex | SCALP | none | 527 | 27% | −0.095 | 0.88 | 56.3 | −0.03 / −0.28 / +0.01 / −0.09 | −0.200 | −0.154 / −0.181 | loses; PF; a half; spread ×2 |
| forex | SCALP | all | 1 | 0% | −1.040 | 0 | 0 | – | – | – | n |
| forex | DAY | none | 520 | 31% | +0.057 | 1.08 | 34.1 | +0.13 / +0.28 / +0.01 / −0.12 | +0.009 | −0.137 / −0.072 | PF; a half; min lot |
| forex | DAY | all | 4 | 0% | −1.011 | 0 | 3.0 | – | – | – | n |
| forex | SWING | none | 623 | 28% | −0.026 | 0.96 | 36.4 | −0.06 / +0.02 / −0.08 / +0.01 | −0.037 | +0.024 / +0.119 | loses; below benchmarks; min lot |
| forex | SWING | all | 3 | 33% | +0.164 | 1.24 | 1.0 | – | – | – | n |
| gold | SCALP | none | 152 | 31% | +0.077 | 1.11 | 12.6 | +0.41 / −0.15 / +0.14 / −0.18 | +0.054 | +0.114 / −0.039 | below flipped; min lot |
| gold | SCALP | all | 5 | 60% | +0.789 | 2.11 | 1.0 | – | – | – | n |
| gold | DAY | none | 170 | 32% | +0.108 | 1.16 | 18.8 | −0.33 / +0.38 / +0.54 / −0.16 | +0.088 | +0.088 / +0.191 | a half; below always-long; min lot |
| gold | DAY | all | 1 | 0% | −1.004 | 0 | 0 | – | – | – | n |
| gold | SWING | none | 186 | 26% | −0.101 | 0.86 | 29.1 | −0.05 / −0.11 / −0.30 / +0.06 | −0.120 | −0.039 / +0.106 | loses |
| gold | SWING | all | 1 | 0% | −1.008 | 0 | 0 | – | – | – | n |
| crypto | SCALP | none | 329 | 26% | −0.142 | 0.82 | 62.9 | +0.05 / −0.26 / −0.15 / −0.17 | −0.238 | −0.001 / −0.028 | loses |
| crypto | SCALP | all | 10 | 40% | +0.348 | 1.55 | 3.2 | +0.66 / +2.49 / −0.18 / −1.06 | +0.352 | −0.030 / +0.671 | n; a half; below always-long |
| crypto | DAY | none | 334 | 25% | −0.168 | 0.79 | 70.3 | +0.03 / −0.01 / −0.37 / −0.33 | −0.220 | −0.160 / −0.236 | loses |
| crypto | DAY | all | 8 | 12% | −0.609 | 0.34 | 5.3 | – | – | – | n; loses |
| crypto | SWING | none | 359 | 30% | −0.034 | 0.95 | 28.8 | −0.14 / +0.07 / −0.00 / −0.07 | −0.053 | −0.113 / −0.004 | loses |
| crypto | SWING | all | 11 | 18% | −0.434 | 0.50 | 6.4 | – | – | – | n; loses |

## Filter ablation (E1, X0): Exp R (n)

`+f` is the base setup plus that filter alone. `−f` is all filters except that one.

| Class | Style | none | +htf | +sweep | +vol | +session | +spread | +zone | **all** | −htf | −sweep | −vol | −session | −spread | −zone |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| forex | SCALP | −0.10 (527) | −0.14 (187) | −0.20 (245) | −0.09 (405) | −0.11 (231) | −0.10 (513) | −0.06 (359) | −1.04 (1) | +0.15 (29) | −1.04 (2) | +0.73 (4) | −1.04 (5) | −1.04 (1) | −0.19 (12) |
| forex | DAY | +0.06 (520) | −0.16 (209) | +0.11 (309) | +0.12 (430) | **+0.20 (281)** | +0.06 (520) | −0.23 (255) | −1.01 (4) | −0.02 (39) | −1.02 (8) | −0.43 (6) | −1.01 (7) | −1.01 (4) | −0.17 (41) |
| forex | SWING | −0.03 (623) | −0.13 (179) | −0.05 (516) | −0.00 (522) | −0.03 (358) | −0.03 (623) | +0.04 (273) | +0.16 (3) | −0.19 (60) | −0.13 (4) | +0.75 (4) | −0.51 (7) | +0.16 (3) | −0.19 (43) |
| gold | SCALP | +0.08 (152) | +0.17 (67) | +0.10 (86) | +0.16 (105) | −0.25 (67) | +0.08 (152) | −0.22 (107) | +0.79 (5) | +0.53 (15) | +0.49 (6) | +0.79 (5) | +0.49 (6) | +0.79 (5) | +0.38 (9) |
| gold | DAY | +0.11 (170) | +0.34 (70) | +0.11 (113) | +0.05 (166) | +0.10 (120) | +0.11 (170) | +0.16 (84) | −1.00 (1) | +0.23 (17) | −1.00 (2) | −1.00 (1) | −1.01 (3) | −1.00 (1) | −0.07 (15) |
| gold | SWING | −0.10 (186) | −0.05 (62) | −0.10 (154) | −0.02 (156) | −0.30 (105) | −0.10 (186) | −0.29 (93) | −1.01 (1) | −0.48 (20) | −1.01 (2) | −1.01 (3) | +0.16 (3) | −1.01 (1) | −0.13 (8) |
| crypto | SCALP | −0.14 (329) | −0.14 (154) | −0.08 (155) | −0.07 (288) | −0.13 (308) | −0.11 (300) | −0.19 (222) | +0.35 (10) | −0.29 (59) | −0.37 (25) | +0.30 (13) | +0.08 (12) | +0.21 (11) | −0.18 (28) |
| crypto | DAY | −0.17 (334) | −0.27 (134) | −0.24 (226) | −0.17 (298) | −0.12 (317) | −0.17 (331) | −0.19 (188) | −0.61 (8) | −0.22 (72) | −0.54 (14) | −0.70 (10) | −0.61 (8) | −0.61 (8) | −0.18 (44) |
| crypto | SWING | −0.03 (359) | −0.17 (138) | +0.01 (300) | +0.12 (289) | −0.05 (354) | −0.03 (359) | +0.09 (189) | −0.43 (11) | +0.12 (97) | −0.07 (14) | +0.03 (16) | −0.43 (11) | −0.43 (11) | −0.23 (75) |

How often each filter alone raised expectancy over the base setup, out of 9 cells (in brackets, the cells where it also lowered max drawdown):

| Filter | Cells improved | Comment |
|---|---|---|
| htf (two-TF structure bias) | **3** (3), gold only | Lowers expectancy in 5 of 6 forex and crypto cells (crypto SCALP ties). Gold DAY +0.34R (n 70) is below always-long (+0.45R): it is bull-run beta. |
| sweep | 6 (5) | Small, mixed gains; it hurts forex SCALP (−0.20 vs −0.10) and crypto DAY. |
| vol (displacement tick volume ≥ 1.2 × SMA20) | **8** (7) | The most consistent filter. Gains are +0.01 to +0.15R (largest in crypto SWING), but no cell clears PF 1.5. |
| session | 3 (3) | Strong for forex DAY; strongly harmful for gold (SCALP −0.25, SWING −0.30). |
| spread | 1 (1) | Rarely binds (0–124 rejections per cell). |
| zone (premium/discount) | 4 (4) | Hurts in 5 of 9 cells. Same verdict as the earlier zone-veto test. |

## Exits: Exp R (n), PF and positive folds; the exit is chosen on folds 1–2 and checked on folds 3–4

Base setup (no filters, E1). This is the sample large enough to say anything:

| Class | Style | X0 2.5R | X1 partial | X2 partial + pivot trail | X3 chandelier | X4a regime → X2 | X4b regime → X3 | Chosen on folds 1–2 | Folds 3–4: chosen vs X0 |
|---|---|---|---|---|---|---|---|---|---|
| forex | SCALP | −0.10 (527) PF 0.88 1/4 | −0.12 (646) PF 0.78 0/4 | −0.11 (769) PF 0.80 0/4 | −0.11 (771) PF 0.81 0/4 | −0.08 (565) PF 0.89 1/4 | −0.07 (569) PF 0.90 2/4 | X1 | −0.141 vs −0.049 ✗ |
| forex | DAY | +0.06 (520) PF 1.08 3/4 | −0.02 (670) PF 0.97 2/4 | −0.00 (819) PF 1.00 3/4 | +0.03 (815) PF 1.05 3/4 | +0.10 (548) PF 1.15 3/4 | +0.11 (548) PF 1.16 3/4 | X4a | −0.028 vs −0.061 ✗ (negative) |
| forex | SWING | −0.03 (623) PF 0.96 2/4 | −0.04 (743) | −0.04 (921) | −0.05 (907) | −0.01 (651) | −0.00 (650) | X0 | −0.031 ✗ |
| gold | SCALP | +0.08 (152) PF 1.11 2/4 | −0.08 (200) | −0.11 (249) | −0.07 (246) | +0.02 (161) | +0.04 (161) | X0 | −0.005 ✗ |
| gold | DAY | +0.11 (170) PF 1.16 2/4 | +0.11 (211) PF 1.24 2/4 | +0.09 (280) | +0.11 (277) PF 1.24 2/4 | +0.07 (178) | +0.09 (178) | X1 | +0.137 vs +0.248 ✗ |
| gold | SWING | −0.10 (186) PF 0.86 1/4 | −0.10 (219) | −0.06 (271) | −0.06 (271) | −0.11 (211) | −0.10 (211) | X0 | −0.128 ✗ |
| crypto | SCALP | −0.14 (329) PF 0.82 1/4 | −0.13 (421) | −0.18 (508) | −0.17 (505) | −0.09 (350) | −0.07 (350) | X4a | −0.100 vs −0.161 ✗ (negative) |
| crypto | DAY | −0.17 (334) PF 0.79 1/4 | −0.13 (404) | −0.13 (489) | −0.08 (497) PF 0.86 2/4 | −0.18 (360) | −0.16 (360) | X3 | −0.189 vs −0.352 ✗ (negative) |
| crypto | SWING | −0.03 (359) PF 0.95 1/4 | −0.00 (451) PF 0.99 2/4 | +0.04 (568) PF 1.09 4/4 | **+0.10 (564) PF 1.22 4/4** | −0.00 (403) | +0.01 (402) | **X3** | **+0.086 vs −0.036 ✓** |

What the exit table shows:

- **Exits with all filters:** n is 1–11 per cell, so the fold choice is noise. Crypto SCALP shows +0.35R (n 10), and E2 there shows +0.88R (n 9), but each rests on 9–10 trades.
- **Kaminski & Lo check.** On setups taken in `TREND` with VR > 1 (1,267 setups, independent outcomes), the chandelier loses less than the fixed target: −0.050R vs −0.090R. Trailing does help under momentum, but it does not turn a losing entry into a winner.
- **The regime switch adds something, inconsistently.** X4 beats its always-on trail in 5 of 9 cells, and beats X0 in 5 (X4a) and 7 (X4b) cells. It is never confirmed out-of-sample with positive expectancy.
- **Trailing does not beat a fixed target in general.** That matches `reports/RANGE_AND_TRAILING_RESEARCH_2026-11-17.md`. The exception is crypto H1, where the chandelier was chosen in-sample and held up out-of-sample.

E2 (limit at the FVG midpoint) vs E1, base setup with X0:

| Class | Style | E1 next open | E2 FVG-midpoint limit |
|---|---|---|---|
| forex | SCALP | −0.10 (527) | −0.17 (510) |
| forex | DAY | +0.06 (520) | +0.02 (516) |
| forex | SWING | −0.03 (623) | −0.13 (562) |
| gold | SCALP | +0.08 (152) | −0.17 (182) |
| gold | DAY | +0.11 (170) | +0.20 (179), below always-long +0.27 |
| gold | SWING | −0.10 (186) | −0.10 (177) |
| crypto | SCALP | −0.14 (329) | −0.36 (329) |
| crypto | DAY | −0.17 (334) | −0.23 (316) |
| crypto | SWING | −0.03 (359) | +0.02 (326) |

The retrace fills preferentially on the trades that keep going against you, which is adverse selection. The tighter stop does not make up for it.

## Rejections: setups failing each filter, counted independently

| Class | Style | Setups | REJECTED_HTF | REJECTED_SWEEP | REJECTED_VOL | REJECTED_SESSION | REJECTED_SPREAD | REJECTED_ZONE | Pass all | REJECTED_E2_UNFILLED (of all-filter trades) |
|---|---|---|---|---|---|---|---|---|---|---|
| forex | SCALP | 1,118 | 875 | 769 | 406 | 791 | 34 | 677 | 1 | 0 |
| forex | DAY | 1,089 | 818 | 571 | 284 | 676 | 1 | 809 | 4 | 1 |
| forex | SWING | 1,247 | 1,027 | 338 | 231 | 764 | 0 | 923 | 3 | 0 |
| gold | SCALP | 343 | 255 | 210 | 133 | 243 | 0 | 201 | 5 | 1 |
| gold | DAY | 378 | 286 | 208 | 91 | 217 | 0 | 271 | 1 | 0 |
| gold | SWING | 390 | 313 | 101 | 84 | 257 | 0 | 276 | 1 | 0 |
| crypto | SCALP | 844 | 642 | 600 | 195 | 112 | 124 | 522 | 11 | 1 |
| crypto | DAY | 784 | 619 | 421 | 168 | 96 | 15 | 561 | 8 | 3 |
| crypto | SWING | 876 | 705 | 235 | 275 | 69 | 0 | 625 | 11 | 4 |

The HTF filter rejects 74–82% of setups:

- the two bias frames agree only 42–47% of the time;
- a CHoCH setup matches that side about half the time.

This was checked on EURUSD and is not a bug. The zone filter rejects 60–75%, because a bullish CHoCH displacement usually lifts price out of discount.

## Every setup by entry regime (E1, independent outcomes, ignoring position overlap)

| Class | Regime | n | X0 | X1 | X2 | X3 | WR X0 |
|---|---|---|---|---|---|---|---|
| crypto | DEAD | 277 | −0.066 | −0.117 | −0.126 | −0.151 | 29% |
| crypto | HIGH_VOL_SHOCK | 87 | −0.063 | −0.162 | −0.107 | −0.084 | 29% |
| crypto | RANGE | 1,037 | −0.071 | −0.069 | −0.053 | +0.012 | 28% |
| crypto | TREND | 1,103 | −0.100 | −0.144 | −0.147 | −0.114 | 27% |
| forex | DEAD | 289 | −0.042 | −0.065 | −0.038 | +0.032 | 28% |
| forex | HIGH_VOL_SHOCK | 68 | +0.125 | −0.052 | −0.018 | −0.011 | 32% |
| forex | RANGE | 1,681 | −0.013 | −0.067 | −0.063 | −0.068 | 29% |
| forex | TREND | 1,416 | −0.061 | −0.061 | −0.067 | −0.053 | 27% |
| gold | DEAD | 91 | −0.176 | −0.195 | −0.194 | −0.233 | 24% |
| gold | HIGH_VOL_SHOCK | 13 | +0.059 | −0.248 | −0.266 | −0.229 | 31% |
| gold | RANGE | 510 | +0.019 | −0.001 | +0.004 | +0.026 | 29% |
| gold | TREND | 497 | −0.014 | +0.006 | +0.016 | +0.029 | 28% |
| all | TREND and VR > 1 | 1,267 | −0.090 | −0.091 | −0.092 | −0.050 | 27% |

No regime makes the SMC setup profitable. ADX-defined `TREND` setups are no better than `RANGE` ones; on crypto and forex they are worse. That makes sense: a CHoCH is a reversal signal, and it fights an ADX trend.

## Components against the adoption gate

| Component | Passed in any class × style? | Closest cell |
|---|---|---|
| SMC confluence (all six filters) | **no** | n ≤ 11 everywhere |
| HTF two-TF structure bias | **no** | gold DAY +0.34R, PF 1.54, n 70; below always-long |
| Liquidity sweep | **no** | forex DAY +0.11R, PF 1.16 |
| Displacement volume | **no** | crypto SWING +0.12R, PF 1.16 |
| Session windows | **no** | forex DAY +0.20R, PF 1.29, 4/4 folds; fails PF and min lot ($100) |
| Spread ≤ 20% of the stop | **no** | rarely binds |
| Premium/discount zone | **no** | gold DAY +0.16R, n 84 |
| E2 FVG-midpoint retrace | **no** | gold DAY +0.20R; below always-long |
| X1 partial at 1R | **no** | raises win rate, lowers expectancy |
| X2 pivot trail | **no** | crypto SWING +0.04R, 4/4 folds |
| X3 chandelier | **no** (closest of all) | crypto SWING +0.104R, PF 1.22, 4/4 folds, OOS-confirmed; fails PF 1.5 and min lot ($100) |
| X4 regime-switched exit | **no** | forex DAY +0.10R; not confirmed on folds 3–4 |

**Components that passed: none.**

## Changes made

None to live code. Added:

- `tools/smc_research.py`, the research tool with `--selftest`;
- this report.

The per-trade dataset for the later meta-labeling phase was written to the session scratchpad as `smc_trades.parquet`. It has 7,069 setups × 36 columns:

- the filter flags and features: body, range/ATR, volume ratio, spread/stop, stop/ATR, zone position, hour, both HTF reads, ADX, BB-width percentile, ATR ratio, VR and regime;
- the independent outcome under every exit, plus E2;
- the fold index.

It is not in the repo. Regenerate it with the command below.

## Caveats

- **Multiple comparisons.** About 150 configurations were tested across 9 cells. The two near-misses are the best of many, so both need a forward test before they mean anything.
- **SCALP rests on 6–8 months of M5.** Its folds are about 6 weeks each.
- **Min-lot affordability** (`sr.verdict`) fails for forex and crypto at $100 almost everywhere. The stops are structural, so they are wide in money.
- **Bar-level simulation.** Bars give no tick order; ambiguous bars resolve conservatively (stop first, break-even before target).

## Reproduce

```
python tools/smc_research.py --selftest
python -c "import sys; sys.path.insert(0,'tools'); import strategy_research as sr; sr.fetch(r'<dir>/bars.pkl', {**sr.SYMBOLS, **sr.FOREX})"
python -W ignore tools/smc_research.py <dir>/bars.pkl <dir>     # ~95 s; writes smc_tables.md, smc_results.json, smc_trades.parquet
```
