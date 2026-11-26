#!/usr/bin/env bash
# Evidence grid for reports/LOSS_ROOT_CAUSE_AUDIT_2026-11-27.md: real MT5 data (365d cache),
# holdout 2026-05-24..11-26 (unseen by selection), train 2025-12-15..2026-05-21 for exit-mode choice.
# Usage: bash tools/backtests/run_loss_audit_grid.sh <workers> <stage...>
#   stages (run in the order given): holdout_lock holdout_default train
# Skips a symbol x style cell whose result file already exists, so a stopped run resumes.
set -u
cd "$(dirname "$0")/../.."
W=${1:-4}; shift
SYMS=XAUUSD,XAGUSD,BTCUSD,ETHUSD,SOLUSD,EURUSD,GBPUSD,USDJPY,USDCHF,USDCAD,AUDUSD,NZDUSD,US30,NAS100,GER40,UK100

run() {  # run <out_dir> <styles> <start> <end> [exit_mode]
  local out=$1 styles=$2 start=$3 end=$4 mode=${5:-}
  local todo=() s st
  for st in ${styles//,/ }; do
    for s in ${SYMS//,/ }; do [ -f "$out/${s}__${st}.json" ] || todo+=("$s"); done
  done
  [ ${#todo[@]} -eq 0 ] && { echo "skip $out (complete)"; return; }
  python tools/backtests/run_mode_backtest.py --workers "$W" --days 365 --symbols "$SYMS" \
    --styles "$styles" --start "$start" --end "$end" ${mode:+--exit-mode $mode} --out "$out"
}

for stage in "$@"; do
  case $stage in
    holdout_lock)    run reports/loss_audit/after_holdout_institutional_lock SCALP,DAY_TRADING,SWING,H4_SWING 2026-05-24 2026-11-26 institutional_lock ;;
    holdout_default) run reports/loss_audit/after_holdout_default SCALP,DAY_TRADING,SWING,H4_SWING 2026-05-24 2026-11-26 ;;
    train)
      for mode in "" institutional_lock hold chandelier; do
        run "reports/loss_audit/after_train_${mode:-default}" DAY_TRADING,SWING,H4_SWING 2025-12-15 2026-05-21 "$mode"
      done ;;
  esac
done
