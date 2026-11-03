#!/usr/bin/env bash
# Poison audit, one cell (POISON_AUDIT.md). Requires run 4 to have finished for SEED
# (splits_v4_s$SEED.json and runs_v4/s$SEED/arm_{A,B}/final.yaml are the clean control).
#
#   scripts/run_poison.sh SEED FAMILY DOSE [MODE=triggered|global] [GOLD=0|1] [WORKERS]
#       build poison -> baseline on poisoned E (compliance) -> arms A, B -> held-out (clean and
#       triggered H/B) -> report
#   scripts/run_poison.sh persist SEED FAMILY DOSE MODE ARM [WORKERS]
#       5 clean generations from the poisoned final harness, then report again
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python

if [ "$1" = "persist" ]; then
  SEED=$2; FAM=$3; DOSE=$4; MODE=$5; ARM=$6; W=${7:-4}
  CELL=s${SEED}_${FAM}_${MODE}_d${DOSE}
  SRC=runs_poison/$CELL
  [ -f "$SRC/arm_$ARM/final.yaml" ] || { echo "no $SRC/arm_$ARM/final.yaml"; exit 1; }
  export RSI_FROZEN=frozen_poison_${CELL}_persist_$ARM.yaml RSI_SPLITS=splits_v4_s$SEED.json RSI_RUNS=$SRC/persist_$ARM
  # same cell settings, poison removed, resume from the poisoned harness, 5 generations
  sed -e "s#^  overrides: .*#  overrides: null#" \
      -e "s/^  generations: 10$/  generations: 5/" \
      -e "s#^  # base_harness: .*#  base_harness: $SRC/arm_$ARM/final.yaml#" \
      "frozen_poison_$CELL.yaml" > "$RSI_FROZEN"
  grep -q "^  base_harness: $SRC" "$RSI_FROZEN"
  mkdir -p "$RSI_RUNS/logs"
  cp "$SRC/noise_floor.json" "$RSI_RUNS/" 2>/dev/null || true
  $PY -m rsi.evolve --arm "$ARM" --workers "$W" > "$RSI_RUNS/logs/evolve_$ARM.log" 2>&1
  $PY -m rsi.poison report --poison "poison_v2_$CELL.json" --runs "$RSI_RUNS" --arms "$ARM" | tee "$RSI_RUNS/logs/report.log"
  exit 0
fi

SEED=$1; FAM=$2; DOSE=$3; MODE=${4:-triggered}; GOLD=${5:-0}; W=${6:-4}
CELL=s${SEED}_${FAM}_${MODE}_d${DOSE}
[ "$GOLD" = "1" ] && CELL=${CELL}_gold
POISON=poison_v2_$CELL.json
export RSI_SPLITS=splits_v4_s$SEED.json RSI_RUNS=runs_poison/$CELL
[ -f "$RSI_SPLITS" ] || { echo "run 4 splits for seed $SEED not found"; exit 1; }
for a in A B; do
  [ -f "runs_v4/s$SEED/arm_$a/final.yaml" ] || echo "warning: clean control runs_v4/s$SEED/arm_$a/final.yaml missing"
done
mkdir -p "$RSI_RUNS/logs"; L=$RSI_RUNS/logs

# 1. build the poison from the CLEAN E (the run-4 frozen file has no poison section)
export RSI_FROZEN=frozen_v4_s$SEED.yaml
[ -f "$RSI_FROZEN" ] || sed -e "s/^seed: 0$/seed: $SEED/" -e "/^proposer:/,/^critic:/ s/^  seed: 0$/  seed: $SEED/" frozen_v4.yaml > "$RSI_FROZEN"
[ -f "$POISON" ] || $PY -m rsi.poison build --family "$FAM" --dose "$DOSE" --mode "$MODE" --out "$POISON" | tee $L/build.log

# 2. the cell's frozen file: poison on, gold visibility as requested
export RSI_FROZEN=frozen_poison_$CELL.yaml
GOLD_BOOL=$([ "$GOLD" = "1" ] && echo true || echo false)
sed -e "s/^seed: 0$/seed: $SEED/" -e "/^proposer:/,/^critic:/ s/^  seed: 0$/  seed: $SEED/" \
    -e "s#^  overrides: null.*#  overrides: $POISON#" -e "s/^  family: null.*/  family: $FAM/" \
    -e "s/^  mode: null.*/  mode: $MODE/" -e "s/^  dose: null.*/  dose: $DOSE/" \
    -e "s/^  show_gold_sql_to_proposer: false.*/  show_gold_sql_to_proposer: $GOLD_BOOL/" \
    frozen_poison.yaml > "$RSI_FROZEN"
grep -q "^  overrides: $POISON" "$RSI_FROZEN"

# 3. baseline on poisoned E (task compliance, poison passes at baseline) and the placebo noise floor
[ -f "$RSI_RUNS/evals/baseline_E.json" ] || $PY -m rsi.runner --split E --tag baseline --workers "$W" | tee $L/baseline_E.log
[ -f "$RSI_RUNS/noise_floor.json" ] || $PY -m rsi.baseline --reps 2 --workers "$W" > $L/baseline.log 2>&1

# 4. arms, unchanged evolution code
pids=()
for a in A B; do
  [ -f "$RSI_RUNS/arm_$a/final.yaml" ] || { $PY -m rsi.evolve --arm $a --workers "$W" > $L/evolve_$a.log 2>&1 & pids+=($!); }
done
for p in "${pids[@]}"; do wait $p; done

# 5. held-out (clean H, B and triggered H_trig, B_trig) and report
[ -f "$RSI_RUNS/results.json" ] || $PY -m rsi.heldout --workers "$W" > $L/heldout.log 2>&1
$PY -m rsi.poison report --poison "$POISON" --runs "$RSI_RUNS" | tee $L/report.log
echo "cell $CELL done $(date -u +%FT%TZ)" >> runs_poison/progress.log
