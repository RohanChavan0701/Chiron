# Predictions for run 4 (committed BEFORE any run-4 result exists)

**Who wrote this.** These predictions were written by the AI assistant (Claude) that built
run 4, at the user's request, before any run-4 baseline, evolution or held-out result
existed. The user did not write or edit them. Runs 1-3 had no predictions (see README).

Date: 2026-11-03
Code: the commit that adds this file (run-4 code and `frozen_v4.yaml` are in the same commit).
No run-4 numbers had been produced at that point. Smoke tests had run: baseline E repeats
for seed 20261111 (35-36/100) and the critic check.

## Design (fixed before running)

- 10 seeds: 20261111 to 20261120. Each seed draws E (100 tasks) and E2 (100 fresh tasks from
  the same databases) from Spider train hard/extra. The held-out sets are the same for
  every seed:
  - H: all 322 eligible Spider dev hard/extra tasks;
  - B: all 398 eligible BIRD Mini-Dev simple/moderate tasks.
- Arms:
  - **A**: LLM proposer, any edit, keeps any gain of 1 or more tasks on E.
  - **B**: RRSI-lite.
    - Edit budget falls from 3 fields to 1 on a cosine schedule.
    - The keep threshold comes from placebo edits.
    - A leak check and a critic (32B; 20/20 on the planted-edit check) screen edits.
    - Pruning reverts fields that do not help.
  - **C**: random edits with A's keep rule (selection control).
- 10 generations × 3 candidates per arm.
- The proposer and critic are qwen2.5:32b-instruct. The student is qwen2.5:1.5b-instruct.
- Scoring uses Spider's official result comparison.

## Analysis plan (fixed before running)

- **Unit of analysis.** The seed. Per seed, compute the net tasks (improved minus regressed)
  for each comparison.
- **Primary endpoint.** Arm B vs Arm A on H. Test: exact two-sided Wilcoxon signed-rank
  across seeds, α = 0.05.
- **Secondary endpoints, Holm-corrected:**
  - A vs baseline on H; B vs baseline on H;
  - A vs C on E and on H; B vs A on B;
  - the selection gap (E gain minus E2 gain, in percentage points) for A, B and C.
- **Command:** `python -m rsi.pool runs_v4/s* --seed-level`.
- **Seed rules.**
  - If a seed crashes, rerun it from scratch with the same seed and report the crash.
  - Seeds are not replaced or dropped for their results.
  - If fewer than 10 seeds finish, report the analysis on the seeds that did, and say so.

## Predictions (means across seeds, in net tasks)

| Arm | E gain (of 100) | E2 gain (of 100) | H gain (of 322) | B gain (of 398) |
|---|---|---|---|---|
| A (unregularized) | +8 | +2 | -2 | 0 |
| B (RRSI-lite) | +4 | +2 | +1 | +1 |
| C (random search) | +6 | +1 | -1 | 0 |

1. **Primary (B vs A on H):** B is ahead by about 3 tasks on average. I predict the
   Wilcoxon test will not reach p < 0.05.
2. **Selection gap:** A's E gain minus E2 gain is positive in most seeds. I predict the
   gap is significant for A (Holm p < 0.05) and smaller for B, whose stricter threshold
   keeps fewer noise edits.
3. **A vs C:** A ≥ C on E by a couple of tasks, and no different on H. That is, the LLM
   proposer adds little over random search plus best-of-N selection in this
   9-knob edit space.
4. **Transfer:** neither arm's mean held-out gain (H or B) exceeds 1% of the set.

**Reasoning.** Runs 2-3 showed E gains of about +5 out of 50 with no held-out transfer. A
larger E (100) and fresh E2 tasks should show how much of that gain was selection noise.
A stronger proposer may find real gains such as few-shot examples, but those carry over
only partly from train to dev databases. B's stricter keep rule trades E gain for less
held-out damage, so it should do slightly better on H, by less than the minimum effect the
study can detect.
