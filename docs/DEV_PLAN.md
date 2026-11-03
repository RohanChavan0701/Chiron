# Development plan (updated 2026-11-03, after runs 4 and 5)

For a local Claude Code session that continues this project, with or without a Lambda A10. Read
this, then `rsi_pilot/CLOUD_RUN.md` (instance runbook and the author's spending limits), then
`rsi_pilot/README.md`, `rsi_pilot/PROJECT_REPORT.md` and `docs/PROJECT_NOTES.md`.

Working branch: `claude/laughing-ritchie-zafhnk`, open as PR RohanChavan0701/Chiron#1 into
`main` (run 4, Lambda tooling, project notes). Run 5 is already on `main` (PR #2).

## Where things stand

| Item | State |
|---|---|
| Runs 1 to 3 (single-shot harness, 1.5B student, n=50) | Done. Tuning-set gains do not transfer. |
| Run 4 (single-shot, 1.5B student, 3 arms, 6 seeds, pre-registered) | Done 2026-11-03. Primary endpoint null (B vs A on held-out Spider -4.3 tasks of 322, p = 0.56); random edits matched the LLM proposer. Outputs in `rsi_pilot/runs_v4/`, results in the README "Run 4". |
| Run 5 (multi-step agent, 7B student, 3 arms, 6 seeds, pre-registered) | Done. Transferred about +12 points on held-out Spider in 6 of 6 seeds; regularization did not change accuracy; random edits matched the LLM proposer. Results in the README TL;DR and `PROJECT_REPORT.md`. |
| Poisoning audit (E2) | Designed, implemented, tested. Not run. Its clean control is run 4 seeds 20261111 to 20261113, which now exist. |
| Lambda tooling | Done: `rsi_pilot/cloud/` (client, ledger, watchdog, bootstrap), 20 tests. |
| Lambda instances | None running. All four instances in `cloud/ledger.jsonl` are terminated. |
| Data (Spider, BIRD Mini-Dev, test-suite DBs, about 8 GB) | Not on any instance or Lambda filesystem. Only copy: laptop archive `C:\Users\Rohan\Desktop\Chiron_backup_2026-11-03\instance_chiron_backup.tar.gz` (members `Chiron/rsi_pilot/data/...`). |
| Write-up | Draft in `docs/writeup/post.md` covers runs 1 to 3 only. Not published. |
| BIRD hand labels | `audit_bird_labels.csv` per run and seed, unlabeled. |

## Rules that hold in every phase

- Spending limits and termination rules in `CLOUD_RUN.md` are the author's and do not change
  without the author. Each launch needs a go-ahead.
- Do not edit `PREDICTION.md`, `PREDICTION_run5.md` or the predictions section of
  `POISON_AUDIT.md`. Results that contradict a prediction are reported, not reconciled.
- Do not change a run's settings after its first seed starts. A needed change is a deviation:
  stop, record it in the README's deviations list, and ask.
- Do not decide whether to run more seeds from held-out results. Decide on budget and time.
- Commit run outputs with the code that produced them. Report nulls.
- Process, in order, one item at a time: branch, code, PR, review, QA, merge, release. No
  Linear ticket for this personal repo. Nothing is pushed before the author has looked at it.

## Phase A: close out runs 4 and 5 (no GPU)

1. Author reviews PR #1 (README "Run 4", the arm C rerun deviation, `docs/PROJECT_NOTES.md`),
   then QA, then merge.
2. Fix the doc inconsistencies listed in `docs/PROJECT_NOTES.md` section 12 (top-level README
   pilot section; "32 plumbing tests"; "One instance at a time" in `CLOUD_RUN.md`).
3. Add a retry on HTTP 5xx in `rsi_pilot/rsi/student.py` (run 4's only crash), with a test. For
   future runs only; runs 4 and 5 are frozen.
4. Author labels the BIRD CSVs. The session can pre-sort rows (verifier disagreements first).

## Phase B: write-up (no GPU)

Fold runs 4 and 5 into `docs/writeup/post.md`. The story: with little headroom (run 4)
evolution's tuning-set gains are selection noise; with a baseline missing general information
(run 5) the gains transfer; in both, random edits match the LLM proposer. Regenerate figures
with `docs/writeup/make_figures.py`. Author checks every citation before publishing.

## Phase C: poisoning audit, step 1 (needs a launch go-ahead)

Launch one 1x A10 per `CLOUD_RUN.md` (see "Relaunch checklist" below), then
`scripts/run_poison.sh <SEED> P2b 15` for seeds 20261111 to 20261113 (6 arm-runs, about a day by
the design's estimate), then `scripts/run_poison.sh <SEED> P2b 15 global` on one seed.
Hand-label carrying candidates into `poison_labels.csv`. Run the persistence phase only for
arm-runs that adopted.

Gate: if step 1 shows no adoption in any arm-run, stop the audit there and write it up as
"not injectable through the question channel at this dose", per the design.

## Relaunch checklist (any future GPU work)

1. On the laptop: key in `LAMBDA_API_KEY` (Windows user env), ledger shows no open instance.
2. `python -m cloud.lambda_api launch ...` with the author's approval text and budget
   (`--budget-usd`); the ledger records the cap.
3. Make a git bundle of the branch to run; copy it and the data archive to the instance:
   `scp -i ~/Downloads/Chiron.pem instance_chiron_backup.tar.gz ubuntu@NEW:` (about 8 GB raw).
4. Bootstrap (absolute remote paths, so the laptop shell does not expand `~`):
   `ssh -i ~/Downloads/Chiron.pem ubuntu@NEW bash -s /home/ubuntu/branch.bundle BRANCH /home/ubuntu/instance_chiron_backup.tar.gz < cloud/bootstrap.sh`
   (installs Ollama 0.40.13, pulls models, extracts only `data/`, checks digests, runs tests).
5. Install the watchdog on the instance: `sudo bash watchdog.sh ID TERMINATE_BY < header`, with
   the header sent over ssh stdin, never on a command line.
6. Run inside `tmux`. After each seed: copy outputs back (exclude `cache/`), commit. At job end:
   copy, commit, `lambda_api.terminate(id, "job_done")`, commit the ledger line.

Model digests on the original instance (Ollama 0.40.13, read 2026-11-03 before it was
terminated): `qwen2.5:1.5b-instruct` 65ec06548149, `qwen2.5:7b-instruct` 845dbda0ea48 (run 5
student), `qwen2.5:32b-instruct` 9f13ba1299af, `qwen2.5:14b-instruct` 7cdf5a0187d5 (runs 1 to 3
proposer), `llama3.1:8b` 46e0c10c039e (run 2 critic). `bootstrap.sh` checks only the 1.5B and
32B; add the 7B check before reusing it for run-5 work. Run 5 served the 7B student from a
second Ollama server on port 11435 with `OLLAMA_NUM_PARALLEL=8` (`PROJECT_REPORT.md` 3.4).

## Candidates after that (each needs its own pre-registration)

| Next | What | Compute |
|---|---|---|
| Test-suite endpoint | Pre-register the test-suite-corrected held-out comparison that looked different in run 4's exploratory audit (`docs/PROJECT_NOTES.md` 8.1). Can be computed from existing run 4 and 5 outputs if the audit data is there; otherwise re-score. | None to little |
| Run 5 with a stronger baseline | Full schema up front from the start, to test whether anything beyond "finding missing defaults" transfers. | About 11 h on one A10 |
| Frontier proposer | Same arms with a frontier-model proposer, to test whether a better proposer beats random search. | API cost |
| Archive arm (E1) | Top-k harness archive and CMP-style selection on a held-back slice of E. | Same as a run-4 seed per arm |
| E3 | GRPO on the correction stage's verified pairs for the 1.5B student, against few-shot memory on the same held-out set. | One A10, hours per run |

## What the author decides (collected so nothing is assumed)

1. Review, QA and merge of PR #1.
2. Whether and when to launch for the poisoning audit, and its budget.
3. Publish timing for the write-up.
4. Whether to keep the Lambda API key in the Windows user env between launches.
5. Where to keep the 8 GB data archive long term (it is the only copy).
