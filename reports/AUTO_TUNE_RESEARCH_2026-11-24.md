# Dynamic auto-tune walk-forward on live trades 2026-11-24

353 clean closed live demo trades. Before each entry, DYNAMIC selects symbols from the closes known at that moment. `actual R` is what each trade made; `lock R` is the same trade under the shipped exits (lock + hold list). Priors are the calibrated profiles of 2026-11-19 (730 days of bars, which overlaps this period); the live-only row uses no prior.

| Selection | trades kept | actual R | 1st half | 2nd half | lock R | 1st half | 2nd half |
|---|---|---|---|---|---|---|---|
| all symbols (today) | 353/353 | -40.0 | -37.3 | -2.7 | +55.7 | -35.6 | +91.3 |
| DYNAMIC (priors + live) | 126/353 | -14.7 | -11.2 | -3.5 | +46.8 | +1.0 | +45.8 |
| DYNAMIC (live only) | 144/353 | -8.8 | -9.9 | +1.1 | +29.2 | -19.6 | +48.7 |
| DYNAMIC (priors + live, learns lock R) | 159/353 | -11.2 | -8.2 | -3.1 | +82.3 | +4.6 | +77.7 |
| DYNAMIC (live only, learns lock R) | 197/353 | -11.0 | -9.7 | -1.3 | +73.1 | -7.7 | +80.8 |

## Reading

- **Learning from the shipped exits** (lock R, which the ledger records from now on), DYNAMIC with priors makes +82.3R against +55.7R for trading every symbol. It turns the first half from −35.6R into +4.6R, using 159 of 353 trades.
- **It still trails in the second half** (+77.7 vs +91.3R), so it misses the both-halves adoption gate.
- **Learning from the old exits' R** (what the ledger holds today), it does worse than trading every symbol under the shipped exits.

Decision: DYNAMIC ships as the default manual profile, and `trading.auto_tune` stays `"off"`. The 30-minute schedule is one switch away on System → Symbol universe. Re-run this after about 30 trades per symbol under the shipped exits: `python tools/exit_research.py --auto-tune <out.md>`.
