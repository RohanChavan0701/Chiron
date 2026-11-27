#!/usr/bin/env bash
# Run 5 fixed-harness ablation over the six run-5 seeds, then the seed-level report.
# Usage: scripts/run_ablation_all.sh [WORKERS]
cd "$(dirname "$0")/.."
W=${1:-8}
PY=${PY:-.venv/bin/python}
for s in 20261211 20261212 20261213 20261214 20261215 20261216; do
  scripts/run_ablation.sh $s "$W" || echo "ablation seed $s FAILED $(date -u +%FT%TZ)" >> runs_v5/ablation_progress.log
done
RSI_HARNESS_KIND=agent $PY -m rsi.ablate report runs_v5/s2026121?
echo "ablation all done $(date -u +%FT%TZ)" >> runs_v5/ablation_progress.log
