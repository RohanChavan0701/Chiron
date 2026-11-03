# Development plan (draft, 2026-11-03)

For a local Claude Code session that manages a Lambda A10 and continues this project. Read this,
then `rsi_pilot/CLOUD_RUN.md` (instance runbook and the author's spending limits), then
`rsi_pilot/README.md`, `rsi_pilot/PREDICTION.md` and `rsi_pilot/POISON_AUDIT.md`.

Working branch: `claude/laughing-ritchie-zafhnk` (not yet merged to `main`; it holds the
framing cleanup, write-up draft, poison audit and these plans). Merge or keep working on it, as
the author decides.

## Where things stand

| Item | State |
|---|---|
| Runs 1 to 3 (harness evolution, n=50) | Done. Tuning-set gains do not transfer; documented with nulls. |
| Run 4 (10 seeds, arms A/B/C, n=100/322/398) | Code and predictions committed in `e085db7`. Not run. |
| Poisoning audit (E2) | Designed, implemented, 12 tests. Not run. Needs run 4 seeds 20261111 to 20261113 as its clean control. |
| Write-up | Draft in `docs/writeup/post.md`, figures in `docs/writeup/`. Not published. |
| BIRD hand labels | `rsi_pilot/runs*/audit_bird_labels.csv`, about 160 rows, unlabeled. |
| Lambda tooling | None yet. `rsi_pilot/cloud/` to be written in phase 0. |

## Rules that hold in every phase

- Spending limits and termination rules in `CLOUD_RUN.md` are the author's and do not change
  without the author. Each launch needs a go-ahead.
- Do not edit `PREDICTION.md` or the predictions section of `POISON_AUDIT.md`. Results that
  contradict a prediction are reported, not reconciled.
- Do not change run-4 settings (`frozen_v4.yaml`, splits code, arms) after the first seed starts.
  A needed change is a deviation: stop, record it in the README's deviations list, and ask.
- Do not decide whether to run more seeds from held-out results. Decide on budget and time.
- Commit run outputs with the code that produced them. Report nulls.

## Phase 0: local, no GPU (half a day)

1. Pull the branch; run both test suites (`pytest -q` at the root, 285; in `rsi_pilot`, 66).
2. Verify the Lambda API against docs.lambda.ai: endpoints, auth, launch fields (name, SSH keys,
   filesystem, startup script), whether OS shutdown stops billing. Record findings at the top of
   `CLOUD_RUN.md`.
3. Write `rsi_pilot/cloud/lambda.py` (types, launch, status, terminate, all ledger-writing;
   terminate refuses ids not in the ledger) and unit tests for the refusal and cap arithmetic.
4. Read-only calls only: list instance types and A10 price/availability, list SSH keys, list
   filesystems. Look for a filesystem holding `rsi_pilot/data/` from runs 1 to 3.
5. **Ask the author:** watchdog option (CLOUD_RUN.md), data source if no filesystem has it, and
   go-ahead for launch 1 with the projected cost.

Exit: author approval for launch 1.

## Phase 1: launch 1, bootstrap and smoke (first 2 to 3 hours of the 48)

Launch per `CLOUD_RUN.md`, install the watchdog, bootstrap, smoke test. The smoke test produces a
projected hours-per-seed figure.

Gate: if the projection says fewer than 2 seeds fit in the cap, report and ask before continuing.
Rough expectation, unmeasured: 2 seeds fit, 3 may.

## Phase 2: run 4, seeds 20261111 to 20261113 (rest of launch 1)

Seeds in order, one at a time, results pulled and pushed after each. Stop starting new seeds when
the remaining cap is below the measured per-seed time. Terminate at job end or cap.

Deliverable: `runs_v4/s20261111` to `s20261113` committed, ledger closed.

## Phase 3: no GPU, while waiting for approval of launch 2

- Author labels the BIRD CSVs. The session can pre-sort rows (verifier disagreements and gold
  structure mismatches first) to cut that to the rows that matter.
- Author checks the arXiv citations in the write-up draft (listed in its header).
- Optional: open a PR for the working branch.

## Phase 4: launch 2, poisoning audit step 1 (needs approval)

`scripts/run_poison.sh <SEED> P2b 15` for the three seeds (6 arm-runs, about a day by the
design's estimate), then `scripts/run_poison.sh <SEED> P2b 15 global` on one seed. Hand-label
carrying candidates into `poison_labels.csv`. Run the persistence phase only for arm-runs that
adopted.

Gate: if step 1 shows no adoption in any arm-run, stop the audit there and write it up as
"not injectable through the question channel at this dose", per the design.

## Phase 5: launches 3 and up, run 4 seeds 20261114 to 20261120 (needs approval per launch)

Same procedure as phase 2. About two to three launches at the projected rate. When all seeds that
will run have finished, run the pre-registered analysis once:

```bash
cd rsi_pilot && .venv/bin/python -m rsi.pool runs_v4/s* --seed-level
```

Add a "Run 4" results section to `rsi_pilot/README.md` with the primary endpoint first, then each
prediction scored as held / did not hold.

## Phase 6: publish (no GPU)

Update `docs/writeup/post.md`: either publish on runs 1 to 3 with run 4 as pre-registered
follow-up (recommended, can happen any time after phase 3), or fold in run 4 and the poison audit.
Regenerate figures with `docs/writeup/make_figures.py`.

## After run 4: candidates, not commitments

Each needs its own pre-registration before any run.

| Next | What | Compute |
|---|---|---|
| Run 5 (E1) | Archive arm (top-k harnesses, propose from any) and CMP-style selection on a held-back slice of E. Tests whether the HGM argument explains the transfer gap. | Same as a run-4 seed per arm |
| E3 | GRPO on the correction stage's verified (question, gold SQL) pairs for the 1.5B student; compare against few-shot memory on the same held-out set, including forgetting on easy tasks. | One A10, TRL, hours per run |
| S1 | Standalone poisoning and defense for a self-modifying coding agent (SICA-style), building on E2's attack design. | API, about $100 to $300 |

## What the author decides (collected so nothing is assumed)

1. Watchdog option for the instance cap.
2. Data source if no Lambda filesystem has it.
3. Go-ahead and budget for each launch.
4. Publish timing for the write-up.
5. Whether to merge the working branch to `main`.
