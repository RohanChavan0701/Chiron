#!/usr/bin/env bash
# Bootstrap a run-4 A10 (CLOUD_RUN.md). Run from the laptop with agent forwarding:
#   ssh -A ubuntu@NEW bash -s BUNDLE BRANCH DATA_SRC < bootstrap.sh
# BUNDLE: git bundle of the working branch copied from the laptop (no push needed).
# DATA_SRC: user@host of an instance holding rsi_pilot/data/. The copy authenticates with the
# laptop's forwarded agent, so no key is added to DATA_SRC or left on the new instance.
set -euo pipefail
BUNDLE=$1; BRANCH=$2; SRC=$3
# Same Ollama as the A10 that started seed 20261111, default server settings (port 11434,
# no OLLAMA_NUM_PARALLEL), so the student's greedy outputs match across instances.
OLLAMA_VERSION=0.40.13

[ -d ~/Chiron ] || git clone -q -b "$BRANCH" "$BUNDLE" ~/Chiron
cd ~/Chiron/rsi_pilot
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION=$OLLAMA_VERSION sh
ollama --version
ollama pull qwen2.5:1.5b-instruct > /tmp/pull_small.log 2>&1 &
ollama pull qwen2.5:32b-instruct > /tmp/pull_big.log 2>&1 &
mkdir -p data
rsync -a -e "ssh -o StrictHostKeyChecking=accept-new" "$SRC:Chiron/rsi_pilot/data/" data/
wait
# model digests on the A10 that started seed 20261111
ollama list | grep -q 'qwen2.5:1.5b-instruct *65ec06548149' || { echo "student digest differs"; exit 1; }
ollama list | grep -q 'qwen2.5:32b-instruct *9f13ba1299af' || { echo "proposer digest differs"; exit 1; }
.venv/bin/python -m pytest -q
echo "bootstrap done $(date -u +%FT%TZ)"
