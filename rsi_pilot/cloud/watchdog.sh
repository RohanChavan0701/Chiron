#!/usr/bin/env bash
# On-instance cap watchdog (CLOUD_RUN.md, watchdog option 1). Terminates this instance at
# terminate_by even if the laptop session is gone. Run on the instance:
#   sudo bash watchdog.sh INSTANCE_ID TERMINATE_BY_ISO < header
# where stdin is one line "Authorization: Bearer <key>", so the key is never on a command
# line. It is stored in /root/.lambda_hdr (mode 600) and dies with the instance.
set -euo pipefail
ID=$1; AT=$2
umask 077
tr -d '\r' > /root/.lambda_hdr
grep -q '^Authorization: Bearer secret_' /root/.lambda_hdr
cat > /usr/local/sbin/chiron-selfterm <<EOF
#!/bin/sh
# retries: a failed call must not leave the instance billing past the cap
for i in 1 2 3 4 5; do
  curl -fsS -X POST -A chiron-rsi-pilot/0.1 -H @/root/.lambda_hdr \\
    -H 'Content-Type: application/json' -d '{"instance_ids": ["$ID"]}' \\
    https://cloud.lambda.ai/api/v1/instance-operations/terminate && exit 0
  sleep 60
done
EOF
chmod 700 /usr/local/sbin/chiron-selfterm
WHEN="$(date -u -d "$AT" '+%F %T') UTC"
systemctl stop chiron-cap.timer 2>/dev/null || true
systemd-run --unit chiron-cap --on-calendar="$WHEN" --timer-property=AccuracySec=1s \
  /usr/local/sbin/chiron-selfterm
systemctl list-timers chiron-cap.timer --no-pager | head -2
