#!/usr/bin/env bash
# Amendment 1 (2026-11-03): stop run 4 after seed 6 (20261116). Waits for that seed's
# "done" line, then stops the driver and anything it started for the next seed.
P=runs_v4/progress.log
until grep -q "seed 20261116 done" $P; do sleep 20; done
pkill -f scripts/run_v4_all.sh
sleep 2
pkill -f "scripts/run_v4.sh 20261117"
pkill -f "RSI_RUNS=runs_v4/s20261117" 2>/dev/null
for p in $(pgrep -f "python -m rsi\."); do
  grep -q "runs_v4/s20261117" /proc/$p/environ 2>/dev/null && kill $p
done
rm -rf runs_v4/s20261117 frozen_v4_s20261117.yaml splits_v4_s20261117.json
echo "stopped after seed 20261116 (amendment 1) $(date -u +%FT%TZ)" >> $P
