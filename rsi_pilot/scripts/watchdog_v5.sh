#!/usr/bin/env bash
# Overnight safety for run 5:
# 1. Restart the student's Ollama server (port 11435) if it stops answering.
# 2. When run_v5_all.sh finishes, rerun any seed that FAILED once, from scratch
#    (pre-registered rule: crashed seeds are rerun with the same seed; the crashed
#    attempt is kept as runs_v5/s<seed>_crash1).
# 3. Write the pre-registered seed-level analysis to runs_v5/seed_level.md.
cd "$(dirname "$0")/.."
P=runs_v5/progress.log
log() { echo "[watchdog $(date -u +%FT%TZ)] $*" >> runs_v5/watchdog.log; }
serve2() {
  OLLAMA_HOST=127.0.0.1:11435 OLLAMA_NUM_PARALLEL=8 OLLAMA_MODELS=/home/ubuntu/ollama2/models \
  OLLAMA_KEEP_ALIVE=30m setsid nohup ollama serve >> /home/ubuntu/ollama2/serve.log 2>&1 &
}
check_server() {
  if ! curl -s -m 10 http://127.0.0.1:11435/api/version > /dev/null; then
    sleep 15
    if ! curl -s -m 10 http://127.0.0.1:11435/api/version > /dev/null; then
      log "student server down; restarting"; serve2; sleep 10
    fi
  fi
}
log "started"
until grep -q "^all done" $P; do check_server; sleep 60; done
for s in $(grep -o "seed [0-9]* FAILED" $P | awk '{print $2}' | sort -u); do
  log "rerunning crashed seed $s"
  mv runs_v5/s$s runs_v5/s${s}_crash1
  check_server
  scripts/run_v5.sh $s 8 || echo "seed $s FAILED AGAIN $(date -u +%FT%TZ)" >> $P
done
dirs=$(ls -d runs_v5/s2026121? 2>/dev/null | while read d; do [ -f $d/results.json ] && echo $d; done)
RSI_HARNESS_KIND=agent .venv/bin/python -m rsi.pool $dirs --seed-level --out runs_v5/seed_level.md >> runs_v5/watchdog.log 2>&1
log "finished; analysis in runs_v5/seed_level.md"
echo "analysis written $(date -u +%FT%TZ)" >> $P
