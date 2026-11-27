#!/usr/bin/env bash
# QualityBench concurrent-serving sweep on a fresh Lambda GPU instance (cloud/QB_LOAD_SWEEP.md).
# Run on the instance inside tmux, with HF_TOKEN exported in the session (the model is gated):
#   bash ~/qb_load_sweep_remote.sh CHIRON_COMMIT
# Steps: clone qualitybench main, apply the sweep commit shipped in the Chiron repo at
# CHIRON_COMMIT (cloud/qb_load_sweep.patch), build the vLLM venv, smoke (2 levels x 8
# prompts), full sweep (4 levels x 3 repeats x 2 variants), results table. Results stay in
# ~/qualitybench/results/load_sweep for rsync; this script terminates nothing. The cap timer
# armed by cloud/watchdog.sh is the only automatic termination.
set -euo pipefail
CHIRON_COMMIT=$1
[ -n "${HF_TOKEN:-}" ] || { echo "HF_TOKEN not set (mistralai/Mistral-7B-v0.1 is gated)" >&2; exit 2; }
cd ~
LOG=~/qb_sweep.log
exec > >(tee -a "$LOG") 2>&1
echo "start $(date -u +%FT%TZ) on $(hostname)"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

[ -d qualitybench ] || git clone -q https://github.com/RohanChavan0701/qualitybench.git
cd qualitybench
git fetch -q origin main && git checkout -q -B load-sweep origin/main
curl -fsSL "https://raw.githubusercontent.com/RohanChavan0701/Chiron/$CHIRON_COMMIT/rsi_pilot/cloud/qb_load_sweep.patch" -o /tmp/qb_load_sweep.patch
git -c user.name="qb-sweep" -c user.email="qb-sweep@localhost" am -q /tmp/qb_load_sweep.patch
echo "sweep commit applied: $(git rev-parse --short HEAD)"

sudo apt-get install -y -qq python3-venv tmux >/dev/null 2>&1 || true
scripts/setup_vllm_serve.sh
echo "venv ready $(date -u +%FT%TZ)"

# Smoke first: proves the server, the client flags and the parser before the long run.
scripts/run_load_sweep.sh --out results/load_sweep_smoke --repeats 1 --concurrency "1 4" --num-prompts 8
.venv-vllm-serve/bin/python analysis/load_sweep_table.py --results-dir results/load_sweep_smoke
echo "smoke done $(date -u +%FT%TZ)"

scripts/run_load_sweep.sh --out results/load_sweep --repeats 3 || echo "sweep reported failures; see results/load_sweep/FAILURES.txt"
.venv-vllm-serve/bin/python analysis/load_sweep_table.py --results-dir results/load_sweep | tee results/load_sweep/TABLE.md
cp "$LOG" results/load_sweep/remote_job.log
echo "sweep done $(date -u +%FT%TZ); results in ~/qualitybench/results/load_sweep (rsync them, then terminate)"
touch ~/QB_SWEEP_DONE
