#!/usr/bin/env bash
# Run 6 stage 0 on a Lambda A10 (CLOUD_RUN.md, RUN6_DESIGN.md). Run on the instance inside tmux:
#   bash ~/Chiron/rsi_pilot/cloud/stage0_remote.sh DEADLINE_EPOCH [WORKERS]
# after the laptop has unpacked the working tree to ~/Chiron/rsi_pilot (with data/finqa/dev.json).
# DEADLINE_EPOCH: unix time of the ledger's terminate_by. The judge check starts only if the
# headroom timing projects it to finish before then (budget gate).
# Idempotent: episodes and grades are cached, so a rerun resumes.
set -euo pipefail
DEADLINE=$1; W=${2:-6}
OLLAMA_VERSION=0.40.13          # same as runs 4 and 5
PORT=11435                      # own server, so parallel slots are set here and nowhere else
cd ~/Chiron/rsi_pilot
OUT=runs_v6/stage0; mkdir -p $OUT/logs; L=$OUT/logs

[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION=$OLLAMA_VERSION sh
ollama --version | tee $L/ollama_version.txt

export OLLAMA_HOST=127.0.0.1:$PORT
if ! curl -fsS http://$OLLAMA_HOST/api/version >/dev/null 2>&1; then
  OLLAMA_NUM_PARALLEL=$W OLLAMA_MAX_LOADED_MODELS=2 OLLAMA_MODELS=$HOME/ollama_v6/models \
    nohup ollama serve > $L/ollama_serve.log 2>&1 &
  for i in $(seq 30); do curl -fsS http://$OLLAMA_HOST/api/version >/dev/null 2>&1 && break; sleep 2; done
fi
ollama pull qwen2.5:7b-instruct > $L/pull_student.log 2>&1
ollama pull llama3.1:8b > $L/pull_judge.log 2>&1
ollama list | tee $L/models.txt          # digests, for the write-up

.venv/bin/python -m pytest -q tests/test_run6.py | tee $L/pytest.log
sed "s#http://localhost:11434#http://localhost:$PORT#" frozen_v6_stage0.yaml > frozen_v6_stage0_cloud.yaml
PY=".venv/bin/python -m rsi.stage0 --frozen frozen_v6_stage0_cloud.yaml --workers $W"

T0=$(date +%s)
$PY headroom > $L/headroom.log 2>&1
T1=$(date +%s)
# headroom = 3 baseline evaluations; judgecheck adds 25 edit evaluations (baselines are cached)
PROJ=$(( (T1 - T0) * 25 / 3 ))
echo "{\"headroom_seconds\": $((T1 - T0)), \"judgecheck_projected_seconds\": $PROJ, \"seconds_to_deadline\": $((DEADLINE - T1))}" | tee $OUT/timing.json
if [ $((T1 + PROJ + 900)) -gt "$DEADLINE" ]; then
  echo "judgecheck would not finish before the cap; stopping after headroom" | tee $OUT/STOPPED
  exit 3
fi
$PY judgecheck > $L/judgecheck.log 2>&1
$PY power > $L/power.log 2>&1
echo "stage0 done $(date -u +%FT%TZ)" | tee $OUT/DONE
