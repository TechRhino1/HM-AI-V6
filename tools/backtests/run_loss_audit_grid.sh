#!/usr/bin/env bash
# Evidence grid for reports/LOSS_ROOT_CAUSE_AUDIT_2026-11-27.md: real MT5 data (365d cache),
# holdout 2026-05-24..11-26 (unseen by selection), train 2025-12-15..2026-05-21 for exit-mode choice.
# Usage: bash tools/backtests/run_loss_audit_grid.sh <workers> <stage...>   stages: holdout train
set -u
cd "$(dirname "$0")/../.."
W=${1:-4}; shift
SYMS=XAUUSD,XAGUSD,BTCUSD,ETHUSD,SOLUSD,EURUSD,GBPUSD,USDJPY,USDCHF,USDCAD,AUDUSD,NZDUSD,US30,NAS100,GER40,UK100
for stage in "$@"; do
  case $stage in
    holdout)
      for mode in "" institutional_lock; do
        python tools/backtests/run_mode_backtest.py --workers "$W" --days 365 --symbols $SYMS \
          --styles SCALP,DAY_TRADING,SWING,H4_SWING --start 2026-05-24 --end 2026-11-26 \
          ${mode:+--exit-mode $mode} --out "reports/loss_audit/after_holdout_${mode:-default}"
      done ;;
    train)
      for mode in "" institutional_lock hold chandelier; do
        python tools/backtests/run_mode_backtest.py --workers "$W" --days 365 --symbols $SYMS \
          --styles DAY_TRADING,SWING,H4_SWING --start 2025-12-15 --end 2026-05-21 \
          ${mode:+--exit-mode $mode} --out "reports/loss_audit/after_train_${mode:-default}"
      done ;;
  esac
done
