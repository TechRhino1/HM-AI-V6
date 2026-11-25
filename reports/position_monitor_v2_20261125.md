# Position monitor v2 — 2026-11-25

Branch `feat/position-monitor-v2` (stacked on `feat/gate-trace-verifier`, PR #19).

## Why
- **Repo evidence.**
  - `EXIT_LOCK_RESEARCH_2026-11-24` replayed 353 real trades on M1. Actual exits made −40.0R; holding to the original SL/TP made +50.4R. The extra monitor layers cost about 40R vs the core policy.
  - Live DB (960 closed bot trades): discretionary exits averaged −0.30R (1 win in 38); SL/TP closes averaged +0.20R.
  - NEWS N2 rejected pre-release de-risking.
- **External.** Kaminski & Lo 2014; Lo & Remorov 2017: tight stops lose to costs. Validate exits by counterfactual replay. The broker-side stop is the real protection. Handle retcodes, cap modify rates, log every change, cap correlated exposure.
- **Code map.**
  - Unproven layers (weekend, news, TP-zone harvest, scalp stagnation) acted live and overrode the crypto hold list.
  - Price was a bar close up to about 18 s old, and the peak was sampled rather than taken from bar highs and lows.
  - The brake and spread blowouts froze the trail.
  - A stale-SL race could loosen a stop, and failed modifies were re-sent every 2 s.
  - Forward-test positions had no portfolio-level protection.

## What changed
| Area | Change | Status |
|---|---|---|
| Price | Broker position price (closing side, 1 s fresh) for R / trail / clamp math; context (ATR, regime) unchanged | DONE |
| Peak | M1 high/low since entry folded into the excursion (bars after entry only; SELL on the ask). This also restores the peak after a restart. | DONE |
| Freezes | Emergency brake: its breakeven is now a one-way floor on top of the policy, and the policy keeps running. Spread blowout: the policy and peak keep running; only the broker send is deferred. | DONE |
| Loosen-proof | Every send is clamped one-way against the broker's latest SL | DONE |
| Modify robustness | Exponential backoff on failure (frozen gets a longer delay); "No changes" (10025) counts as success; max 6 modifies per ticket per minute | DONE |
| Small fixes | Shield lock read from config on a ticket's first tick; all per-ticket dicts pruned; margin ladder closes at most 1 position per minute; dead "tighten" branch is now an explicit alert | DONE |
| Layer registry | `monitor_layers` config (off / shadow / enforce). news_floor, news_bank, weekend_floor, weekend_bank, tp_zone_harvest and scalp_stagnation default to **shadow**. The hold list is exempt from all of them, and crypto from the weekend layers. | DONE |
| Audit trail | Every monitor SL/TP send and every SHADOW verdict is journaled (`kind=monitor`) and served at `/api/monitor` → System → Health "Position monitor actions" | DONE |
| Portfolio protections | Missing broker SL → emergency SL at 1.8×ATR (bot and FT). The emergency brake now also floors forward tests that are in profit. | DONE |
| Watchdog | New checks `currency_exposure` (same-direction risk per currency, incl. FT) and `stops_and_gap_risk` (naked positions CRITICAL; Friday gap ×3 worst case), plus the position-monitor heartbeat with `last_tick_ms` | DONE |
| Exit replay per layer | Counterfactual replay deciding which shadow layers to re-enable | PENDING (proposed as its own session) |
| Per-symbol context tick budget | Building contexts once per symbol with a time budget | PENDING (`last_tick_ms` now measured, to decide whether it is needed) |
| ML predictor skip | Not running the ML predictor when no enabled layer uses it | PENDING |

## Tests
- `tests/test_position_monitor_v2.py`: 14 tests covering:
  - M1 peak (after entry only; SELL on the ask; rate limit);
  - the one-way broker clamp (BUY and SELL);
  - backoff and rate cap;
  - shadow default, enforce, hold-list and crypto-weekend exemptions;
  - margin ladder cooldown;
  - missing-SL emergency stop for forward tests;
  - brake on profitable forward tests only;
  - 4×EURUSD shorts flagged as concentrated currency risk;
  - naked-position CRITICAL and the Friday gap ×3.
- The existing layer-mechanics tests now run with the layers enforced. Their assertions are unchanged.
- Full suite: see the PR description.

## Rollout
- The new defaults change live behaviour:
  - six unproven exits stop acting (shadow);
  - stops trail from the true peak;
  - forward tests gain the brake and the missing-SL protection.
- Watch System → Health for ≥ 72 h on demo before merging to the live account.
- Re-enable a layer only through `monitor_layers.<layer>=enforce` once the replay shows it beats "hold" in both halves with ≥ 30 affected trades and passes the deflated-Sharpe check.
