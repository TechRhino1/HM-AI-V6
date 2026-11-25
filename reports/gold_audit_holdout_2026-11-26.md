# HM Algo — Backtest on Real MT5 Data (730d cache, scored from 2026-05-24)

**Mode:** calibrated per-symbol win-rate profiles  
**Data:** MT5 terminal, real H1 bars (validated non-synthetic)  
**Initial balance:** $10,000.00 at 0.5% risk per trade  
**Generated:** 2026-11-25T18:48:10.732140+00:00

## 1. Headline

| Metric | Value |
|---|---|
| Symbols traded | 1 |
| Total trades | 529 |
| Win rate | 41.21% |
| Expectancy | +0.0623 R per trade |
| Average win / loss | +1.605 R / -1.019 R |
| Payoff ratio | 1.575 |
| Total R | +32.96 R |
| Profit factor | 1.09 |
| Net profit | $+515.62 |
| Max drawdown | 8.03% |
| Sharpe / Sortino / Calmar | 0.63 / 4.83 / 0.61 |
| Expectancy (sample-uniqueness weighted) | +0.0240 R |

**Win-rate target outcome:** 0/1 symbols met the target out-of-sample. 0 met it in-sample but failed out-of-sample (i.e. the target was reachable only by overfitting).

## 2. Per-symbol results

| Symbol | Trades | WR % | Exp (R) | PF | Net $ | MaxDD % | OOS WR % | OOS Exp (R) | Target | Binding constraint |
|---|---:|---:|---:|---:|---:|---:|---:|---:|:--:|---|
| XAUUSD | 529 | 41.2 | +0.062 | 1.09 | +515.62 | 8.03 | 65.2 | +1.255 | ✗ | win rate - best achievable in-sample with positive expectancy is 54.2% |

### 2a. What the learned regime policy contributes

Calibration reports the same out-of-sample sample twice: once with every regime enabled, and once with the regimes the learned policy has switched off removed. Both are purged out-of-sample w.r.t. the geometry and threshold; the policy itself is fitted on **training folds only**, so it has never seen the out-of-sample bars it filters. The gap between the two columns is the policy's entire contribution — read it as the honest size of the effect, not as free money.

| Symbol | OOS n (all regimes) | OOS WR | OOS Exp (R) | OOS n (policy applied) | OOS WR | OOS Exp (R) | Policy fitted on |
|---|---:|---:|---:|---:|---:|---:|---|
| XAUUSD | 587 | 65.2 | +1.255 | 587 | 65.2 | +1.255 | train folds |

## 3. Win-rate / expectancy frontier

For each target size (`tp_r`, as a multiple of initial risk) the table gives the highest win rate found at all, and the highest win rate that still carries positive expectancy. Where those two diverge, the gap is win rate that can only be bought by running a losing system. This is the direct evidence for whether the 75% target is reachable.

**XAUUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 54.8% | -0.237 | 2473 | — | — | — |
| 0.5 | 54.3% | -0.189 | 2465 | — | — | — |
| 0.6 | 54.3% | -0.136 | 2459 | — | — | — |
| 0.75 | 54.2% | -0.061 | 2445 | — | — | — |
| 1 | 54.2% | +0.065 | 2417 | 54.2% | +0.065 | 2417 |
| 1.5 | 53.6% | +0.300 | 2351 | 53.6% | +0.300 | 2351 |
| 2 | 52.9% | +0.533 | 2271 | 52.9% | +0.533 | 2271 |
| 2.5 | 53.0% | +0.743 | 2244 | 53.0% | +0.743 | 2244 |

## 4. Calibrated geometry per symbol

`tp_r` is the target distance in multiples of initial risk; `be` is the breakeven trigger (off = never lock breakeven); `pc` the partial bank; `mb` the time stop in bars; `thr` the entry score threshold.

The last two columns come from the isotonic score calibration: the realised win probability the fitted map assigns to a score sitting exactly at the deployed threshold, and the Brier score of that map (lower is better; 0.25 is the skill-free baseline for a balanced sample). The calibration is monotone, so it cannot change which candidates pass — it exists to make the score interpretable and to give the AI layer a probability rather than an arbitrary index.

| Symbol | tp_r | be | pc | mb | threshold | P(win) @ thr | Brier | Enabled regimes |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| XAUUSD | 2.5 | off | off | 24 | 0.439 | 62.1% | 0.225 | TREND_BEAR, REVERSAL, TREND_BULL, LIQUIDITY_SWEEP, BREAKOUT, RANGE, CONSOLIDATION, WEAK_TREND |

## 5. Portfolio risk allocation (HRP)

Not enough aligned per-symbol return history to compute HRP weights.

## 6. Entry rejection analysis

Why candidates were not traded under the calibrated profile. In calibrated mode these are the capital-protection gates plus the calibrated edge filter; the legacy 29-check stack no longer decides.

Counts are per **bar evaluated**, not per candidate: a bar on which the pipeline found no setup at all (`no directional bias`) is counted here too, because the engine has to consider and decline it. A large `no directional bias` count therefore means the pipeline rarely formed a view, not that a good trade was vetoed.

| Symbol | Top rejection reasons |
|---|---|
| XAUUSD | Cooldown active: 2 bars remaining. (94); Cooldown active: 1 bars remaining. (94); Cooldown active: 4 bars remaining. (52) |

## 7. Method and honesty notes

**Calibration is walk-forward.** Each symbol's geometry and entry threshold were chosen only on training folds and reported on purged out-of-sample folds (`PurgedKFold`, with the embargo excluded from both train and test). The deployed configuration is the one the folds agree on most often, not the best in-sample point.

**Win rate is a constrained objective, not a bare target.** The calibrator maximises expectancy subject to `win_rate >= target`, `trades >= min_trades` and `expectancy > 0`. A high win rate is trivially obtainable by shrinking the target relative to the stop, so a profile that reached 75% with negative expectancy would be rejected.

**The regime policy is fitted out-of-sample.** Which regimes are switched off is learned from trades the fold-selected configuration would have taken *inside its training windows*, never from the out-of-sample bars it then filters. Fitting the policy on the same sample it filters is a filter tuned to the test set: measured on this data it moved the aggregate out-of-sample result from roughly break-even to about +52R, which is the size of the artefact. Section 2a publishes both figures so the contribution can be judged rather than assumed.

**Intrabar ordering is conservative.** A bar whose range spans both the stop and the target is booked as a loss, because OHLC data does not reveal which came first. The previous engine resolved this optimistically, which inflated win rate exactly where the target lives.

**The backtest is hermetic.** All persistent-state reads and writes on the decision path are disabled during simulation (`jarvis.config.runtime`), so results are reproducible and cannot be influenced by live trade history.

### Known limitations

* Three months of H1 data bounds the achievable sample: with one-position-at-a-time and a time stop, a symbol yields roughly `bars / max_bars` trades. Per-symbol win rates on 20-40 trades carry wide confidence intervals.
* Costs are modelled as the realised spread from the data plus the symbol profile's commission (zero on XM Ultra Low). Swap/financing is not modelled.
* Regime labels and the candidate set come from the same pipeline under test; a regime that the pipeline cannot detect will not appear here.
