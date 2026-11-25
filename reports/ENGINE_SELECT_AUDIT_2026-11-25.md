# Audit + engine-in-the-loop per-symbol calibration, 6-month blind holdout — 2026-11-25

Real MT5 H1 bars only, refreshed today (`tools/fetch_real_data.py --days 730`, 16/16 symbols, last bar 2026-11-24).
Nothing promoted to `config/winrate_profiles.json`. Nothing committed.

## 1. Verdict

No symbol has a statistically significant edge on the blind holdout (2026-05-24 → 2026-11-24). Best DSR is 0.67 (BTCUSD); 0.95 is the usual bar.
Selecting with the real engine instead of the calibrator's simulator takes the portfolio from **−0.018R/trade (PF 0.91, DD 33.7%)**
to roughly **flat (+0.008R/trade over 1,239 trades)**. Almost all of that gain comes from refusing 12 symbols that show no engine edge even on the training year.

## 2. Method (new: `tools/engine_select.py`)

1. `calibrate_winrate.py --train-end 2026-05-21 --purge-days 3` → train-only base profiles (unchanged tool).
2. For each symbol, 11 candidates (the calibrated profile + 10 exit geometries: tp 1.0/1.5/2.0/2.5R × time stop 24/48 bars, plus BE@1R at 2.0/2.5R)
   are run through the **production `BacktestEngine`** on the train year 2025-05-21 → 2026-05-21.
3. Pick the highest train t-stat among candidates with ≥30 trades, PF > 1.05 and mean R > 0. If none qualifies, the symbol is "no edge" and is not traded.
4. Trade the single pick once on the holdout. Pass = existing HOLDOUT_GATE rule (≥10 trades, R > 0) plus PF > 1. DSR uses n_trials = symbols tested.

Why: on 2026-11-24 the calibrator's own out-of-sample numbers did not survive the engine. Today it again claims XAUUSD OOS +1.255R, PF 4.6; the engine on the same kind of data gives ~+0.02–0.07R.

## 3. Per-symbol results (holdout, after costs, 0.5% risk, $10k)

| Symbol | Engine pick (train) | Train n / exp R / t | Holdout n | Holdout exp R | PF | DSR | Pass | Calibrator-only holdout (old method) |
|---|---|---|---|---|---|---|---|---|
| BTCUSD | tp2.5, BE 1R, 48 bars | 134 / +0.271 / 3.01 | 120 | **+0.141** | 1.42 | 0.67 | ✅ | 128 / +0.094 / PF 1.16 |
| XAUUSD | tp2.0, BE 1R, 48 bars | 1248 / +0.019 / 0.58 | 656 | **+0.044** | 1.08 | 0.46 | ✅ | 533 / +0.068 / PF 1.08 |
| ETHUSD | tp1.5, 48 bars | 303 / +0.092 / 1.81 | 151 | −0.017 | 0.78 | 0.10 | ❌ | 130 / −0.081 |
| XAGUSD | tp2.0, 48 bars | 742 / +0.109 / 2.30 | 312 | −0.107 | 0.82 | 0.01 | ❌ | 250 / +0.002 |
| AUDUSD, EURUSD, GBPUSD, GER40, NAS100, NZDUSD, SOLUSD, UK100, US30, USDCAD, USDCHF, USDJPY | none qualified on train | – | 0 | – | – | – | ❌ | GER40 +0.099/138, GBPUSD +0.045/130, rest ≤ 0.003 or 0 trades |

Notes:
- XAGUSD shows the overfitting risk directly: train t = 2.30, holdout −0.107R with an 18.8% drawdown.
- BTCUSD is the only symbol consistent across both windows (train t 3.0 → holdout t 1.48).
- GER40 lost on the engine train year under every candidate but was positive on the holdout under the calibrator profile. That is regime drift, not something either method can exploit yet.

## 4. Audit

| Check | Result |
|---|---|
| Full test suite | 4 failed / 4112 passed. 3 are the known failures from 2026-11-24 (user's `allowed_symbols` edit ×2, options math). 1 was a **regression from PR #16**: `test_deployment_refusal_follows_the_real_profile_stats` did not know about HOLDOUT_GATE. **Fixed** (test now applies the holdout rule). |
| Wiring (`tools/audit_wiring.py`) | 200/200 modules import, 0 broken refs |
| MT5 data/specs (`reports/MT5_DATA_AUDIT_2026-11-25.md`) | Bars OK. Broker `volume_step` is now 0.001 vs profile 0.01 on 7 FX/gold symbols; harmless, because 0.01 is a valid multiple and execution reads the broker value. **Min-lot risk exceeds the 2.5% cap at current equity on XAUUSD (5.84%), US30 (7.04%), NAS100 (6.63%)**, so those cannot trade live at this balance whatever the profile says. |
| Exit parity probe | BE@1R ≡ no-BE for targets ≤ 1.65R because `ExitPolicy.profit_locks` already locks BE at 50% of TP. The simulator, engine and live path all do the same, so this is not a divergence. The redundant variant was dropped. |

## 5. Deployment state and decision needed

`config/winrate_profiles.json` is unchanged; every allowed symbol is still refused by HOLDOUT_GATE (from 2026-11-24).
`--promote config/winrate_profiles.json` would install the BTCUSD and XAUUSD picks (backup written first). Practical effect on the demo bot:
- **XAUUSD** is in `allowed_symbols` but its min lot risks 5.84% > 2.5%, so it would still be refused by risk sizing at the current balance.
- **BTCUSD** is not in `allowed_symbols` (removed by you), so nothing trades unless you add it back.

## 6. Reproduce

```
python tools/fetch_real_data.py --days 730
python tools/calibrate_winrate.py --days 730 --target 0.75 --wide-grid --train-end 2026-05-21 --purge-days 3 --out data/signals/holdout/winrate_profiles_train_to_2026-05-21.json
python tools/engine_select.py --profiles data/signals/holdout/winrate_profiles_train_to_2026-05-21.json --train-start 2025-05-21 --train-end 2026-05-21 --holdout-start 2026-05-24 --out engine_select_2026-11-25
python tools/backtests/run_3month_backtest.py --days 730 --start 2026-05-24 --profiles data/signals/holdout/winrate_profiles_train_to_2026-05-21.json --out backtest_6month_holdout_calibrator_2026-11-25
```
Runtime: calibration 67 min, engine selection 70 min (6 workers), baseline ~12 min.
