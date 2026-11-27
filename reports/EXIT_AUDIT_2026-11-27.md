# Exit audit: profit given back on reversals (2026-11-27, grid finished 2026-11-28)

## Contents

- The trade that started this audit.
- What was wrong, and what this PR fixes.
- Candidate exits and how they were tested.
- Results:
  - all symbols and styles together;
  - the selection per asset class and style;
  - gold.
- What changes live (nothing yet).
- Conclusions for profitability.
- Monitoring added.
- Limits.

Per-cell tables are in [EXIT_AUDIT_2026-11-27_selection.md](EXIT_AUDIT_2026-11-27_selection.md), with raw numbers in `.json`. This report builds on [EXIT_LOCK_RESEARCH_2026-11-24.md](EXIT_LOCK_RESEARCH_2026-11-24.md).

## 1. The trade: XAUUSD BUY #2607 (ticket 2009632524, demo, SCALP)

| Time (UTC) | Event |
|---|---|
| 08:18 | Fill at 3670.24. Stop 3658.42, so 1R = 11.82 points. Target 3699.79 (2.5R). |
| 08:18–09:02 | Stop unchanged. The institutional lock gives no protection below +1R. |
| 09:02 | Price reaches +1.03R. A single stop change applies break-even, the +0.3R floor and the 0.7R trail. |
| 09:02–09:07 | Ten trailing stop moves, each acknowledged by the broker in about 0.2 s. The last one, at 09:07, put the stop at 3676.86, with the peak at about 3685.0 (+1.25R). |
| 09:54 | Broker-side stop fills at 3676.58: 0.28 points of slippage, +0.54R. |

**Root cause:** the exit design, not its execution. `institutional_lock()` uses the same hard-coded constants for every symbol and style, so it always gives back up to 0.7R from the peak:
- trigger at 1.0R;
- floor at +0.3R;
- trail of 0.7R.

There was no delay, no failed modification and no broker problem. A replay of the stored price path reproduces +0.54R and a stop of about 3676.7 (see `tests/test_exit_audit_e.py`).

## 2. Defects found and fixed in this PR

These change no trading rule.

1. **MFE and MAE were lost on every broker-side stop or target exit.**
   - Cause: the generic prune removed `_peak_mfe` / `_peak_mae` before they were saved.
   - Impact: 54 of 55 closes since 15 Nov stored NULL, so give-back was invisible in live data.
   - Fix: they are now retired and saved for every close.
2. **A refused stall exit skipped that tick's stop update.** The SCALP stagnation branch now returns only when the exit was actually sent.
3. **Default backtests did not measure the live exit.**
   - `run_mode_backtest.py --exit-mode` now defaults to `live`: per cell, exactly what trades today.
   - `tools/revalidate.py` always passes it.
   - SELL stops on the ask were already modelled by the one-spread entry and stop shift, so nothing changed there.

## 3. Candidate exits and how they were tested

The three variants were fixed before any run, with no parameter search:

| Variant | Rule | Target leak |
|---|---|---|
| `early_protect` | Stop moves to break-even once the peak reaches 0.6R. | 0.5–1.0R trades that reverse into full losses. |
| `ratchet` | Trail tightens to 0.5R after a 1.5R peak, and to 0.4R after 2.5R. | Give-back on winners. |
| `early_ratchet` | Both of the above. | Both. |

None of them is ever looser than the current rule.

**Data:** real MT5 bars, the rolling windows of `revalidate.py`, every symbol × style.
- **Train:** 2025-12-15 to 2026-05-21, covering DAY_TRADING, SWING and H4_SWING.
- **Holdout:** 2026-05-24 to 2026-11-26, covering all four styles.
- **Size:** 448 runs, 256 holdout trials counted in the DSR.

**Rules:**
- **Train selects** per asset class × style. To be chosen, a variant must beat the baseline on all four:
  - expectancy;
  - total R;
  - profit factor;
  - mean max drawdown.
- **Holdout only confirms:** both expectancy and total R must be no worse than the baseline.
- **SCALP has no train window** (M1 history starts inside the holdout), so a SCALP choice is PROVISIONAL until the live shadow confirms it.

**One rule was added after the grid:** the total-R requirement. It can only reject more choices, never fewer. It was added because of the churn effect in §4. It changed two outcomes:
- INDEX · SWING went from confirmed to rejected (holdout total −10.7R → −12.1R).
- INDEX · SCALP's `ratchet` was dropped (equal total R).

## 4. Results: all symbols together (holdout, 3,174 baseline trades)

| Exit | Trades | Total R | R / trade | Give-back after +1R | +1R trades closed ≤ 0R |
|---|---:|---:|---:|---:|---:|
| **live (today)** | 3,174 | **−75** | −0.024 | 0.79R | 96 |
| early_protect | 4,083 | −248 | −0.061 | 0.77R | 12 |
| ratchet | 3,572 | −177 | −0.050 | 0.70R | 17 |
| early_ratchet | 4,151 | −245 | −0.059 | 0.72R | 12 |

On train, all four exits are flat and within noise (−42R to −52R over about 2,000 trades).

**Breakdown by best open profit (MFE), holdout:**

| MFE | live | early_protect | ratchet |
|---|---|---|---|
| < 0.5R | 1,505 trades, −939R | 1,922 trades, **−1,257R** | 1,706, −1,064R |
| 0.5–1.0R | 471, **−341R (−0.72/trade)** | 989, **−115R (−0.12/trade)** | 525, −385R |
| 1.0–2.5R | 1,025, +839R | 1,034, +867R | 1,236, +1,075R |
| ≥ 2.5R | 173, **+366R** | 138, +257R | 105, +198R |

**What this shows:**
- **The early protection works where it was aimed.** It cuts the 0.5–1.0R leak from −341R to −115R, and missed protection drops from 96 to 12.
- **It also costs more than it saves, for two reasons:**
  - **Fewer runners.** Many trades that become 2.5R winners first dip back to entry. A stop at break-even takes them out (173 → 138 trades, −109R).
  - **Churn.** A protected exit frees the symbol's slot sooner, and the engine re-enters. Those extra entries are mostly trades that never reach 0.5R (+417 trades, −318R).
- **The ratchet keeps more on 1–2.5R winners (+236R), but loses more:**
  - runners that would have gone to ≥ 2.5R are cut (−168R);
  - its own extra re-entries lose too (−125R).

## 5. Selection per asset class × style

| Class × style | Result |
|---|---|
| **INDEX · DAY_TRADING** | **`early_ratchet` CONFIRMED.** Train −14.3R → −1.3R; holdout −35.8R → −29.3R; PF and drawdown not worse. DSR 0 per cell, so it isn't significant on its own. |
| **CRYPTO · SCALP** | `early_protect` **PROVISIONAL.** Holdout −94.7R → −89.2R. Needs the live shadow. |
| **FOREX · SCALP** | `early_protect` **PROVISIONAL.** Holdout −4.7R → −4.5R on only 20 trades. Needs the live shadow. |
| COMMODITY · DAY_TRADING, COMMODITY · H4_SWING, CRYPTO · H4_SWING, CRYPTO · SWING, FOREX · H4_SWING, FOREX · SWING, INDEX · SWING | **REJECTED.** Better on train, worse on holdout. |
| COMMODITY · SCALP, COMMODITY · SWING, CRYPTO · DAY_TRADING, FOREX · DAY_TRADING, INDEX · H4_SWING, INDEX · SCALP | **KEEP.** No variant passed. |

No single symbol showed a clear edge on both windows, so there are no per-symbol exceptions.

The proposed setting is:
```
trading.exit_cells = {"CRYPTO|SCALP": "early_protect", "FOREX|SCALP": "early_protect", "INDEX|DAY_TRADING": "early_ratchet"}
```

### Gold

**XAUUSD SCALP** (holdout, 230 trades): live gives +0.010R per trade with 0.65R give-back. Every variant is worse:
- early_protect −0.012R;
- ratchet −0.003R;
- early_ratchet −0.009R.

**Gold's scalp exit stays as it is.** The give-back seen on #2607 is the price of letting the 1.0–2.5R winners run. On this data, tighter rules gave up more than they saved.

Gold in the other styles:
- **XAUUSD H4_SWING:** improves with early_protect on the holdout (+0.07R → +0.24R), but not on train (equal). The class as a whole was rejected.
- **XAUUSD DAY_TRADING and SWING:** no variant is consistently better.

## 6. What changes live

**Nothing until you approve it.** The candidate evidence (`reports/staging/exit_candidate/`) differs from the active version only in `exit_cells`. A dry run shows:
- 0 tightenings;
- 0 loosenings;
- 1 exit-policy change.

**Path to live:**
1. After merge, promote the candidate. It becomes PENDING.
2. Each changed cell needs ≥ 20 complete demo/live shadow closes with mean shadow R ≥ mean real R.
3. Then `python tools/promote_model.py approve mode_evidence <version> --reason ...` installs the evidence and the `exit_cells` together.
4. Rollback: `python tools/promote_model.py rollback mode_evidence <previous>`.

## 7. Conclusions for profitability

- **The exit rule is not the main problem.** Today's rule is at least as good as any of the three variants overall.
- **The main problem is entries.** 47% of holdout trades (1,505 of 3,174) never reach +0.5R; they cost −939R.
  - In SCALP, 790 of 1,171 trades close on the stagnation stop at −0.31R.
  - So better entry selection is the next work (PR F, remove-only filters).
- **Re-entry after a protected exit is a second, measurable leak.** Any future tighter exit must be judged on total R, not R per trade. PR F should also test a cooldown after a break-even or protected exit.
- **The overall holdout is slightly negative** (−0.024R per trade on today's exit). These are backtest figures, not a forecast, and no change here guarantees profit.

## 8. Monitoring added

- **Health page, check `exit_quality`.** Over the last 200 live closes it reports capture of +1R peaks, give-back, missed protection and average stop slippage. It WARNs when:
  - a cell gives back more than its holdout by over 2 standard errors; or
  - stops fill more than 0.10R beyond their level.
- **Performance page:** Capture, Give-back R and Missed columns.
- **Shadow forward test:** every live position also runs the three variants on virtual stops, stored in `shadow_exits` in `jarvis_history.db` (migration 8, run at restart). Nothing is sent to the broker.

## 9. Limits

- **SCALP has no train window,** so its choices rest on one window plus the shadow.
- **The shadow compares matched trades only.** It cannot see the churn effect, so for the two SCALP cells it may be more favourable than live would be.
- **Partial closes aren't possible.** At this balance, positions are 0.01 lot.
- **The chandelier exit isn't eligible.** It can be looser than the current rule, so the shadow rule can't approve it.
