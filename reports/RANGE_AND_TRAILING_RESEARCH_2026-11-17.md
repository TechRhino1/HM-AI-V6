# Range S/R trading and the institutional trailing stop: research (2026-11-17)

**Request:** "in sidewise market it should follow the trend line and buy from the support and sell from the resistance so we can make profit please research on this and make it fix and traling stoploss functionality should be upgraded to intuitional level please research on it and improve"

## Short answer

- **Buying support and selling resistance in a sideways market loses money after costs** on all 9 symbols tested (5 forex pairs, BTC, ETH, SOL, gold) and on all three timeframes (M15, H1, H4). This holds both for horizontal ranges and for trend-line channels. **Nothing was adopted.** `RANGE_MEAN_REVERSION` stays as it was (label only, banned on most symbols).
- **The opposite trade was positive.** Trading the *break* of the same levels made money on H1/H4 forex (+0.11R / +0.19R per trade). This matches the support/resistance literature. It is reported as a lead, not adopted: it was a benchmark, not a pre-registered candidate.
- **The institutional trailing stop is built and tested, but off by default.** It is a chandelier trail plus a structure trail, starting at +1R. On the same entries it did **not** beat today's stop logic where the entries had an edge. On H4 swing trades it was worse: +0.05R versus +0.08R. The best policy on those entries was **no trailing at all**: a fixed stop and target scored +0.108R and beat today's stack in both halves.

## Method

- **Tools:** `tools/range_research.py` and `tools/exit_research.py`, both on `tools/strategy_research.py` machinery.
- **Data:** frozen, real XM MT5 bars: 50,000 bars per timeframe, H4/D1 back to 1973 for forex.
- **Costs:** entry at the next bar's open paying the real per-bar spread, slippage, broker swap, stop assumed hit first when stop and target share a bar, and gaps filled at the open.
- **Parameters:** all fixed in advance, no tuning.
- **Adoption gate** (unchanged from the earlier research):
  - profit after costs
  - profit factor > 1.1
  - both halves positive
  - survives spread × 2
  - beats always-long and flipped-direction trades at the same entries
  - at least 100 trades
  - affordable at the minimum lot

### Candidates

**`range_sr`:**
- Setup: setup-timeframe ADX(14) < 20 and higher-timeframe ADX < 25.
- Levels: support and resistance are each confirmed by at least 2 fractal pivots within 0.5·ATR; the range is 3–12 ATR wide.
- Entry: BUY when a bar touches support (within 0.25·ATR) and closes back above it in the upper half of the bar; SELL mirrored at resistance.
- Stop: 0.5·ATR beyond the boundary. Target: the opposite boundary. Time stop: 48 bars.

**`channel_sr`:** the "trend line" version.
- Lines are fitted through the last 3 pivot lows and the last 3 pivot highs, both sloping the same way, 3–12 ATR apart.
- BUY at the lower line of a rising channel; SELL at the upper line of a falling one. Stop and target as above.

## Results: range and channel (pooled over symbols, R per trade after all costs)

| Candidate | TF | Group | n | Exp R | Flipped (break) | Spread ×2 |
|---|---|---|---|---|---|---|
| range_sr | M15 | forex | 286 | −0.266 | −0.408 | −0.488 |
| range_sr | M15 | crypto+gold | 120 | −0.543 | −0.597 | −0.979 |
| range_sr | H1 | forex | 213 | −0.202 | **+0.111** | −0.193 |
| range_sr | H1 | crypto+gold | 100 | −0.521 | −0.011 | −0.626 |
| range_sr | H4 | forex | 183 | −0.096 | **+0.185** | −0.108 |
| range_sr | H4 | crypto+gold | 27 | −0.435 | +0.827 | −0.547 |
| channel_sr | M15 | forex | 3,915 | −0.405 | −0.367 | −0.627 |
| channel_sr | M15 | crypto+gold | 3,781 | −0.775 | −0.793 | −1.320 |
| channel_sr | H1 | forex | 4,007 | −0.166 | −0.114 | −0.228 |
| channel_sr | H1 | crypto+gold | 3,539 | −0.362 | −0.313 | −0.553 |
| channel_sr | H4 | forex | 3,290 | −0.010 | −0.022 | −0.067 |
| channel_sr | H4 | crypto+gold | 1,280 | −0.061 | −0.095 | −0.114 |

Closest individual cases, none of which passes:

| Symbol / candidate / TF | Exp R | Why it fails |
|---|---|---|
| XAUUSD channel_sr H4 | +0.12 (n 380) | below always-long; min lot fits only 70% of trades at $545 |
| USDJPY channel_sr H4 | +0.085 (n 753) | below always-long; min lot at $100 |
| EURUSD channel_sr H4 | +0.069 | PF 1.09; second half negative |
| AUDUSD range_sr H4 | +0.55 | n 18 |
| BTCUSD range_sr M15 | +0.64 | n 20 |
| GBPUSD range_sr M15 | +0.14 (n 68) | second half −0.39 |

Full per-symbol table: run `python tools/range_research.py <bars.pkl> <out.json>`.

### Why the fade loses: the literature agrees

- **Osler (2000)**, FRBNY *Economic Policy Review*, "Support for Resistance: Technical Analysis and Intraday Exchange Rates": published S/R levels *interrupt* intraday FX trends more often than random levels. The effect is a pause, small in size.
- **Osler (2003)**, *Journal of Finance*, "Currency Orders and Exchange Rate Dynamics": take-profit orders cluster *at* round numbers, so price stalls there. Stop orders cluster just *beyond* them, so a break accelerates.

The bounce is short and smaller than the spread plus a stop beyond the level. The break runs. Our flipped results show exactly that shape.

**Lo, Mamaysky & Wang (2000)** find some chart patterns carry information, but no economically large fade edge.

## Results: trailing stop (same entries, every policy, pooled over 9 symbols)

- **Entries:** Donchian 20/10 breakouts (stop 3·ATR, target 2.5R) on H1 (DAY_TRADING exits) and H4 (SWING exits), plus range_sr on H1.
- **Policies:** every policy runs through the production `exit_policy.evaluate_exit`.
- **Micro-account rule:** `partial_executable=False`, because a 0.01 lot cannot split, as on the live account.

| Entries | Policy | n | Exp R | WR | Avg win | Avg loss | 1st half | 2nd half |
|---|---|---|---|---|---|---|---|---|
| Donchian H1 DAY | fixed stop + target | 6,814 | −0.038 | 28% | +2.48 | −1.03 | −0.055 | −0.021 |
| | legacy (today) | | −0.048 | 32% | +1.46 | −0.75 | −0.052 | −0.044 |
| | institutional k=3 | | −0.042 | 41% | +1.00 | −0.77 | −0.033 | −0.050 |
| | institutional k=3.5 | | −0.042 | 41% | +1.00 | −0.76 | −0.032 | −0.052 |
| | institutional k=3, no target | | −0.043 | 41% | +1.00 | −0.77 | −0.031 | −0.055 |
| Donchian H4 SWING | **fixed stop + target** | 4,183 | **+0.108** | 33% | +2.48 | −1.04 | +0.110 | +0.107 |
| | legacy (today) | | +0.079 | 34% | +1.54 | −0.66 | +0.079 | +0.078 |
| | institutional k=2 | | +0.045 | 43% | +0.95 | −0.64 | +0.059 | +0.031 |
| | institutional k=3 | | +0.054 | 43% | +0.98 | −0.64 | +0.073 | +0.035 |
| | institutional k=3.5 | | +0.058 | 43% | +1.00 | −0.64 | +0.073 | +0.043 |
| | institutional k=3, no target | | +0.060 | 43% | +1.00 | −0.64 | +0.083 | +0.037 |
| range_sr H1 | fixed | 313 | −0.320 | 18% | +3.28 | −1.10 | −0.305 | −0.335 |
| | legacy | | −0.300 | 29% | +1.46 | −1.01 | −0.341 | −0.260 |
| | institutional k=3 | | −0.245 | 35% | +1.21 | −1.02 | −0.226 | −0.264 |

### Reading the trailing table

- **Trailing raises the win rate and lowers the profit.** Win rate goes from 33% to 43%, but the average winner falls from 2.5R to 1R. A trade that reaches +1R and pulls back exits near breakeven instead of later reaching its target. Every trailing variant, today's and the institutional one, gives up more in winners than it saves in losers.
- **This is the published result.** Kaminski & Lo (2014, *Journal of Financial Markets*, "When do stop-loss rules stop losses?"): stops add value only when returns are persistent (momentum). Otherwise they lower expected return. LeBeau's chandelier exit is designed for long-horizon trend following with no target, where it trails *wide*.
- **On these entries even a wide chandelier (3.5·ATR) gives back more than it protects.**
- **Verdict:** the institutional mode is adopted for no style; the code stays with `trail_mode="legacy"`.
- **Strongest evidence:** on H4 swing entries, *no trailing* (fixed stop + target) beat today's stack in both halves (+0.110 / +0.107 vs +0.079 / +0.078). That is a decision for you (see below), not something I switched.

## What changed in code

| File | Change |
|---|---|
| `jarvis/execution/exit_policy.py` | `ExitPolicy.trail_mode` (default `"legacy"`, so nothing changes live), `chandelier_atr_mult`, `be_at_r`. `_institutional_trail`: initial stop until +1R, then the tightest of breakeven + buffer, the chandelier (best price since entry − k·ATR) and the last swing beyond entry − 0.25·ATR; one-way. `struct_level_for`: one structural-level rule shared by live and backtest. |
| `jarvis/execution/position_monitor.py`, `jarvis/backtesting/engine.py` | Both use `struct_level_for`. The backtester used to ratchet behind the raw swing even against the trade's structure; now it applies the live filter (higher lows / lower highs, beyond entry). |
| `tools/strategy_research.py` | Brought onto main from the research branch. It adds forex symbols, the M15 timeframe, MT5 fetch retries, a 50k-bar cap, and per-trade targets. |
| `tools/range_research.py`, `tools/exit_research.py` | The two studies above, with self-tests. |
| `tests/test_institutional_trail.py` | The 1R gate, chandelier, structure trail, breakeven buffer, never-loosen, SELL mirror and the shared structural filter. |

## Decisions left to you

1. **Fixed target for SWING / H4_SWING** (as gold already has). The evidence says it beats today's trailing on swing-type entries. Caveat: Donchian entries are not the engine's own entries. Confirming would need a run of `run_backtest` with `mtf_frames` on the engine's swing trades.
2. **Test "trade the break of S/R" as a pre-registered candidate:** for example, a close beyond a 2-touch level with ADX rising, on H1/H4 forex.

## Caveats

- The entries in the exit study are Donchian and range rules, not the live decision engine's entries. Live-only locks (PROX_LOCK, MFE retrace, the reversal phases, VWAP/momentum/ML) cannot be replayed, so "legacy" here is the shared core only.
- Forex history before about 2018 uses modelled spreads where the broker recorded zero; crypto before 2018 is the same.

## Follow-up: the engine's own swing trades (fixed stop + target vs today's exits)

- **Method:** `BacktestEngine.run_backtest` with `mtf_frames` (M15/H1/H4/D1) on 9 symbols, from 2024-11-16 to now.
- **"Fixed"** is what `fixed_target_r` does for gold: no breakeven, partials, milestones, trail or progress locks.
- **Trade counts differ between modes** because exit timing changes which later entries are free to fire.

| Style | Exits | n | Exp R | WR | Avg win | Avg loss | PF | 1st half | 2nd half |
|---|---|---|---|---|---|---|---|---|---|
| SWING | legacy | 260 | −0.051 | 27% | +1.82 | −0.73 | 0.90 | −0.071 | −0.030 |
| SWING | fixed | 213 | −0.016 | 22% | +2.73 | −0.77 | 0.97 | +0.044 | −0.075 |
| H4_SWING | legacy | 150 | +0.024 | 25% | +1.76 | −0.56 | 1.06 | −0.110 | +0.158 |
| H4_SWING | fixed | 94 | +0.033 | 21% | +2.51 | −0.64 | 1.07 | +0.071 | −0.004 |
| D1_SWING | legacy | 91 | +0.024 | 31% | +2.06 | −0.88 | 1.04 | +0.042 | +0.006 |
| D1_SWING | fixed | 45 | +0.697 | 33% | +4.09 | −1.00 | 2.05 | +0.241 | +1.134 |

**Verdict: no switch.**
- Fixed exits score higher on average in every style, but neither SWING nor H4_SWING beats legacy in both halves.
- D1_SWING's +0.70R comes from 45 trades, 32 of them ETH, so it is below the n ≥ 100 gate.
- The exits are not the main problem: the engine's swing entries themselves are about breakeven (SWING PF 0.90). About a third of trades end on the stagnation time stop.
