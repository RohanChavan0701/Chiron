#!/usr/bin/env bash
# Run-5 fixed-harness ablation (schema-only) on a Vultr A100 (CLOUD_RUN_VULTR.md). Run on the
# instance as root inside tmux, after cloud/vultr_ablation_driver.sh has cloned the bundle to
# ~/Chiron and copied the data archive to ~/instance_chiron_backup.tar.gz:
#   bash ~/Chiron/rsi_pilot/cloud/ablation_remote.sh DEADLINE_EPOCH [WORKERS]
# Starts no seed it cannot finish by DEADLINE_EPOCH (set it well before the ledger's cap).
# Idempotent: seeds with SEED_DONE are skipped, so a rerun resumes. No accuracy numbers go to
# the progress log (no peeking mid-run); the analysis runs on the laptop.
set -uo pipefail
DEADLINE=$1; W=${2:-8}
OLLAMA_VERSION=0.40.13          # same as runs 4 to 7
PORT=11435                      # run 5's student server; frozen_v5*.yaml points at this port
MODEL=qwen2.5:7b-instruct
SEEDS="20261211 20261212 20261213 20261214 20261215 20261216"
cd ~/Chiron/rsi_pilot
OUT=runs_v5; L=$OUT/ablation_logs; P=$OUT/ablation_progress.log
mkdir -p $L
say() { echo "$(date -u +%FT%TZ) $*" | tee -a $P; }
fail() { say "FAILED: $*"; echo "$(date -u +%FT%TZ) $*" > $OUT/ABLATION_FAILED; exit 1; }
rm -f $OUT/ABLATION_FAILED $OUT/ABLATION_PARTIAL $OUT/ABLATION_DONE
say "start deadline=$(date -u -d @$DEADLINE +%FT%TZ) workers=$W"

# a. GPU: must be an A100 with a working driver; never install drivers here
nvidia-smi > $L/nvidia_smi.txt 2>&1 || fail "nvidia-smi does not work (see ablation_logs/nvidia_smi.txt)"
grep -q A100 $L/nvidia_smi.txt || fail "nvidia-smi shows no A100"

# b. data (only spider and bird_minidev are needed)
[ -d data/spider ] && [ -d data/bird_minidev ] || \
  tar xzf ~/instance_chiron_backup.tar.gz -C ~ Chiron/rsi_pilot/data > $L/untar.log 2>&1 || fail "untar failed"
[ -d data/spider ] && [ -d data/bird_minidev ] || fail "data/spider or data/bird_minidev missing"

# c. venv, Ollama (pinned), one student server like run 5's
python3 -c "import ensurepip" > /dev/null 2>&1 || \
  { apt-get update -q && DEBIAN_FRONTEND=noninteractive apt-get install -yq python3-venv; } > $L/apt.log 2>&1
[ -x .venv/bin/python ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; } \
  > $L/venv.log 2>&1 || fail "venv or pip install failed"
command -v ollama > /dev/null || { curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION=$OLLAMA_VERSION sh; } \
  > $L/ollama_install.log 2>&1 || fail "ollama install failed"
systemctl disable --now ollama > /dev/null 2>&1 || true    # the installer's 11434 service: one server only
ollama --version > $L/ollama_version.txt 2>&1
export OLLAMA_HOST=127.0.0.1:$PORT
if ! curl -fsS http://$OLLAMA_HOST/api/version > /dev/null 2>&1; then
  # run 5's student settings; no OLLAMA_FLASH_ATTENTION (run 5 did not set it)
  OLLAMA_NUM_PARALLEL=$W OLLAMA_KEEP_ALIVE=-1 setsid nohup ollama serve > $L/ollama_serve.log 2>&1 < /dev/null &
  for i in $(seq 30); do curl -fsS http://$OLLAMA_HOST/api/version > /dev/null 2>&1 && break; sleep 2; done
fi
curl -fsS http://$OLLAMA_HOST/api/version > $L/ollama_server_version.txt || fail "ollama server did not start"
ollama pull $MODEL > $L/pull_student.log 2>&1 &
PULL=$!
wait $PULL || fail "ollama pull failed"   # only the pull: a bare wait would also wait on the server
ollama list > $L/models.txt                # digest, for the write-up

# d. tests
PY=.venv/bin/python
$PY -m pytest -q tests/test_ablate.py tests/test_agent.py > $L/pytest.log 2>&1 || fail "pytest failed (ablation_logs/pytest.log)"
say "setup done"

# e. seeds
gpu_check() {   # after the model is loaded by a seed's first evaluation: 100% GPU or stop
  local S=$1 PID=$2
  for i in $(seq 240); do
    ollama ps > $L/ollama_ps_s$S.txt 2>&1
    grep -q "^$MODEL" $L/ollama_ps_s$S.txt && break
    kill -0 $PID 2> /dev/null || return 0
    sleep 5
  done
  grep "^$MODEL" $L/ollama_ps_s$S.txt | grep -q "100% GPU" && return 0
  kill -- -$PID 2> /dev/null      # the seed's whole process group (setsid below)
  fail "model not 100% on GPU (ablation_logs/ollama_ps_s$S.txt); partial CPU placement changed outputs in run 4"
}
run_seed() {    # one attempt; 0 when ablation.json exists afterwards
  local S=$1
  setsid bash scripts/run_ablation.sh $S $W > $L/seed_$S.log 2>&1 < /dev/null &
  local PID=$!
  gpu_check $S $PID
  wait $PID && [ -f $OUT/s$S/ablation/ablation.json ]
}
# SLOWEST: the slowest finished seed's duration, 45 min until one has finished
SLOWEST=$((45 * 60)); HAVE=""; DONE_L=""; FAIL_L=""; STOPPED=""
for S in $SEEDS; do
  if [ -f $OUT/s$S/ablation/SEED_DONE ]; then   # finished in an earlier session: reuse its duration
    DONE_L="$DONE_L $S"; DT=$(awk '{print $3}' $OUT/s$S/ablation/SEED_DONE)
    [ -n "$DT" ] && { [ -z "$HAVE" ] || [ $DT -gt $SLOWEST ]; } && { SLOWEST=$DT; HAVE=1; }
    continue
  fi
  if [ $(( $(date +%s) + SLOWEST )) -gt $DEADLINE ]; then
    STOPPED=1; say "stop before seed $S: $SLOWEST s would pass the deadline"; break
  fi
  T0=$(date +%s); say "seed $S start"
  ok=""
  for attempt in 1 2; do
    if run_seed $S; then ok=1; break; fi
    say "seed $S attempt $attempt failed"
    # remove only an incomplete ablation dir, never a finished one
    [ -d $OUT/s$S/ablation ] && [ ! -f $OUT/s$S/ablation/ablation.json ] && rm -rf $OUT/s$S/ablation
  done
  DT=$(( $(date +%s) - T0 ))
  if [ -n "$ok" ]; then
    echo "$(date -u +%FT%TZ) duration_s $DT" > $OUT/s$S/ablation/SEED_DONE
    DONE_L="$DONE_L $S"
    if [ -z "$HAVE" ] || [ $DT -gt $SLOWEST ]; then SLOWEST=$DT; fi; HAVE=1
    say "seed $S done in $DT s"
  else
    FAIL_L="$FAIL_L $S"; say "seed $S failed twice after $DT s"
  fi
done

# f. end marker: finished and failed seeds only, no accuracy numbers
M=ABLATION_DONE; [ -n "$STOPPED" ] && M=ABLATION_PARTIAL
printf 'finished:%s\nfailed:%s\ntime: %s\n' "$DONE_L" "$FAIL_L" "$(date -u +%FT%TZ)" > $OUT/$M
say "$M finished:${DONE_L:- none} failed:${FAIL_L:- none}"
