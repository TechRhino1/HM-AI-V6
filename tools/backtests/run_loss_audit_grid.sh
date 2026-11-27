#!/usr/bin/env bash
# Evidence grid for reports/LOSS_ROOT_CAUSE_AUDIT_2026-11-27.md: real MT5 data (365d cache),
# holdout 2026-05-24..11-26 (unseen by selection), train 2025-12-15..2026-05-21 for exit-mode choice.
# Usage: bash tools/backtests/run_loss_audit_grid.sh <workers> <stage...>
#   stages (run in the order given): holdout_lock holdout_default train holdout_chandelier exit_holdout exit_train
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

# Exit audit (2026-11-27): the live exit and the pre-registered variants (exit_policy.EXIT_VARIANTS),
# same windows, every cell. Train selects per asset class x style; the holdout only confirms.
EXIT_MODES="live early_protect ratchet early_ratchet"

for stage in "$@"; do
  case $stage in
    exit_holdout) for m in $EXIT_MODES; do run "reports/exit_audit/holdout_$m" SCALP,DAY_TRADING,SWING,H4_SWING 2026-05-24 2026-11-26 "$m"; done ;;
    exit_train)   for m in $EXIT_MODES; do run "reports/exit_audit/train_$m" DAY_TRADING,SWING,H4_SWING 2025-12-15 2026-05-21 "$m"; done ;;
    holdout_lock)    run reports/loss_audit/after_holdout_institutional_lock SCALP,DAY_TRADING,SWING,H4_SWING 2026-05-24 2026-11-26 institutional_lock ;;
    holdout_default) run reports/loss_audit/after_holdout_default SCALP,DAY_TRADING,SWING,H4_SWING 2026-05-24 2026-11-26 legacy ;;
    holdout_chandelier) run reports/loss_audit/after_holdout_chandelier DAY_TRADING,SWING,H4_SWING 2026-05-24 2026-11-26 chandelier ;;
    train)
      for mode in legacy institutional_lock hold chandelier; do
        d=$mode; [ "$d" = legacy ] && d=default
        run "reports/loss_audit/after_train_$d" DAY_TRADING,SWING,H4_SWING 2025-12-15 2026-05-21 "$mode"
      done ;;
  esac
done
