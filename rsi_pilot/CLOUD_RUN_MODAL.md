# Run-5 ablation on Modal (runbook)

Runs the registered ablation (`PREDICTION_schema_only.md`) on Modal instead of one Vultr VM.
Code: `cloud/modal_ablation.py` (tests: `tests/test_modal_ablation.py`, offline). What is
measured is unchanged: each seed is one session of `scripts/run_ablation.sh SEED 8` against one
Ollama 0.40.13 server (port 11435, 8 parallel slots, keep-alive -1, no flash attention) with
`qwen2.5:7b-instruct` fully on the GPU, and the baseline and all four variants of a seed share
that session.

All commands: Git Bash, from `rsi_pilot/`.

## Deviation to record (owner)

- **Provider and layout.** Modal instead of Vultr. Six containers, one per seed, all started
  together, all requesting the same GPU type (`A100-80GB`, 8 physical cores, 32 GiB RAM each),
  instead of six sessions in sequence on one VM. Pairing is kept: a seed's baseline and variants
  always run in the same container and on the same server. Across seeds, the host (and the A100
  variant, SXM or PCIe) can differ; each seed's `nvidia-smi` output is saved with its results.
- **Reruns.** A failed seed is rerun once with the same seed, in a fresh container, only while
  the 30 dollar budget allows it (below). Modal may also restart a preempted GPU container on the
  same input; that counts as one of the two starts a seed may have. Every start is recorded under
  `s<SEED>/starts/` and `s<SEED>/attempts/` in the out volume.
- **Software.** Python 3.12 (Modal `debian_slim`), the same `requirements.txt`, Ollama installed
  with the official script and `OLLAMA_VERSION=0.40.13`. The student digest is in
  `runs_v5/s<SEED>/ablation_modal/ollama_list.txt`.

## What was checked in the docs (2026-11-27) and what was not

Checked against the installed client (modal 1.6.4, signatures and CLI `--help`) and these pages:

- GPU names: https://modal.com/docs/guide/gpu (`A100-80GB` pins 80 GB; `A100` may be either).
- Prices: https://modal.com/pricing (A100 80 GB 0.000694 USD/s, CPU 0.0000131 USD/core/s,
  memory 0.00000222 USD/GiB/s; Starter plan: 30 USD/month credits, 10 GPU concurrency).
- Driver: https://modal.com/docs/guide/cuda (driver and `nvidia-smi` are provided; no CUDA install).
- Timeouts: https://modal.com/docs/guide/timeouts (per attempt; `startup_timeout` separate).
- Preemption: https://modal.com/docs/guide/preemption (all functions preemptible; a preempted
  input is restarted; `nonpreemptible` is not supported for GPU functions, 3x CPU/memory price).
- Volumes: https://modal.com/docs/guide/volumes (commit/reload, read-only mounts, v2 for many
  concurrent writers; v1 recommends at most five).
- Detach: https://modal.com/docs/guide/apps and https://modal.com/docs/reference/cli/run
  (`--detach`: "Don't stop the app if the local process dies or disconnects").
- Budgets: https://modal.com/docs/guide/budgets (Workspace budget and spend limit, Usage & Billing).
- Ollama install script: https://raw.githubusercontent.com/ollama/ollama/main/scripts/install.sh
  (needs curl; zstd for `.tar.zst` releases; without lspci/lshw it installs the binary and stops).
- `modal volume get`: read in the client source: the last part of REMOTE_PATH is kept under the
  destination, and `--force` deletes an existing local directory before writing. So results are
  fetched into an empty stage dir, never straight into the repo.

Not verified (no Modal account was used): that the image builds; that Ollama 0.40.13 downloads
with `?version=`; the exact `ollama ps` columns of that version (the parser matches the format
the VM script relied on); Modal's default container disk size (`run_seed` refuses to start with
under 15 GB free); that a spawned call keeps running after the laptop disconnects (it follows
from "don't stop the app", but was not tried).

## One-time setup (owner, yourself)

1. Sign in: `.venv/Scripts/python.exe -m modal setup` opens a browser. The token is stored on
   this machine only. Never paste it in chat, logs or commits.
2. In the Modal dashboard, Settings, Usage & Billing: set the Workspace budget (usage limit) to
   30 dollars. It is the outer cap; the code's guard is the inner one.
3. Create the three volumes (v2):

```
.venv/Scripts/python.exe -m modal volume create --version 2 chiron-data
.venv/Scripts/python.exe -m modal volume create --version 2 chiron-ollama
.venv/Scripts/python.exe -m modal volume create --version 2 chiron-ablation-out
```

## Launch sequence

The launch is refused while any file the run uses is modified or untracked
(`cloud/modal_ablation.py` included), so commit first.

```
# 1. upload the data archive (551 MB)
.venv/Scripts/python.exe -m modal volume put chiron-data "<path to chiron_data_slim.tar.gz>" chiron_data_slim.tar.gz

# 2. offline check: cost guard and clean tree (no Modal contact)
.venv/Scripts/python.exe cloud/modal_ablation.py plan

# 3. launch, detached (prints the app URL/id and the orchestrate call id)
.venv/Scripts/python.exe -m modal run --detach cloud/modal_ablation.py --seeds all
```

Detach and the laptop: with `--detach` the app keeps running if the laptop sleeps or the terminal
dies. The local entrypoint itself does not survive that, so it does nothing but check, print the
cost and spawn `orchestrate`. Everything else (prepare, the six seeds, the rerun round, the budget
accounting, the `ABLATION_DONE` file) runs server side in `orchestrate`, a CPU function marked
nonpreemptible. Without `--detach`, closing the terminal stops the app and all containers.

## While it runs

```
.venv/Scripts/python.exe -m modal app list                       # find the app id (ap-...)
.venv/Scripts/python.exe -m modal app logs ap-XXXX --tail 200    # start/done/failed lines only
.venv/Scripts/python.exe -m modal volume get chiron-ablation-out s20261211/PROGRESS -
.venv/Scripts/python.exe -m modal volume get chiron-ablation-out ABLATION_DONE -
```

`PROGRESS` shows elapsed minutes, how many of the 10 evaluations exist, and whether the model was
seen 100% on the GPU. No accuracy is printed or logged by Modal; the session's own output is in
`s<SEED>/attempts/NN/seed_stdout.log` in the out volume (do not open it before all seeds are in).

## Fetch and analyse

```
STAGE=$(mktemp -d)
for s in 20261211 20261212 20261213 20261214 20261215 20261216; do
  .venv/Scripts/python.exe -m modal volume get chiron-ablation-out s$s "$STAGE"
done
.venv/Scripts/python.exe cloud/modal_ablation.py merge "$STAGE"
.venv/Scripts/python.exe -m rsi.ablate report runs_v5/s2026121?
```

`merge` copies `STAGE/s<SEED>/rsi_pilot/...` to the same paths in `rsi_pilot/`
(`runs_v5/s<SEED>/ablation/`, `runs_v5/s<SEED>/heldout_access.jsonl`, `runs_v5/s<SEED>/logs/`,
`runs_v5/s<SEED>/ablation_modal/`, `splits_v5_s<SEED>.json`). It never deletes, skips seeds
without `SEED_DONE` and `ablation.json`, and refuses (copying nothing) if a local file differs
from the fetched one other than by appended lines.

## Stop everything

```
.venv/Scripts/python.exe -m modal app stop ap-XXXX
```

Stops the app and terminates all its containers. Results already committed to the out volume
stay; a rerun of the launch skips seeds whose `SEED_DONE` and `ablation.json` exist.

## Cost model and guard

Constants in `cloud/modal_ablation.py` (prices: re-check before launch):

- Seed container: A100 80 GB + 8 cores + 32 GiB = 3.13 USD/h. Hard timeout `MAX_SEED_MINUTES`
  = 75 min plus 5 min startup: 4.18 USD worst case per attempt.
- prepare (2 cores, 8 GiB, 60 min) and orchestrate (0.25 core, 1 GiB, 3x nonpreemptible price,
  4 h 40 min) together: 0.44 USD worst case.
- First round, six seeds all at the timeout: 25.49 USD. The launch is refused if this exceeds
  `BUDGET_USD` = 30.
- The requested sizing (6 seeds x 2 attempts x 90 min) would be 59.93 USD worst case, and even
  one attempt of 90 min per seed (29.8 USD before overhead) does not fit, so: timeout 75 min
  (about 1.7x the expected 35 to 45 min session) and reruns admitted by budget. After the first
  round, `orchestrate` estimates what was spent (each attempt's duration plus 5 min, the worst
  case for timeouts) and reruns failed seeds only while spent + reruns at worst case + overhead
  stay within 30 USD: at least 1 rerun even if all six first attempts time out, all six if the
  sessions take about 45 min. A seed is never started more than twice (`MAX_STARTS_PER_SEED`).
- Not covered by the code guard: preemption restarts inside the first round (each one is a new
  75 min attempt). The Workspace budget in the dashboard is the backstop.
