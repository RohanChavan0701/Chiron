# QualityBench load sweep: launch runbook (laptop, Git Bash)

Approved by the author in chat on 2026-11-27: "go ahead launch item 2, cap it at 5". Budget
**$5** for one launch. The cloud session that prepared the job could not launch it: that container
has no SSH egress, no Hugging Face token, and the model (`mistralai/Mistral-7B-v0.1`) is gated.
The author then said Lambda has no credits and named Vultr or Modal. Vultr refused every GPU
launch on 2026-11-27 (monthly fee limit), so **Modal is the path**; the Lambda steps stay below
as the alternative.

## Modal (primary)

`cloud/modal_qb_sweep.py`, patterned on `modal_ablation.py`: one `A100-40GB` container
(2.10 USD/h GPU, 2.42 USD/h with 4 cores and 16 GiB; prices read 2026-11-27), hard timeout
100 min, worst case **4.23 USD** against the 5 USD budget (`python cloud/modal_qb_sweep.py plan`
prints the guard and refuses a dirty tree). No retries: a timeout ends the run and whatever was
copied to the volume by then is kept (results are copied every 5 minutes). The 40 GB A100 is the
GPU class of the committed matrix, so the concurrency-1 cell is comparable with the committed
vLLM row apart from the vLLM version, the client path and the host (Modal, not Lambda).

One-time, in the Modal dashboard or CLI (the token never enters this repo or the chat):

```bash
cd Chiron/rsi_pilot                               # branch main-plobim, pulled, clean tree
.venv/Scripts/python.exe -m modal secret create huggingface HF_TOKEN="$HF_TOKEN"
# dashboard, Settings, Usage & Billing: Workspace budget / spend limit at or below 5 USD above
# the current month's spend (outer cap; the code's guard is the inner one)
```

Launch, detached (the laptop may sleep afterwards):

```bash
.venv/Scripts/python.exe cloud/modal_qb_sweep.py plan           # offline: cost guard, clean tree
.venv/Scripts/python.exe -m modal run --detach cloud/modal_qb_sweep.py
```

While it runs (about 50 min expected; the image build on the first launch adds about 10 min of
CPU time, billed at CPU rates):

```bash
.venv/Scripts/python.exe -m modal app list                          # ap-... id
.venv/Scripts/python.exe -m modal app logs ap-XXXX --tail 50
.venv/Scripts/python.exe -m modal volume ls chiron-qb-out qb_load_sweep
```

Fetch and finish (no numbers are printed by Modal; the table is in the volume):

```bash
STAGE=$(mktemp -d)
.venv/Scripts/python.exe -m modal volume get chiron-qb-out qb_load_sweep "$STAGE"
ls "$STAGE/qb_load_sweep"                                 # one <run id> dir; DONE or FAILED inside
cd ../../qualitybench && git checkout -b load-sweep main && git am ../Chiron/rsi_pilot/cloud/qb_load_sweep.patch
cp -r "$STAGE"/qb_load_sweep/<run id>/results/load_sweep results/
cp -r "$STAGE"/qb_load_sweep/<run id>/results/load_sweep_smoke results/
cp "$STAGE"/qb_load_sweep/<run id>/{run_record.json,nvidia_smi.txt,qb_sweep.log} results/load_sweep/
python analysis/load_sweep_table.py --results-dir results/load_sweep
```

Then paste the table into the README section "Concurrent serving sweep", change its heading
from "not yet run" to the date and GPU, note Modal as the host and the vLLM version from
`results/load_sweep/ENVIRONMENT_serve.md`, and commit the results directory.

Stop everything: `.venv/Scripts/python.exe -m modal app stop ap-XXXX`.

Not verified without a Modal account: that the image builds (vLLM 0.34.0 wheel on Python 3.11,
debian_slim), that the gated download succeeds with the secret, and the exact run time. The
smoke stage (first 10 minutes) is where a problem would show; `modal app logs` names the step.

## Lambda (alternative, needs credits)

### GPU choice

- **Default: 1x A10** (`gpu_1x_a10`, 1.29 USD/h live on 2026-11-27, capacity us-east-1 and
  us-west-1). It is the guardrailed type, so no rule changes. Cap 500 / 129 = 3.88 h for about
  1 h of work. The fp16 weights (about 14.5 GB) fit the 24 GB card with 4k-context KV cache.
  Cost of this choice: the committed QualityBench matrix ran on an A100 40 GB SXM4, so the
  sweep's concurrency-1 cell is the sweep's own reference, not a replication of the committed
  vLLM row. The sweep's claim (how throughput and latency scale with concurrency) does not
  depend on that.
- **A100 40 GB SXM4** (`gpu_1x_a100_sxm4`, 1.99 USD/h, 2.51 h at the cap) would make the
  concurrency-1 cell comparable with the committed row. It needs an author exception in
  `lambda_api.TYPE_EXCEPTIONS` plus a line under "Author changes" in `CLOUD_RUN.md`, which
  only the author adds (the preparing session was stopped from adding it, correctly).

### Steps

```bash
cd Chiron/rsi_pilot                       # branch main-plobim, pulled; LAMBDA_API_KEY in env
COMMIT=$(git rev-parse HEAD)              # the instance fetches cloud/qb_load_sweep.patch at this commit
git branch -r --contains $COMMIT          # must list origin/main-plobim: push first if empty

# 1. launch (ledger line, cap = 5 dollars at the live price)
python -m cloud.lambda_api launch --name chiron-qb-load --region us-east-1 --ssh-key Chiron \
  --budget-usd 5 --approved-by "author, 2026-11-27 chat: 'go ahead launch item 2, cap it at 5'"
git add cloud/ledger.jsonl && git commit -m "rsi_pilot: ledger launch line for chiron-qb-load" && git push

# 2. wait for status active and note ID, IP, terminate_by
python -m cloud.lambda_api status ID --job-state booting

# 3. arm the cap watchdog (key over ssh stdin, as always)
scp -i ~/Downloads/Chiron.pem cloud/watchdog.sh cloud/qb_load_sweep_remote.sh ubuntu@IP:
printf 'Authorization: Bearer %s\n' "$LAMBDA_API_KEY" | ssh -i ~/Downloads/Chiron.pem ubuntu@IP "sudo bash watchdog.sh ID TERMINATE_BY"

# 4. start the job in tmux; HF_TOKEN goes over the ssh channel into the session, not a command line
printf '%s\n' "$HF_TOKEN" | ssh -i ~/Downloads/Chiron.pem ubuntu@IP \
  'read -r HF_TOKEN; export HF_TOKEN; tmux new -d -s qb "bash ~/qb_load_sweep_remote.sh '"$COMMIT"'"'
python -m cloud.lambda_api status ID --job-state "watchdog armed; qb_load_sweep_remote.sh started in tmux"
git add cloud/ledger.jsonl && git commit -m "rsi_pilot: chiron-qb-load job started" && git push

# 5. follow; the job writes ~/QB_SWEEP_DONE when finished (about 1 h expected)
ssh -i ~/Downloads/Chiron.pem ubuntu@IP tail -f qb_sweep.log

# 6. fetch, then terminate, then commit the ledger
rsync -az -e 'ssh -i ~/Downloads/Chiron.pem' ubuntu@IP:qualitybench/results/load_sweep ubuntu@IP:qualitybench/results/load_sweep_smoke ../../qualitybench/results/
python -m cloud.lambda_api terminate ID --reason job_done
git add cloud/ledger.jsonl && git commit -m "rsi_pilot: chiron-qb-load terminated, job done" && git push
```

Then in the qualitybench checkout: `git am cloud/qb_load_sweep.patch` (from this repo) if the
sweep commit is not there yet, `python analysis/load_sweep_table.py --results-dir
results/load_sweep`, paste the table into the README section "Concurrent serving sweep", change
its heading from "not yet run" to the run date and GPU, and commit the results directory.

### If something goes wrong

- Smoke fails (first 10 minutes): the log names the step. Terminate with `--reason error`,
  fix, relaunch; the cap is per launch and does not roll over.
- The job is not done by about 2 h: look at `qb_sweep.log`; the watchdog terminates at the
  cap regardless, so rsync whatever `results/load_sweep` holds before then.
- `vllm serve` does not become healthy: `~/qualitybench/results/load_sweep_smoke/server.log`.
  The likely A10 cause is memory; the smoke uses the same server settings as the full run.
