#!/usr/bin/env bash
# Run 4, one seed: splits -> critic check -> baseline (+placebo) -> arms A, B, C in parallel
# -> held-out evaluation -> audit. Usage: scripts/run_v4.sh SEED [WORKERS]
set -euo pipefail
cd "$(dirname "$0")/.."
SEED=$1; W=${2:-4}
export RSI_FROZEN=frozen_v4_s$SEED.yaml RSI_SPLITS=splits_v4_s$SEED.json RSI_RUNS=runs_v4/s$SEED
sed -e "s/^seed: 0$/seed: $SEED/" -e "/^proposer:/,/^critic:/ s/^  seed: 0$/  seed: $SEED/" \
    frozen_v4.yaml > "$RSI_FROZEN"
grep -q "^seed: $SEED$" "$RSI_FROZEN"
mkdir -p "$RSI_RUNS/logs"
L=$RSI_RUNS/logs
PY=.venv/bin/python
[ -f "$RSI_SPLITS" ] || $PY -m rsi.splits --out "$RSI_SPLITS" | tee $L/splits.log
[ -f "$RSI_RUNS/critic_check.json" ] || $PY -m rsi.critic_check > $L/critic_check.log 2>&1
[ -f "$RSI_RUNS/noise_floor.json" ] || $PY -m rsi.baseline --reps 2 --workers $W > $L/baseline.log 2>&1
pids=()
for a in A B C; do
  [ -f "$RSI_RUNS/arm_$a/final.yaml" ] || { $PY -m rsi.evolve --arm $a --workers $W > $L/evolve_$a.log 2>&1 & pids+=($!); }
done
for p in "${pids[@]}"; do wait $p; done
[ -f "$RSI_RUNS/results.json" ] || $PY -m rsi.heldout --workers $W > $L/heldout.log 2>&1
$PY -m rsi.audit --testsuite-dir data/testsuite > $L/audit.log 2>&1 || true
echo "seed $SEED done $(date -u +%FT%TZ)" >> runs_v4/progress.log
