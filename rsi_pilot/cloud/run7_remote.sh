#!/usr/bin/env bash
# Run 7 on a fresh Lambda A10 (CLOUD_RUN.md, RUN7_DESIGN.md). Run on the instance inside tmux:
#   bash ~/Chiron/rsi_pilot/cloud/run7_remote.sh BUILD_DEADLINE_EPOCH FINAL_DEADLINE_EPOCH [WORKERS]
# after the laptop has unpacked the working tree to ~/Chiron/rsi_pilot (with data/finqa/dev.json).
# The bank starts no harness it cannot finish by BUILD_DEADLINE. The two judge-only regrades
# start nothing they cannot finish by FINAL_DEADLINE; set that well before the ledger's cap.
# Order follows the design's stop rule: bank, then verdict regrade (H5), then judge repeat.
# Idempotent: episodes and grades are cached, so a rerun resumes. Analysis runs on the laptop.
set -euo pipefail
BUILD_DEADLINE=$1; FINAL_DEADLINE=$2; W=${3:-8}
OLLAMA_VERSION=0.40.13          # same as runs 4, 5 and 6
PORT=11435                      # own server; frozen_v7.yaml points at this port
cd ~/Chiron/rsi_pilot
OUT=runs_v7; mkdir -p $OUT/logs; L=$OUT/logs

[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION=$OLLAMA_VERSION sh
ollama --version | tee $L/ollama_version.txt

export OLLAMA_HOST=127.0.0.1:$PORT
if ! curl -fsS http://$OLLAMA_HOST/api/version >/dev/null 2>&1; then
  # keep both models resident (no reload between the student and judge phases); flash attention
  # is a faster attention kernel with the same weights
  OLLAMA_NUM_PARALLEL=$W OLLAMA_MAX_LOADED_MODELS=2 OLLAMA_KEEP_ALIVE=-1 OLLAMA_FLASH_ATTENTION=1 \
    OLLAMA_MODELS=$HOME/ollama_v7/models \
    setsid nohup ollama serve > $L/ollama_serve.log 2>&1 < /dev/null &
  for i in $(seq 30); do curl -fsS http://$OLLAMA_HOST/api/version >/dev/null 2>&1 && break; sleep 2; done
fi
ollama pull qwen2.5:7b-instruct > $L/pull_student.log 2>&1 &    # both pulls at once
ollama pull llama3.1:8b > $L/pull_judge.log 2>&1
wait
ollama list | tee $L/models.txt          # digests, for the write-up

PY=.venv/bin/python
$PY -m pytest -q tests/test_run6.py tests/test_run7.py | tee $L/pytest.log
echo "setup done $(date -u +%FT%TZ)" | tee $OUT/progress.log
$PY -m rsi.bank build --frozen frozen_v7.yaml --workers $W --deadline $BUILD_DEADLINE > $L/build.log 2>&1
echo "build done $(date -u +%FT%TZ)" | tee -a $OUT/progress.log
ollama ps | tee $L/ollama_ps.txt
$PY -m rsi.run7 verdict --workers $W --deadline $FINAL_DEADLINE > $L/verdict.log 2>&1
echo "verdict done $(date -u +%FT%TZ)" | tee -a $OUT/progress.log
$PY -m rsi.run7 repeat --workers $W --deadline $FINAL_DEADLINE > $L/repeat.log 2>&1
echo "repeat done $(date -u +%FT%TZ)" | tee -a $OUT/progress.log
echo "run7 done $(date -u +%FT%TZ)" | tee $OUT/DONE
