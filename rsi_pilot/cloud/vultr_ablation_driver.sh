#!/usr/bin/env bash
# Laptop side of the Vultr ablation run (CLOUD_RUN_VULTR.md). Git Bash, from rsi_pilot/:
#   bash cloud/vultr_ablation_driver.sh INSTANCE_ID IP DEADLINE_EPOCH [WORKERS]
# a. setup over ssh (bundle of HEAD, data archive, clone, tmux running cloud/ablation_remote.sh);
# b. every 300 s: `cloud.vultr_api check` (destroys at the cap or budget), then fetch every
#    finished seed; c. on the end marker: fetch everything, verify, destroy.
# The cap is enforced from here only: no API key is ever copied to the instance. Resumable: a
# rerun skips setup done remotely and seeds already fetched. Prints no accuracy numbers.
# Exit: 0 DONE, 2 PARTIAL, 1 FAILED (or setup error), 3 destroyed by check at the cap.
set -uo pipefail
ID=$1; IP=$2; DEADLINE=$3; W=${4:-8}
PY=.venv/Scripts/python.exe
ARCHIVE=${ARCHIVE:-/c/Users/Rohan/Desktop/Chiron_backup_2026-11-03/instance_chiron_backup.tar.gz}
SEEDS="20261211 20261212 20261213 20261214 20261215 20261216"
SSH_OPTS=(-i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 -o ServerAliveInterval=30)
R=root@$IP; RR='~/Chiron/rsi_pilot'
rssh() { ssh "${SSH_OPTS[@]}" "$R" "$@"; }
log() { echo "$(date -u +%FT%TZ) $*"; }
die() { log "ERROR: $*"; exit 1; }
[ -f cloud/vultr_api.py ] && [ -x "$PY" ] || die "run from rsi_pilot/ with .venv present"
[ -f "$ARCHIVE" ] || die "data archive not found: $ARCHIVE"

# --- a. setup (skipped when the remote marker exists) -----------------------------------
# The instance gets HEAD only, so everything the run needs must be committed.
git diff --quiet HEAD -- cloud scripts rsi tests ablations_v5.yaml frozen_v5*.yaml requirements.txt \
  || die "uncommitted changes in files the run uses; commit them first (the bundle carries HEAD only)"
git cat-file -e HEAD:rsi_pilot/cloud/ablation_remote.sh 2> /dev/null || die "cloud/ablation_remote.sh is not committed"
for i in $(seq 60); do rssh true 2> /dev/null && break; [ $i -eq 60 ] && die "no ssh after 10 min"; sleep 10; done
if ! rssh '[ -f ~/.chiron_setup_done ]'; then
  BR=$(git rev-parse --abbrev-ref HEAD)
  TMP=$(mktemp -d)                                  # outside the repo
  git bundle create "$TMP/chiron.bundle" "$BR" 2> /dev/null || die "git bundle failed"
  scp "${SSH_OPTS[@]}" "$TMP/chiron.bundle" "$R:chiron.bundle" || die "bundle upload failed"
  rm -rf "$TMP"
  LSZ=$(stat -c %s "$ARCHIVE"); RSZ=$(rssh 'stat -c %s ~/instance_chiron_backup.tar.gz 2> /dev/null' || true)
  if [ "$LSZ" != "$RSZ" ]; then
    log "uploading data archive ($((LSZ / 1048576)) MB)"
    scp "${SSH_OPTS[@]}" "$ARCHIVE" "$R:instance_chiron_backup.tar.gz" || die "archive upload failed"
  fi
  rssh "set -e; export DEBIAN_FRONTEND=noninteractive
    command -v git > /dev/null && command -v tmux > /dev/null || { apt-get update -q && apt-get install -yq git tmux; } > /dev/null
    [ -d ~/Chiron ] || git clone -q -b '$BR' ~/chiron.bundle ~/Chiron
    git -C ~/Chiron checkout -q '$BR'
    touch ~/.chiron_setup_done" || die "remote clone or tmux install failed"
  log "setup done (branch $BR)"
fi
rssh "[ -f ~/.chiron_started ] || { tmux new -d -s chiron 'bash ~/Chiron/rsi_pilot/cloud/ablation_remote.sh $DEADLINE $W' && touch ~/.chiron_started; }" \
  || die "could not start tmux session"

# --- b. poll ------------------------------------------------------------------------------
fetch() {   # copy the given rsi_pilot-relative paths back, skipping ones that do not exist
  rssh "cd $RR && tar czf - \$(for p in $*; do [ -e \$p ] && echo \$p; done)" | tar xzf - -C .
}
seed_paths() { echo "runs_v5/s$1/ablation runs_v5/s$1/heldout_access.jsonl runs_v5/s$1/logs splits_v5_s$1.json"; }
fetched() { [ -f runs_v5/s$1/ablation/SEED_DONE ] && [ -f runs_v5/s$1/ablation/ablation.json ]; }
LAST=""; SSHFAIL=0; MISSING_TRIES=0
while true; do
  OUT=$($PY -m cloud.vultr_api check "$ID" --job-state "${LAST:-unknown}" 2>&1)
  if echo "$OUT" | grep -q '"event": "terminate"'; then log "destroyed by check at the cap or budget"; exit 3; fi
  echo "$OUT" | grep -q '"event": "check"' || log "check failed: $(echo "$OUT" | tail -n1)"
  STATE=$(rssh "cd $RR && tail -n1 runs_v5/ablation_progress.log 2> /dev/null
    for m in ABLATION_DONE ABLATION_PARTIAL ABLATION_FAILED; do [ -f runs_v5/\$m ] && echo MARK \$m; done
    for s in $SEEDS; do [ -f runs_v5/s\$s/ablation/SEED_DONE ] && echo SEED \$s; done") \
    || { SSHFAIL=$((SSHFAIL + 1)); STATE=""; }
  [ -n "$STATE" ] && LAST=$(echo "$STATE" | grep -v '^MARK \|^SEED ' | tail -n1 | tr -d '"')
  DONE_SEEDS=$(echo "$STATE" | sed -n 's/^SEED //p')
  for s in $DONE_SEEDS; do fetched $s || fetch $(seed_paths $s) || SSHFAIL=$((SSHFAIL + 1)); done
  N=0; for s in $SEEDS; do fetched $s && N=$((N + 1)); done
  log "fetched $N/6 ssh_failures $SSHFAIL state: ${LAST:-unknown}"
  MARK=$(echo "$STATE" | sed -n 's/^MARK //p' | head -n1)
  if [ -n "$MARK" ]; then
    # --- c. end: fetch everything, verify, then destroy ---------------------------------
    fetch runs_v5/ablation_logs runs_v5/ablation_progress.log runs_v5/$MARK || SSHFAIL=$((SSHFAIL + 1))
    MISS=""; for s in $DONE_SEEDS; do fetched $s || MISS="$MISS $s"; done
    # Finished seeds are paid-for results: keep retrying the fetch until the cap (check above
    # destroys there) instead of destroying with data still on the instance.
    if [ -n "$MISS" ]; then
      MISSING_TRIES=$((MISSING_TRIES + 1)); log "not yet fetched:$MISS (try $MISSING_TRIES)"; sleep 120; continue
    fi
    REASON=job_done; RC=0
    [ "$MARK" = ABLATION_PARTIAL ] && RC=2
    [ "$MARK" = ABLATION_FAILED ] && { REASON=error; RC=1; }
    [ -n "$MISS" ] && { log "WARNING: destroying with seeds not fetched:$MISS"; REASON=error; RC=1; }
    $PY -m cloud.vultr_api destroy "$ID" --reason $REASON > /dev/null || die "destroy failed: destroy $ID by hand now"
    log "$MARK: fetched $N seed(s), instance $ID destroyed ($REASON)"
    exit $RC
  fi
  sleep 300
done
