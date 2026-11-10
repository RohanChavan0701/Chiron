#!/usr/bin/env bash
# Run 6 stage 0b + stage 1 on the instance that ran stage 0 (models already pulled):
#   bash ~/Chiron/rsi_pilot/cloud/stage1_remote.sh BUILD_DEADLINE_EPOCH [WORKERS]
# The bank stops starting new harnesses at BUILD_DEADLINE_EPOCH; set it well before the cap.
set -euo pipefail
DEADLINE=$1; W=${2:-6}
PORT=11435
cd ~/Chiron/rsi_pilot
mkdir -p runs_v6/stage1/logs; L=runs_v6/stage1/logs
export OLLAMA_HOST=127.0.0.1:$PORT
# small models only from here on: W slots each, both loaded, nothing on the CPU
pkill -u "$USER" -f "[o]llama serve" || true
sleep 3
OLLAMA_NUM_PARALLEL=$W OLLAMA_MAX_LOADED_MODELS=2 OLLAMA_MODELS=$HOME/ollama_v6/models \
  setsid nohup ollama serve > $L/ollama_serve.log 2>&1 < /dev/null &
for i in $(seq 30); do curl -fsS http://$OLLAMA_HOST/api/version >/dev/null 2>&1 && break; sleep 2; done
.venv/bin/python -m pytest -q tests/test_run6.py | tee $L/pytest.log
for f in frozen_v6_stage0b frozen_v6_stage1; do
  sed "s#http://localhost:11434#http://localhost:$PORT#" $f.yaml > ${f}_cloud.yaml
done
PY=.venv/bin/python
$PY -m rsi.stage0 judgecheck --frozen frozen_v6_stage0b_cloud.yaml --workers $W --tag recompute > $L/judgecheck_recompute.log 2>&1
echo "regrade done $(date -u +%FT%TZ)" | tee runs_v6/stage1/progress.log
$PY -m rsi.bank anchor --frozen frozen_v6_stage1_cloud.yaml --workers $W > $L/anchor.log 2>&1
echo "anchor done $(date -u +%FT%TZ)" | tee -a runs_v6/stage1/progress.log
ollama ps | tee $L/ollama_ps.txt
$PY -m rsi.bank build --frozen frozen_v6_stage1_cloud.yaml --workers $W --deadline $DEADLINE > $L/build.log 2>&1
echo "build done $(date -u +%FT%TZ)" | tee -a runs_v6/stage1/progress.log
$PY -m rsi.bank analyze --frozen frozen_v6_stage1_cloud.yaml > $L/analyze.log 2>&1
echo "stage1 done $(date -u +%FT%TZ)" | tee runs_v6/stage1/DONE
