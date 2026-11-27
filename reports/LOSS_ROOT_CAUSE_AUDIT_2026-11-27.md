# Loss root-cause audit: JARVIS MT5 (2026-11-27)

Branch `fix/loss-root-cause-2026-11-27`. Account: XM demo 101059540, about $466.
All backtests use real MT5 bars (`data/market/real/<SYM>/<SYM>_<TF>_365d.parquet`), real spread and slippage, and the engine in the loop. No synthetic data.
**No result below guarantees profit.** No cell reaches a deflated Sharpe ratio (DSR) of 0.95 after counting every trial.

## 1. Executive summary

- **Live record:** 1,026 closed trades (2026-08-23 to 11-26). Win rate 31%, PF 0.47, **−$1,654**.
  - Gold alone: 320 trades, −$1,287, PF 0.42.
  - Winners realised about +0.66R against a 2.54R plan; losers took the full −1R.
- **Root causes that were real and fixable** were fixed at source (§3).
  - The most damaging one: commit `4fd416a` turned `use_calibrated_entry_policy` off, which also **switched off the deployment gate for every symbol** and blinded the drift monitor.
- **The deployment gate is back and now judges engine-in-the-loop evidence per symbol × style**, on the exit policy that actually trades.
  - A cell must clear its asset-class hurdle on the 6-month holdout **and** must not have lost on the preceding 5-month train window.
  - Allowed cells now: **ETHUSD DAY, SOLUSD DAY, SOLUSD SWING, XAGUSD DAY, BTCUSD H4_SWING.**
  - **XAUUSD is refused in every style**, because no gold cell passes both windows (§6).
- **Measured, not adopted** (failed train, or holdout worse):
  - four entry filters (D1 trend, NY-open block, stop floors at 1×/1.5× ATR, USD regime);
  - the chandelier exit, globally and per cell;
  - the gold $12 cap applied to the placed stop;
  - index intraday momentum.
- **Biggest honest limitation:** most cells that are profitable on the holdout lost on the train window, so the edge is regime-dependent. The gate refuses those cells rather than trusting one half-year.

## 2. Baseline (before)

### Live trades (`data/jarvis_history.db` → `executed_trades`, read-only)

| Symbol | Trades | Win % | Net $ | PF |
|---|---:|---:|---:|---:|
| XAUUSD | 320 | 28.1 | −1,286.66 | 0.42 |
| SOLUSD | 67 | 19.4 | −123.36 | 0.06 |
| GBPUSD | 69 | 27.5 | −104.23 | 0.16 |
| EURUSD | 133 | 33.1 | −59.39 | 0.52 |
| ETHUSD | 138 | 37.0 | −3.38 | 0.93 |
| BTCUSD | 150 | 36.0 | +9.35 | 1.03 |
| Other 13 symbols | 149 | — | −86.46 | — |
| **Total** | **1,026** | 31 | **−1,654.13** | 0.47 |

Gold detail (bot trades):
- Stops under $8 had PF 0.27. $12–16 stops were the only profitable bucket (PF 1.13).
- 13:00–16:00 UTC entries had PF 0.09.
- With the D1/H1 trend, about PF 1.0. Against it, or neutral, losing.

### Engine baseline

Old code, default exit, holdout 2026-05-24 → 11-26 (`HM_main_chk/reports/base_holdout`): 64 cells, −107.8R over 3,270 trades, no DSR > 0.4.

## 3. Root causes and fixes

| # | Root cause (verified in code and data) | Fix | Commit |
|---|---|---|---|
| R1 | `deployment_refusal` returned None whenever `use_calibrated_entry_policy=false`; `4fd416a` set it false, so the EXPECTANCY/HOLDOUT gates were off for all symbols. | The gate reads stamped profiles regardless of the flag (`exit_geometry._stamped_profile`); fails closed; offline skip kept. | `50bac5b` |
| R1b | The calibrator stamps refuse every symbol except EURUSD, which passes vacuously with 0 holdout trades, because they judge a policy that no longer trades. | The gate judges engine holdout of the live policy per symbol × style (`reports/mode_backtest_report.json`), with fallback to the stamps. A cell that lost on train is refused (`STYLE_TRAIN_GATE`). | `b5324e8`, `16194c9`, `5213e7d` |
| R2 | EV used invented RR floors (`max(2.2, rr×1.1)` and similar), which inflated WAIT→EXECUTE promotion (`ev ≥ 0.40`), the positive-EV gate and the elite check. | EV uses the live target R (`live_target_r`), else the real levels RR; recomputed after the final RR. Thresholds unchanged. | `50bac5b` |
| R3 | The live exit (`institutional_lock`) was never backtested. | `JARVIS_BACKTEST_EXIT_MODE` / `--exit-mode` on `run_mode_backtest.py`, `run_3month_backtest.py`, `engine_select.py`. | `9b7d60c` |
| R4 | TP re-anchor desync. | Fixed in PR #22 (merged). | `a2ab111` |
| R5 | Live signals read the forming bar; the backtest reads closed bars. | `fetch_multi_timeframe` gives every role closed bars only; the forming close goes in `df.attrs["last_price"]` for bid/ask. | `d521cee` |
| R6/G1 | Gold $12 cap applied to every style. | SCALP/DAY only; SWING keeps its ATR ceiling (user decision). See §6 for why this cap rarely binds. | `c957e22` |
| G2 | H4_SWING/D1_SWING bias read as SWING; W1 never read. | D1_SWING resolves macro W1 → D1, context D1. | `3591af8` |
| G3 | Strategy names the selector never emits kept dead branches alive. | Removed. | `3591af8` |
| R7 | Missing initial SL, commission, journal ticket. | Already fixed in current code; only historical rows are affected. Verified, no change. | — |
| R8 | No correlated-risk grouping: FX only, and only from the 2nd trade. | METALS / CRYPTO / EQ_BETA groups, one bet per direction, from the first trade; risk-free runners excluded. | `dbd77ac` |
| R9 | PROMOTION_HOLE gate in shadow: 9 of 29 orders on 11-24..26 had 41–157% cost friction. | `gates.promotion_hole_mode = "enforce"`. | `019a1de` |
| Config | — | BTCUSD and ETHUSD added to `allowed_symbols` (user decision); they trade only where the gate allows. | `019a1de` |

**Only R2 changes backtest behaviour, and its measured effect is about neutral (§5).** R1, R5, R8 and R9 act on the live path, so a bar replay cannot measure them.

## 4. Research vs measurement

The external evidence points the same way:
- Moskowitz-Ooi-Pedersen, Hurst-Ooi-Pedersen, Man AHL and Baltussen et al.: the edge that survives costs is slow trend with a higher-timeframe bias, volatility-sized stops, and exits that let winners run.
- Liu-Tsyvinski: crypto time-series momentum.
- Elder-Miao-Ramchander: event volatility.
- Bailey-López de Prado: deflated Sharpe ratio (DSR) and multiple-testing control.
- There is no peer-reviewed intraday directional edge for gold after costs.

What was measured here:

| Idea | Source | Train (2025-12-15..05-21) | Holdout (05-24..11-26) | Verdict |
|---|---|---|---|---|
| D1 trend filter (G6) | trend literature, repo | all cells −41.7R → −68.4R; gold +27.0 → −18.6R | −74.9 → +9.7R | **Rejected**: fails train (regime-dependent) |
| Stop floor 1× ATR (G7) | live stops < $8 PF 0.27 | −41.7 → −48.7R | −74.9 → −72.2R | Rejected |
| Stop floor 1.5× ATR (G7) | research | −41.7 → −80.5R | −74.9 → −58.8R | Rejected |
| NY-open block (G10) | live 13–16 UTC PF 0.09 | no SCALP train data | gold +8.4 → +1.8R | Rejected |
| USD regime (G11) | dollar–gold link | −41.7 → −64.7R | −74.9 → −38.1R | **Rejected**: fails train |
| Chandelier exit (G8) | Kaminski-Lo, repo | best mode: −16.3R vs −49R lock | **−29.7R vs +40.1R lock** (DAY/SWING/H4) | Rejected globally |
| Exit picked per cell on train | — | — | 8 of 15 cells better (coin flip); +15.4R almost all gold SWING | Not promoted |
| Gold $12 cap on the placed stop | user decision, live buckets | DAY lock −0.098 → −0.100R/trade (×3 trades) | DAY lock +0.064R/117 → −0.018R/340 | **Reverted** (`5d05600`) |
| Index intraday momentum (IMOM) | Gao et al., Baltussen et al. | GER40 +0.379R, PF 1.50, 3 of 4 folds; US30/NAS100/UK100 negative | DSR ≤ 0.0001 over 36 trials | Not adopted (`reports/SESSION_LEADS_RESEARCH_2026-11-26.md`) |

DSR trials counted: 192 for the train exit grid (48 cells × 4 modes), 384 for the holdout (64 cells × 6 variants).

## 5. Per-symbol results (after fixes, live exit `institutional_lock`)

Holdout, expectancy R per trade (trades). Train shown for the consistency rule. **Gate**: P = may trade live, R = refused. SCALP has no train window, because M1 bars start on 2026-09-18 (holdout SCALP spans only 68 days).

| Symbol | SCALP | DAY hold / train | SWING hold / train | H4_SWING hold / train | Gate |
|---|---|---|---|---|---|
| XAUUSD | +0.010 (230) | +0.064 (117) / −0.098 | −0.027 (165) / +0.105 | +0.067 (46) / +0.514 | R all |
| XAGUSD | −0.065 (65) | **+0.094 (51) / +0.220** | +0.019 (117) / +0.201 | +0.191 (27) / −0.087 | P DAY |
| BTCUSD | −0.070 (385) | +0.204 (59) / −0.282 | +1.107 (4) / +0.300 | **+0.154 (16) / −0.094 (8)** | P H4_SWING |
| ETHUSD | −0.312 (217) | **+0.232 (44) / +0.014** | +0.599 (8) / −0.334 | +0.305 (6) / −0.363 | P DAY |
| SOLUSD | — | **+0.395 (31) / +0.055** | **+0.562 (12) / −0.472 (9)** | +0.146 (6) / −0.490 | P DAY, SWING |
| EURUSD | −0.151 (15) | −0.038 (76) / +0.117 | +0.096 (29) / −0.035 | +0.226 (17) / −0.188 | R |
| GBPUSD | — | −0.050 (79) / −0.115 | +0.161 (29) / −0.177 | +0.156 (18) / −0.124 | R |
| NZDUSD | — | −0.010 (87) / −0.182 | +0.092 (26) / −0.198 | +0.109 (20) / +0.059 | R |
| USDCHF | −0.421 (2) | +0.048 (77) / −0.103 | −0.080 (28) / −0.213 | −0.175 (17) / −0.299 | R |
| UK100 | −0.211 (57) | −0.306 (81) / −0.130 | −0.326 (25) / +0.066 | −0.304 (14) / +0.336 | R |
| US30 | −0.020 (60) | −0.191 (83) / −0.138 | −0.010 (26) / −0.172 | −0.349 (19) / −0.431 | R |
| Not allowed: AUDUSD, USDCAD, USDJPY, GER40, NAS100 | | see `reports/loss_audit/` | | | — |

Notes:
- BTCUSD H4_SWING and SOLUSD SWING pass because their train samples (8 and 9 trades) are under the 10-trade minimum for the train rule. SOLUSD SWING's train result (−0.472R over 9) is a warning; the drift monitor (§8) watches it.
- Full metrics per cell (win %, net R, PF, average win and loss, max DD in R, max consecutive losses, trades per week, DSR) are in `reports/loss_audit/*.md` and `reports/mode_backtest_report.json`.

### What changed the backtest: code vs exit

Same holdout and same 64 cells, real MT5 bars.

| Run | Trades | Net R |
|---|---:|---:|
| Old code, default exit (baseline) | 3,270 | −107.8 |
| Fixed code, default exit (code effect only) | 3,202 | −122.8 |
| Fixed code, live exit `institutional_lock` | 3,174 | −74.9 |

- **The backtestable code changes (mainly R2's honest EV) are neutral to slightly negative: −15R over about 3,200 trades, about −0.005R per trade.**
  - The biggest moves are gold SCALP (+0.002 → −0.034R/trade) and gold SWING (+0.274 → +0.231).
  - R2 is kept because it is a correctness fix: EV was computed from RR floors the trade never had. It is not kept for a profit claim.
- **Holding the code fixed, the live exit beats the default exit by +48R.** That supports keeping `institutional_lock` live.
- **One exception, gold SWING**, where the live exit is the worst of the three on the holdout:

  | Gold SWING | Train | Holdout |
  |---|---:|---:|
  | Default exit | +0.071 | +0.231 |
  | Chandelier | +0.333 | +0.081 |
  | `institutional_lock` (live) | +0.105 | −0.027 |

  Gold SWING is not routed now, because only 1% of its stops are affordable at $466. Revisit it when the balance can carry an $18 stop at 0.01 lot.
- Raw runs: `reports/loss_audit/after_holdout_default/`; table: `reports/loss_audit/eval_holdout_default.md`.


## 6. XAUUSD: every timeframe and style

**Timeframe roles:**

| Style | Macro | Context | Entry |
|---|---|---|---|
| SCALP | H1 | M15 | M5 |
| DAY | H4 | H1 | M15 |
| SWING | D1 | H4 | H1 |
| H4_SWING | D1 | H4 | H4 |
| D1_SWING | W1 | D1 | D1 |

D1_SWING now reads W1 (G2).

**Volatility (real MT5, 183 days):** median ATR is M5 $4.4, M15 $7.9, H1 $16.9, H4 $35.8, D1 $97.9, so a $12 stop is 0.71× H1 ATR.

**The $12 cap never bound the placed stop.** With multi-timeframe data, which is always present live and in backtests, `InstitutionalEntryEngine` sets the stop. The baseline level, where the cap lives, is only a floor: `max(inst_risk, base)`. Placed gold stops in the holdout:

| Style | p10 | Median | p90 |
|---|---:|---:|---:|
| SCALP | $8.0 | $11.7 | $20.8 |
| DAY | $22.1 | $38.9 | $59.7 |
| SWING | $18.2 | $18.2 | $18.2 |
| H4_SWING | $18.2 | $18.6 | $21.6 |

Applying the cap to the placed stop was tested and **made the holdout worse**, so it was reverted (§4). The same "cap is only a floor" behaviour applies to the silver, ETH and BTC caps. That is not changed here, because there was no user decision or evidence for it.

**Affordability at $466** (0.01 lot = $1 per $1 move; account-tier minimum-lot ceiling is 3.5% = $16.31):

| Style | Affordable at 0.01 lot |
|---|---:|
| SCALP | 71% |
| DAY | 0% |
| SWING | 1% |
| H4_SWING | 0% |

So even if a gold DAY, SWING or H4 cell passed the gate, sizing would refuse almost every live order at this balance. It refuses; it never squeezes the stop.

**Gold per style** (holdout / train, live exit):
- SCALP: +0.010R (below the +0.020R hurdle).
- DAY: +0.064 / −0.098. It is the main gold route by trade count, but lost on train.
- SWING: −0.027 / +0.105. The chandelier exit helps on both windows (+0.081 / +0.333), but it is unaffordable at this balance and was not promoted.
- H4_SWING: +0.067 / +0.514, but only 46 trades, under the commodity minimum of 50.

**Result: no gold style is deployable now.** It becomes eligible when an H4_SWING holdout reaches ≥ 50 trades at ≥ +0.020R, or a DAY cell stops losing on train, and the balance can carry the stop.

## 7. Risk management state

- **Sizing:** min-lot refusal from `account_tier` (gold 3.5%).
- **Stops:** dynamic per style; gold SCALP/DAY base cap.
- **Drawdown and consecutive-loss breakers:** existing circuit breaker and drawdown state, unchanged.
- **Spread / cost:** the scalp friction gate (`MAX_FRICTION_PCT` 0.35) plus PROMOTION_HOLE, now enforced.
- **Duplicates and conflicts:** existing per-symbol checks, plus correlated groups (R8).
- **Reserved gold slot:** PR #25. The gate still applies to it.

## 8. Monitoring agent (no new agent)

The existing `system_monitor`:
- compares live expectancy with the holdout benchmark when the holdout has ≥ 10 trades;
- writes one `MONITOR_DRIFT` advisory per day per verdict to `data/advisories/advisories_YYYYMMDD.jsonl`;
- recommends a re-run (`tools/engine_select.py`) and promotion (`tools/promote_model.py approve`).

**It never writes settings or parameters.** Before the fix it was blind with the calibrated flag off (`786794f`).

## 9. Testing

- New: `tests/test_loss_audit_2026_11_27.py`, covering R2, R3, R5, R8, R9, the drift monitor, and the per-style and train gates.
- Updated: holdout gate, live exit geometry, gold cap, regression, universe and session-leads tests.
- Full-suite result: see the PR description. Known baseline failures on `main` are listed in it.

## 10. Rollback

- **Code:** `git revert` the merge commit.
- **Gate evidence:** restore with `git show 5213e7d~1:reports/mode_backtest_report.json > reports/mode_backtest_report.json`. Deleting the file makes the gate fall back to the calibrator stamps, which refuse more symbols, not fewer.
- **Promotion hole:** `config/settings.json` `gates.promotion_hole_mode` = `"shadow"`.
- **Symbols:** remove BTCUSD/ETHUSD from `trading.allowed_symbols`.

## 11. Limitations

- No DSR ≥ 0.95 anywhere; every passing cell could be luck at this number of trials.
- Most holdout winners lost on train (regime dependence). The train rule refuses them, but it also uses only one earlier window.
- The SCALP holdout covers 68 days, and SCALP has no train window.
- Backtests size from $10,000. Live at $466, the minimum lot makes most gold, index and wide-stop cells unaffordable.
- R1, R5, R8 and R9 are live-path fixes that a bar replay cannot measure; the drift monitor is the check.
- The backtest does not model the news blackout widening (G9) or the always-long gold benchmark comparison (G5); both are not done.
- The live bot runs from the main checkout. These changes apply only after `main` is pulled and the bot restarted.

## 12. Addendum (2026-11-27): gold scalp override, AUTO style, and unlocking styles

User decisions after the merge of PR #26:
- gold trades SCALP now;
- other styles unlock on evidence plus affordability;
- the override stops itself on live losses;
- AUTO applies to all symbols.

- **Override:** `config/settings.json` `gates.deployment_overrides` allows **XAUUSD SCALP** despite its evidence (holdout +0.010R over 230, under the +0.020R hurdle).
  - **Probation:** once at least 30 live (non-paper) gold scalps have closed since 2026-11-27, and their mean net R is below −0.10R, the gate refuses with `OVERRIDE_STOPPED`. R is net P&L divided by the risk at the entry stop.
  - An unreadable trade DB refuses (`OVERRIDE_UNVERIFIED`).
  - To re-enable after a stop, edit the entry (for example a new `since`). Nothing re-enables itself.
- **AUTO:** `trading.trade_style: "AUTO"` is the startup style. Each sweep keeps one style per symbol: the best arbiter utility × earned score, among the styles that
  1. the deployment gate allows, and
  2. the account can carry at 0.01 lot under `account_tier.min_lot_risk_cap`.

  Skips are counted in the AUTO journal entry (`refused_by_gate`, `unaffordable`). Before this change AUTO could pick a style that the gate or sizer then refused, which cost the symbol its trade.
- **How gold's other styles unlock:**
  - Affordability at the 3.5% gold cap: SWING/H4 (typical stop about $18) from about $520–530; DAY (about $39) from about $1,115.
  - **Evidence:** they must also pass the gate on a fresh re-run. Today DAY lost on train, SWING lost on the holdout, and H4 has too few trades.
  - Re-run monthly with new windows:

    ```bash
    bash tools/backtests/run_loss_audit_grid.sh 3 holdout_lock train
    python tools/loss_audit_eval.py reports/loss_audit/after_holdout_institutional_lock \
      --write-mode-report reports/mode_backtest_report.json --holdout-window <start>..<end> \
      --exit-mode institutional_lock --train-run reports/loss_audit/after_train_institutional_lock
    ```

    Adjust the dates in `run_loss_audit_grid.sh` first. Nothing re-runs or rewrites the evidence automatically.
- **Dry sweep at $466** (paper, no dispatch): AUTO picked XAUUSD SCALP, SOLUSD DAY and ETHUSD DAY. BTCUSD and NZDUSD setups were skipped as refused by the gate.
