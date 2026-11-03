# Lambda instance runbook (for a local Claude Code session)

Read with `docs/DEV_PLAN.md`, which says what to run and when. This file says how to run it on a
Lambda A10 without exceeding the author's limits. Lambda API details marked **verify** were not
checked against Lambda's docs when this was written; check them before the first call.

## API findings (verified 2026-11-02 against Lambda's OpenAPI spec 1.10.0, docs.lambda.ai/api/cloud)

- Base URL `https://cloud.lambda.ai/api/v1` (`cloud.lambdalabs.com` still served, deprecated).
  Auth: `Authorization: Bearer <key>` preferred; basic auth with the key as user also accepted.
- `GET /instance-types` returns `data` keyed by type name; each item has
  `instance_type.price_cents_per_hour`, `instance_type.gpu_description`, `instance_type.specs.gpus`
  and `regions_with_capacity_available` (list of `{name, description}`).
- `POST /instance-operations/launch`: required `region_name`, `instance_type_name`,
  `ssh_key_names` (exactly one key). Optional: `name` (64 chars max), `file_system_names`,
  `file_system_mounts`, `user_data` (cloud-init, so a startup script is accepted), `image`,
  `hostname`, `tags`, `firewall_rulesets`. Returns `data.instance_ids`.
- `GET /instances`, `GET /instances/{id}` (`status`, `ip`, `region`, `first_healthy`).
- `POST /instance-operations/terminate` with `{"instance_ids": [...]}`.
- Filesystems: `GET /filesystems` (`/file-systems` is the deprecated alias). Fields include
  `name`, `region`, `mount_point`, `is_in_use`, `bytes_used`. A filesystem must be in the
  instance's region. Filesystems are billed per GiB used, separately from instances.
- **Billing:** Lambda's billing docs say billing runs from launch (once health checks pass) until
  the instance is terminated, whether or not it is used. An OS shutdown does not stop billing; a
  forum report says a shut-down instance shows status "alert" and still needs a terminate call.
  So only the terminate call stops billing, as assumed below.
- Not yet checked (needs `LAMBDA_API_KEY`): the live A10 type name, price and regions; the SSH
  key names on the account; whether a filesystem holds `rsi_pilot/data/`.

The client is `rsi_pilot/cloud/lambda_api.py` (not `lambda.py`: `lambda` is a Python keyword
and cannot be imported). Run from `rsi_pilot/` as `python -m cloud.lambda_api ...`; its
docstring lists the commands. Guardrail tests: `tests/test_cloud.py`.

## Guardrails (set by the author, 2026-11-03; do not change without the author)

- **One instance at a time, type 1x A10.** Confirm the type name from the instance-types listing.
- **Per launch: 48 hours and $50, whichever comes first.** Cap hours = min(48, 5000 / live
  `price_cents_per_hour`), using the price the API reports at launch, not a remembered price.
  Each new launch needs the author's go-ahead; budgets do not roll over.
- **Terminate only what this process launched**, matched by the instance id in
  `rsi_pilot/cloud/ledger.jsonl`. Never terminate by name, type or "the only A10". Anything else
  in the account is not yours.
- **Name prefix `chiron-`** on every launch (e.g. `chiron-run4-a`).
- **Terminate at job end or at the cap**, and the cap must hold even if the laptop sleeps (see
  Watchdog).
- **The API key never appears** in chat, logs, commits, command lines visible in `ps`, or files
  in the repo. Read it from `LAMBDA_API_KEY` in the environment.

### Author changes for run 4 (2026-11-03, in chat)

- The author's manually launched A10 (`Chiron`, running run 5) is adopted into the ledger
  with its cap counted from its billing start. It keeps running.
- Run 4 (6 seeds after amendment 1) runs on **up to 3 more 1x A10s at once**, two seeds each,
  for **$50 in total**: each launch gets `budget_usd = 50/3`, cap = 1667 / live price
  (12.9 h at $1.29). `lambda_api.MAX_OPEN = 4` covers the adopted instance plus three.
- Seed 20261111 restarts from scratch: its partial outputs on the old instance stopped after
  8 minutes, before any evolution result.
- Run-4 instances run the working branch (a git bundle, not a push); see `cloud/bootstrap.sh`.

## Ledger (`rsi_pilot/cloud/ledger.jsonl`, committed)

Append one JSON line per event and commit it:

- `launch`: id, name, type, region, price_cents_per_hour, launched_at (UTC), terminate_by,
  cap_hours, approved_by_author (the message or date of approval)
- `check`: time, status, hours_elapsed, est_spend_usd, job_state
- `terminate`: time, reason (`job_done` | `cap` | `error` | `author`), est_spend_usd

Estimated spend = hours since launch x launch price. Before any launch, the ledger must show no
instance without a `terminate` line.

## Lambda API (verify every item before first use)

- Base URL: `https://cloud.lambda.ai/api/v1` (older: `cloud.lambdalabs.com`). Auth with the key
  as a bearer token or basic-auth user; check which.
- List types and prices: `GET /instance-types` (look for `price_cents_per_hour` and regions with
  capacity).
- Launch: `POST /instance-operations/launch` with region, instance type, SSH key names, name,
  optional filesystem names. Check the exact field names and whether a startup script is
  accepted.
- Instances: `GET /instances`, `GET /instances/{id}` (status, IP).
- Terminate: `POST /instance-operations/terminate` with a list of ids.
- **Billing:** confirm whether an OS shutdown stops billing or only the terminate call does.
  Until confirmed, assume only terminate does.

Write a small `rsi_pilot/cloud/lambda.py` (stdlib `urllib`, key from env) with `types`,
`launch`, `status`, `terminate`, each appending to the ledger. `terminate` refuses any id not in
the ledger. Unit-test the refusal and the cap arithmetic without network.

## Watchdog (the cap must not depend on the laptop)

A local session can stop at any time (laptop sleep, closed terminal), so the termination at
`terminate_by` needs a second path. Options, in order of preference; the author picks one before
the first launch:

1. **On-instance self-terminate.** At bootstrap, copy the key to `/root/.lambda_key` (mode 600,
   never in the repo) and install a systemd timer or `at` job that calls the terminate endpoint
   for this instance's own id at `terminate_by`, and also when the job script exits. Risk: the
   account key sits on the instance for up to 48 hours. The instance is yours and ephemeral.
2. **Cloud scheduled task.** A Claude cloud session scheduled for `terminate_by` that calls
   terminate. Requires the cloud environment to allow `cloud.lambda.ai` and hold the key as a
   secret.
3. **Laptop only, kept awake** (`caffeinate -dims` on macOS) with a local `at`/`launchd` job.
   Weakest; a lid close or reboot defeats it.

Whichever is chosen, the local session also checks status on every wake and terminates past the
cap.

## Bootstrap (on the instance, over SSH, inside `tmux`)

```bash
tmux new -s chiron
git clone https://github.com/RohanChavan0701/Chiron.git && cd Chiron
git checkout <working branch>
cd rsi_pilot && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
curl -fsSL https://ollama.com/install.sh | sh          # verify current install method
ollama pull qwen2.5:1.5b-instruct && ollama pull qwen2.5:32b-instruct   # ~20 GB for 32B
.venv/bin/python -m pytest -q                          # 66 pass, no models needed
```

Data (not in git): `rsi_pilot/data/spider/` (dev.json, train_spider.json, tables.json,
database/), `rsi_pilot/data/bird_minidev/` (Mini-Dev SQLite json + dev_databases/),
`rsi_pilot/data/testsuite/` (Spider test-suite `database/`). Runs 1 to 3 ran on a Lambda A10 at
`/home/ubuntu/Chiron` (see `runs/audit.json`), so the data may survive on a persistent
filesystem; check `GET /file-systems` first and attach it at launch if present. Otherwise the
author confirms download sources; do not guess.

Ollama settings: one server for student, proposer and critic. If arms run in parallel
(`run_v4.sh` starts A, B, C together with 4 workers), set `OLLAMA_NUM_PARALLEL` and confirm the
student is still deterministic afterwards: the baseline repeats in `noise_floor.json` must agree.

## Smoke test before any long job (budget gate)

1. `RSI_FROZEN=frozen_v4_s20261111.yaml ...` then `python -m rsi.splits` and
   `python -m rsi.critic_check` (expect 20/20 as in the pre-registration).
2. Time one baseline E evaluation (100 tasks) and one proposer call with the 32B loaded.
3. Project hours per seed (about 35 E evaluations per arm, three arms, plus held-out on 720
   tasks per harness). Write the projection to the ledger as a `check` line.
4. If the projection for the planned seeds exceeds the cap, stop and report to the author with
   the numbers. Do not start a seed that cannot finish before the cap.

## Running and retrieving

- Seeds run one at a time inside `tmux`: `scripts/run_v4.sh <SEED> 4`.
- After each seed: `rsync` from the instance to the laptop `runs_v4/s<SEED>/` (exclude
  `cache/`), `splits_v4_s<SEED>.json`, `frozen_v4_s<SEED>.yaml`; commit locally; push to the
  working branch. A cap hit then loses at most the seed in progress.
- Do not open per-seed `results.md` to decide whether to run more seeds. Continue or stop on
  budget and time only; the pre-registered analysis is across all seeds (`rsi.pool --seed-level`),
  and stopping on a peek is optional stopping.
- On job end: rsync, commit, terminate, ledger `terminate` line, commit.
