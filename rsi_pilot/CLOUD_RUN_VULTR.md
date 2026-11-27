Status: draft. Guardrail numbers below are placeholders until the author sets them.

# Vultr instance runbook (draft)

Counterpart of `CLOUD_RUN.md` (Lambda) for one Vultr Cloud GPU instance. The Lambda runbook,
client and ledger are unchanged. Client: `rsi_pilot/cloud/vultr_api.py`, run from `rsi_pilot/`
as `python -m cloud.vultr_api plans|keys|balance|launch|status|destroy|check` (its docstring
has the full usage). Guardrail tests: `tests/test_vultr.py` (offline, fake transport). No call
to the Vultr API has been made by the client yet. The facts below come from public pages and
from one read-only look at the owner's account by the main session.

## API findings (read 2026-11-27)

Verified by a live API read (source: live API read by the main session, 2026-11-27, read-only):

- `GET /plans?type=vcg` returns only 3 plans, all L40S (e.g. `vcg-l40s-16c-180g-48vram` at
  $1.671/h), each with an empty `locations` list.
- The A100, A40 and A16 Cloud GPU plans appear only under `GET /plans?type=all` (139 plans in
  one page at `per_page=500`), with `type: "vdm"` and empty `gpu_type` and `gpu_vram_gb`. Seen:
  `vcg-a100-12c-120g-80vram` $2.397/h ($1750/month, 12 vCPU, 122880 MB RAM, 1400 GB disk),
  `vcg-a40-24c-120g-48vram` $1.712/h, `vcg-a16-6c-60g-16vram` $0.471/h,
  `vcg-a16-12c-120g-32vram` $0.942/h. So the client lists `type=all` merged with `type=vcg` and
  keeps ids starting `vcg-`; it never relies on the gpu fields.
- Regional availability does not come from a plan's `locations`. It comes from
  `GET /regions/{region-id}/availability` with no type filter (with `?type=vcg` it returned
  nothing useful), whose `available_plans` is a list of plan id strings. On 2026-11-27
  `vcg-a100-12c-120g-80vram` was available only in `ewr`; `vcg-a40-24c-120g-48vram` in `lax`
  and `lhr`. The client checks this endpoint at every launch.
- `GET /account` returns `{"account": {"balance": -250, "pending_charges": 0, "acls": [...]}}`.
  Negative means credit, per live read.

Verified against the API reference, https://www.vultr.com/api/ (where the live read above
differs, the live read wins):

- Base URL `https://api.vultr.com/v2`; auth header `Authorization: Bearer <key>`.
- `GET /plans?type=vcg` lists Cloud GPU plans (`vcg` = "Cloud GPU" in the type filter).
  Paged with `per_page` (max 500) and `cursor`, next cursor in `meta.links.next`. Plan fields in
  the sample: `id`, `vcpu_count`, `ram`, `disk`, `bandwidth`, `monthly_cost`, `hourly_cost`
  (dollars), `type`, `locations`, `location_cost.{region}.hourly_cost`, `gpu_brand`. The docs say
  not to parse plan ids (the client only checks the `vcg-` prefix, which the live listing bears
  out).
- `GET /regions/{region-id}/availability` lists plans available in one region.
- `POST /instances` (202): required `region`, `plan`; image by one of `os_id` (integer),
  `image_id` (marketplace app), `snapshot_id`, `iso_id`, `app_id`; optional `sshkey_id` (array of
  SSH key ids, not names), `label`, `hostname`, `tags` (array; `tag` is deprecated), `backups`,
  `user_data` (base64 encoded). Response `instance` with `id`, `status` (`pending` at create),
  `power_status`, `server_status`, `main_ip` (`0.0.0.0` until assigned), `date_created`.
- `GET /instances` (filters incl. `label`, `region`), `GET /instances/{instance-id}` (same
  `instance` object; sample statuses `pending`, `active`).
- `DELETE /instances/{instance-id}` answers 204 No Content. `POST /instances/{id}/halt` (204)
  powers off only.
- `GET /ssh-keys` returns `ssh_keys` (each `id`, `name`, `date_created`, `ssh_key`), paged.
- `GET /account`: `balance`, `pending_charges`, `last_payment_date`, `last_payment_amount`
  (sample `balance: -100.55`).
- Users have their own API keys and ACLs (`subscriptions`, `provisioning`, `billing`, ...;
  `service_user` for API-only users), and `/users/{user-id}/ip-whitelist` manages a per-user IP
  allowlist, so IP restriction exists.

Billing, verified on Vultr's support docs (updated 2026-10-26):

- https://docs.vultr.com/support/platform/billing/are-stopped-instances-still-billed-on-vultr :
  a stopped instance is billed until it is destroyed.
- https://docs.vultr.com/support/platform/billing/how-am-i-billed-for-my-servers : hourly,
  minimum billing unit one hour, charges run from deploy whether powered on or off; GPU plans
  bill up to 730 hours a month. So, as on Lambda, only the destroy call stops billing.

Verify before first use:

- The `GET /regions` response shape (`regions`, each with `id`): used only by `plans` without
  `--region`, not by launch.
- Whether a partial hour is billed as a full hour (the docs only say "minimum billing unit is one
  hour"). The client assumes the worst: whole hours only, every started hour billed.
- Credit expiry is not in the API docs; read it from the console.
- Instance label length limit (the client keeps Lambda's 64).
- The `os_id` (or `image_id`) of an Ubuntu image with NVIDIA drivers for the chosen GPU plan:
  `GET /os` and the console's GPU image list.
- The format of a Vultr key (the watchdog checks only `[A-Za-z0-9]+`), and the console path
  for restricting a key by IP.
- Which sub-user ACL allows deleting an instance (for a narrower watchdog key).

GPU plans with 24 GB or more, as of 2026-11-27. The client re-reads the price at every launch;
these figures are for planning only.

| Plan id | GPU | Hourly | Source |
| --- | --- | --- | --- |
| `vcg-a100-12c-120g-80vram` | A100 80 GB | $2.397 (ewr only) | live read, 2026-11-27 |
| `vcg-a40-24c-120g-48vram` | A40 48 GB | $1.712 (lax, lhr) | live read, 2026-11-27 |
| `vcg-l40s-16c-180g-48vram` | L40S 48 GB | $1.671 (no region seen) | live read; https://www.vultr.com/pricing |
| `vbm-72c-480gb-gh200-gpu` | GH200 96 GB, bare metal | $1.99 | https://compute.fru.dev/providers/vultr (bare metal, not supported by this client) |

## Guardrails (the code enforces these; blanks are the author's)

- **Plan:** `vcg-a100-12c-120g-80vram`, named by the author in chat on 2026-11-27 ("lets use
  a100"). It is the only entry in `PLAN_ALLOWLIST`, so launch refuses every other plan. At launch
  the plan must also be among the live `vcg-` plans, and in the region's `available_plans` (today
  that means `ewr` only).
- **Region:** `ewr` (set by the author in chat on 2026-11-27).
- **Per-launch dollar cap:** $30 for the schema-only ablation launch, raised from $20 by the
  author in chat on 2026-11-27 ("keep a100 ... finish the job in 5 hours and have the 30 usd
  cap"); the job deadline is 5 hours after launch; one launch approved. `--budget-usd` is required on every launch
  and must be within the ceiling (`MAX_BUDGET_USD = 20`, still the code placeholder for later
  launches). At $2.397/h the cap is 7.9 h.
- **Max hours:** ______ (placeholder `MAX_HOURS = 24`; not binding at $20 on the A100).
- **Cap arithmetic:** cap hours = min(MAX_HOURS, floor(budget cents / live cents per hour)) -
  0.1 h, with the price read from the plans API at launch (the higher of `hourly_cost` and the
  region's `location_cost`), never a remembered price. Refuses if the budget buys under one hour.
  Example for the A100 at $2.397/h: a $10 budget buys 4 whole hours, so the cap is 3.9 h; the
  $20 ceiling gives 7.9 h.
  Choice: whole hours and a 6-minute margin, because Vultr bills a minimum of one hour; the
  plain formula (budget / price) could overrun by up to one hour's price, at the cost of up to
  one hour of runtime.
- **One instance at a time** (`MAX_OPEN = 1`): launch refuses while the ledger shows any launch
  without a terminate line.
- **Label prefix `chiron-`** (64 chars max); `--approved-by` (the author's message or date) is
  required and recorded on the launch line.
- **Destroy only what this ledger launched**, by instance id. `check` destroys any open
  instance past `terminate_by` or past its budget.
- **Credit balance and expiry:** $______ , expires ______ (read in the console; `balance`
  shows the API's view).
- The key never appears in chat, logs, commits, argv, the ledger or exception text.

## Key storage

- Preferred on the laptop: `%USERPROFILE%\.vultr_key`, a Windows DPAPI string readable only by
  the same Windows user. Create it in PowerShell, typing the key at the masked prompt:

  ```powershell
  Read-Host -AsSecureString -Prompt "Vultr API key" | ConvertFrom-SecureString | Set-Content -NoNewline -Encoding ascii "$env:USERPROFILE\.vultr_key"
  ```

  `vultr_api.load_key` decrypts it per request with `CryptUnprotectData` and keeps the
  plaintext in memory only. `VULTR_API_KEY` in the environment, if set, takes precedence (the
  only option off Windows).
- Never paste the key into chat, a log, a commit, a command line (argv is visible to other
  processes) or a repo file.
- Restrict the key by IP: the API docs confirm a per-user IP allowlist
  (`/users/{user-id}/ip-whitelist`). Add the laptop's address. This conflicts with the
  on-instance watchdog (below) unless the instance's IP is added for its lifetime.

## Ledger (`rsi_pilot/cloud/ledger_vultr.jsonl`, committed, created by the first event)

Same event shapes as `ledger.jsonl`, each line with `"provider": "vultr"`:

- `register_key`: id, name, key_type, time (never key material)
- `launch`: id, name (label), type (plan id), region, price_cents_per_hour, launched_at (UTC,
  taken before the create call), terminate_by, cap_hours, budget_usd, os_id / image_id,
  approved_by_author. The create response's `default_password` (root password) is dropped
  before anything is printed or written.
- `check`: time, status, power_status, server_status, ip, hours_elapsed, est_spend_usd,
  job_state, past_cap
- `terminate`: time, reason (`job_done` | `cap` | `error` | `author`), est_spend_usd

Estimated spend = every started hour since launch x launch price (minimum one hour). If an
instance is destroyed in the console, add its `terminate` line by hand, or launch stays refused.

## Watchdog options (the cap must not depend on the laptop)

As in `CLOUD_RUN.md`; the author picks one before the first launch:

1. **On-instance self-destroy:** `cloud/watchdog_vultr.sh ID TERMINATE_BY < header`, a
   systemd timer that calls `DELETE /instances/{id}` at `terminate_by` with retries. Risk: a key
   on the instance. Narrow it with a sub-user key, and note that an IP-restricted key needs the
   instance IP allowed. A shutdown is no fallback: a stopped instance is still billed.
2. **Cloud scheduled task** at `terminate_by` running `check` (needs `api.vultr.com` reachable
   and the key as a secret there).
3. **Laptop only, kept awake**, running `python -m cloud.vultr_api check` on a schedule. Weakest.

Whichever is chosen, the local session runs `check` on every wake.

**Decision for the ablation run (2026-11-27): option 3, laptop only.** No API key is ever
copied to the instance, so `cloud/watchdog_vultr.sh` is unused for this run and wired into
nothing: the account key has root ACLs (it could delete or create anything on the account), and
a key on the instance is the larger risk. The cap is enforced by `vultr_ablation_driver.sh`,
which runs `check` every 300 s. Residual risk: if the laptop sleeps, loses network or the
driver dies, nothing destroys the instance and it bills ($2.397/h) until someone runs `check`
or `destroy` (or deletes it in the console). Keep the laptop awake and plugged in.

## Ablation run: live command sequence (Git Bash, from `rsi_pilot/`)

Approved by the author in chat on 2026-11-27: register the laptop's public key, one launch of
`vcg-a100-12c-120g-80vram` in `ewr` with a $20 cap, push the branch. First commit everything
the run uses: the driver refuses uncommitted changes, because the instance gets a bundle of
HEAD only. Live facts (main session, 2026-11-27): no SSH keys and no instances on the account;
os id 1743 = Ubuntu 22.04 LTS x64, 2284 = Ubuntu 24.04 LTS x64; Vultr logs in as root.

```bash
PY=.venv/Scripts/python.exe
$PY -m cloud.vultr_api register-key --name chiron-laptop --pubkey-file ~/.ssh/id_ed25519.pub
$PY -m cloud.vultr_api launch --label chiron-ablation --plan vcg-a100-12c-120g-80vram --region ewr \
    --ssh-key chiron-laptop --os-id 1743 --budget-usd 20 \
    --approved-by 'author, 2026-11-27 chat: one A100 launch in ewr for the schema-only ablation, "use $20 cap"'
ID=$($PY -c "import json; print([json.loads(l) for l in open('cloud/ledger_vultr.jsonl')][-1]['id'])")
IP=$($PY -m cloud.vultr_api wait-active "$ID" --timeout-s 1200 | head -n1)
# stop starting seeds 30 min before the cap, leaving time for the final fetch
DEADLINE=$($PY -c "import json, datetime as d; r=[json.loads(l) for l in open('cloud/ledger_vultr.jsonl')]; l=[x for x in r if x['event']=='launch' and x['id']=='$ID'][-1]; print(int(d.datetime.fromisoformat(l['terminate_by']).timestamp()) - 1800)")
bash cloud/vultr_ablation_driver.sh "$ID" "$IP" "$DEADLINE" 8
```

`cloud/ablation_remote.sh` (on the instance, in tmux) checks `nvidia-smi` for an A100, unpacks
`data/`, sets up the venv, Ollama 0.40.13 with one student server on 11435
(`OLLAMA_NUM_PARALLEL=8 OLLAMA_KEEP_ALIVE=-1`, no flash attention, as run 5; the installer's
11434 service is disabled), runs `tests/test_ablate.py tests/test_agent.py`, then seeds 20261211
to 20261216 via `scripts/run_ablation.sh`, never starting one that cannot finish by DEADLINE. It
requires `ollama ps` to show the model 100% on GPU and stops otherwise. Markers in `runs_v5/`:
`ABLATION_DONE`, `ABLATION_PARTIAL` or `ABLATION_FAILED`; `s<SEED>/ablation/SEED_DONE` per seed.
The driver exits 0 (DONE), 2 (PARTIAL), 1 (FAILED), 3 (destroyed by `check` at the cap). If it
dies, rerun the same command: it resumes. If the laptop must stop, run
`$PY -m cloud.vultr_api destroy "$ID" --reason author` first.

## Bootstrap differences from Lambda

- Image: Lambda's image ships NVIDIA drivers. For the ablation the main session chose the plain
  Ubuntu 22.04 image (`os_id` 1743); whether it has a working NVIDIA driver for the A100 is not
  verified, so `ablation_remote.sh` checks `nvidia-smi` first and fails fast (costs the one
  billed hour) rather than installing drivers.
- Ollama pinned to 0.40.13, default server settings, same model digests, as in
  `cloud/bootstrap.sh` (its `OLLAMA_VERSION` install line and digest checks carry over).
- Data: no Lambda filesystem. The driver copies the laptop backup
  `C:\Users\Rohan\Desktop\Chiron_backup_2026-11-03\instance_chiron_backup.tar.gz` (1880 MB) by
  scp, skipping it when the remote size matches; only `Chiron/rsi_pilot/data/...` members are
  extracted. The laptop has no rsync, so results come back as `ssh ... tar czf - | tar xzf -`.
- Login user is root (live fact); the scripts use `~`.
- Code: git bundle of the current branch's HEAD, made in a temp dir outside the repo.

## Hardware note

Run 5 ran on a Lambda 1x A10 (24 GB). A Vultr GPU is different hardware (and may differ in
driver and CUDA versions), so greedy outputs can change. Only same-session paired comparisons
(all arms on the same instance in the same session) are valid; do not compare Vultr numbers
against run-5 numbers directly.
