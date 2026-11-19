# Devil's Advocate gate: walk-forward calibration (2026-11-18)

**Verdict: NOT PUBLISHED.** On every group, the calibrated gate fails to beat the current gate out of sample.
The current rule stays in force (penalty <= `max_devil_penalty` (+10 if ai_score >= 75), threats <= 3).
`config/devil_gate_calibration.json` has `published: false`. The per-flag stats are still used, but only to *describe* each threat (`threat_stats`).

## Data
- Real MT5 H1 caches `data/market/real/<SYM>/<SYM>_H1_730d.parquet`, covering 2024-11-20 to 2026-11-17 for 8 symbols.
- I re-ran the production pipeline (`SignalScanner`: context -> regime -> analysts -> DecisionEngine) over every bar.
  The run took 1,094 s on 8 workers. It recorded each Devil's Advocate flag per candidate in `data/signals/devil/`; the shared `data/signals/*` caches were not touched.
- I kept only candidates whose traded side matches the side the critic judged.
  I replayed each one under its symbol's **deployed exit geometry** from `config/winrate_profiles.json`, using the same simulator, commission and 0.5-pip stop slippage as `calibrate_winrate.py`. The output is realised R.
- n: forex 34,005 (EURUSD, GBPUSD, USDCAD, USDJPY); gold 8,474 (XAUUSD); crypto 34,891 (BTC, ETH, SOL); pooled 77,370.
- Candidates overlap heavily, because consecutive bars often give the same setup. That makes the t-stats below optimistic, and roughly 2x is a fair discount.
- "Current gate pass" is read directly from each candidate's `failing_gates`. Note that in code `DecisionEngine.max_devil_penalty` defaults to **50.0**, not the 43 the comments and tests mention. The penalty is capped at 50, so in practice the live guard is only "threats <= 3", except for the fail-closed penalty of 100.

## Per-flag findings (mean-R delta with vs without the flag, Welch t)
| group | flag | n | WR delta | mean-R delta | t |
|---|---|---|---|---|---|
| crypto | excessive_spread | 3,484 | -2.6 pp | -0.256 | -18.6 |
| crypto | htf_conflict | 7,345 | +2.3 pp | -0.069 | -5.2 |
| crypto | extreme_volatility (+18 penalty) | 356 | +27.8 pp | **+0.556** | +9.3 |
| forex | adverse_divergence | 5,409 | -2.2 pp | -0.051 | -3.4 |
| forex | rsi_overextended | 9,424 | -0.8 pp | -0.032 | -2.6 |
| forex | unswept_equal_levels (+8 penalty) | 17,404 | +5.4 pp | **+0.080** | +7.2 |
| forex | adx_strong_counter (+14 penalty) | 468 | +7.5 pp | **+0.278** | +4.8 |
| gold | (no flag reaches abs(t) >= 2 on the adverse side) | | | | |
| gold | unswept_equal_levels | 1,805 | +4.2 pp | +0.075 | +3.3 |
| pooled | excessive_spread | 4,478 | -7.4 pp | -0.166 | -12.6 |

Several hand-weighted penalties point the wrong way in-sample: extreme_volatility, unswept_equal_levels and adx_strong_counter.
Only excessive_spread is a strong, consistent adverse signal. All flag stats are in the JSON.

## Out-of-sample comparison
Method: an expanding walk-forward over 5 time-ordered test folds (first sixth of the data used only for training), with a 48-bar embargo that drops any training trade still open near the start of the test fold.
The model is an L2 logistic P(loss | 20 flags). The threshold is chosen on training data only, to maximise kept expectancy, and must keep at least the share of trades the current gate passes on that same training data, so trade counts stay comparable.

| group | gate | OOS n | WR | expectancy R | PF |
|---|---|---|---|---|---|
| forex | current | 20,282 | 43.5% | -0.061 | 0.86 |
| forex | calibrated | 21,453 | 43.9% | -0.042 | 0.90 |
| gold | current | 5,029 | 56.2% | **+0.039** | 1.10 |
| gold | calibrated | 5,336 | 55.4% | +0.027 | 1.07 |
| crypto | current | 24,298 | 38.6% | +0.092 | 1.29 |
| crypto | calibrated | 22,402 | 38.8% | +0.095 | 1.30 |
| pooled | current | 49,611 | 42.4% | **+0.024** | 1.07 |
| pooled | calibrated | 54,906 | 42.7% | +0.015 | 1.04 |

Why each group was not published:
- **Forex**: the calibrated gate is better, but still negative expectancy. Neither gate makes forex candidates profitable.
- **Gold**: the calibrated gate is worse.
- **Pooled**: the calibrated gate is worse.
- **Crypto**: +0.002R overall, but it won only 2 of 5 folds, so that is noise. The "must win a majority of folds" rule was added *after* I saw this result, and I'm stating that here. Without it, crypto would have been published on a +0.002R edge.

A first run without the like-for-like trade-count floor kept about 1/3 of the trades. That run had higher expectancy in forex, gold and crypto (forex +0.0002R, gold +0.052R, crypto +0.112R), but it fails the comparable-n requirement. It shows that a stricter devil filter may help, but at a large cost in trade count.

## Wiring (behaviour unchanged while unpublished)
- `DevilAdvocateAnalyst` records `threat_flags` (20 stable ids), always attaches `threat_stats`, and sets `calibrated_loss_prob` / `calibration_group` only when its group is published.
- `decision_engine` "Devil Adversarial Guard" now calls `jarvis/analysts/devil_calibration.gate_passes`. That uses the calibrated threshold when the group is published; otherwise it runs the original expression, which is proven equivalent in tests. The fail-closed penalty of 100 always fails.
- The `inst_global.adverse_flags` signals (COT, dollar, yields, vol spike, F&O ban, event risk) are **not** included. They have no point-in-time history over this window, so they cannot be measured on these candidates.

Reproduce: `python tools/calibrate_devil_gate.py --scan --workers 8` (scan plus calibration, about 25 min), or omit `--scan` to only re-calibrate (about 4 min).
