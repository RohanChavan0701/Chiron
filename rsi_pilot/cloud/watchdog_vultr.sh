#!/usr/bin/env bash
# On-instance cap watchdog for Vultr (CLOUD_RUN_VULTR.md, watchdog option 1), modeled on
# watchdog.sh. Destroys this instance at terminate_by even if the laptop session is gone.
# Run on the instance:
#   sudo bash watchdog_vultr.sh INSTANCE_ID TERMINATE_BY_ISO < header
# where stdin is one line "Authorization: Bearer <key>", so the key is never on a command
# line. It is stored in /root/.vultr_hdr (mode 600) and dies with the instance. Caveat as for
# Lambda: an account key sits on the instance until the destroy. Prefer a sub-user key whose
# permissions are as narrow as Vultr allows (CLOUD_RUN_VULTR.md, Watchdog options).
# Differences from watchdog.sh: DELETE /v2/instances/{id} (204, no body) instead of a POST
# with an id list; no key-prefix check (Vultr keys have no documented prefix); a 404 counts as
# done (already destroyed); and if the key is IP-restricted, the instance's IP must be on the
# allowlist or every call here fails.
set -euo pipefail
ID=$1; AT=$2
umask 077
tr -d '\r' > /root/.vultr_hdr
grep -Eq '^Authorization: Bearer [A-Za-z0-9]+$' /root/.vultr_hdr
cat > /usr/local/sbin/chiron-selfdestroy <<EOF
#!/bin/sh
# retries: a failed call must not leave the instance billing past the cap (a powered-off
# Vultr instance is still billed, so shutdown is no fallback)
for i in 1 2 3 4 5; do
  code=\$(curl -sS -o /dev/null -w '%{http_code}' -X DELETE -A chiron-rsi-pilot/0.1 \\
    -H @/root/.vultr_hdr https://api.vultr.com/v2/instances/$ID) || code=000
  case "\$code" in 204|404) exit 0 ;; esac
  sleep 60
done
exit 1
EOF
chmod 700 /usr/local/sbin/chiron-selfdestroy
WHEN="$(date -u -d "$AT" '+%F %T') UTC"
systemctl stop chiron-cap.timer 2>/dev/null || true
systemd-run --unit chiron-cap --on-calendar="$WHEN" --timer-property=AccuracySec=1s \
  /usr/local/sbin/chiron-selfdestroy
systemctl list-timers chiron-cap.timer --no-pager | head -2
