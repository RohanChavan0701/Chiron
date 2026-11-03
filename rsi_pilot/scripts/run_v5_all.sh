#!/usr/bin/env bash
# Run 5: 6 pre-registered seeds, one after another (PREDICTION_run5.md).
cd "$(dirname "$0")/.."
mkdir -p runs_v5
for s in 20261211 20261212 20261213 20261214 20261215 20261216; do
  scripts/run_v5.sh $s 8 || echo "seed $s FAILED $(date -u +%FT%TZ)" >> runs_v5/progress.log
done
echo "all done $(date -u +%FT%TZ)" >> runs_v5/progress.log
