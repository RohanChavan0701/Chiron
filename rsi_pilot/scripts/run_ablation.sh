#!/usr/bin/env bash
# Run 5 fixed-harness ablation, one seed (rsi/ablate.py, PREDICTION_schema_only.md).
# Usage: scripts/run_ablation.sh SEED [WORKERS]
# Scores the baseline harness and the variants in ablations_v5.yaml on H and B, fresh, in one
# session. No evolution, noise floor, proposer or critic: only the student server is needed,
# as in run 5 (port 11435 in the frozen file):
#   OLLAMA_HOST=127.0.0.1:11435 OLLAMA_NUM_PARALLEL=8 OLLAMA_MODELS=~/ollama2/models ollama serve
set -euo pipefail
cd "$(dirname "$0")/.."
SEED=$1; W=${2:-8}
export RSI_HARNESS_KIND=agent RSI_OLLAMA_SERVERS=${RSI_OLLAMA_SERVERS:-http://localhost:11435}
export RSI_FROZEN=frozen_v5_s$SEED.yaml RSI_SPLITS=splits_v5_s$SEED.json RSI_RUNS=runs_v5/s$SEED
PY=${PY:-.venv/bin/python}
for a in A B C; do
  [ -f "$RSI_RUNS/arm_$a/final.yaml" ] || { echo "missing $RSI_RUNS/arm_$a/final.yaml: run 5 seed $SEED not found"; exit 1; }
done
# The per-seed frozen files are committed; write one only if it is missing (same rule as run_v5.sh).
if [ ! -f "$RSI_FROZEN" ]; then
  sed -e "s/^seed: 0$/seed: $SEED/" -e "/^proposer:/,/^critic:/ s/^  seed: 0$/  seed: $SEED/" \
      frozen_v5.yaml > "$RSI_FROZEN"
fi
grep -q "^seed: $SEED$" "$RSI_FROZEN"
mkdir -p "$RSI_RUNS/logs"
L=$RSI_RUNS/logs
# Splits are not committed: regenerate from the data (H and B do not depend on the seed).
[ -f "$RSI_SPLITS" ] || $PY -m rsi.splits --out "$RSI_SPLITS" | tee $L/splits_ablation.log
$PY -m rsi.ablate check | tee $L/ablation_check.log
[ -f "$RSI_RUNS/ablation/ablation.json" ] || $PY -m rsi.ablate --workers "$W" 2>&1 | tee $L/ablation.log
echo "ablation seed $SEED done $(date -u +%FT%TZ)" >> runs_v5/ablation_progress.log
