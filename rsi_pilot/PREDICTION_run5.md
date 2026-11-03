# Predictions for run 5 (committed BEFORE any run-5 result exists)

**Who wrote this.** The AI assistant (Claude) wrote these predictions at the user's request,
before any run-5 baseline, evolution or held-out result existed. The user did not write or
edit them.

Date: 2026-11-03.
Code: the commit that adds this file (`frozen_v5.yaml`, `rsi/agent.py`, `scripts/run_v5*.sh`).
**Smoke tests already run.** On seed-20261211 tuning tasks, the baseline agent scored 34, 36
and 35 out of 60. Those tasks came from a 60-task split; run 5 uses 50.

**Status of run 4.** Run 4 is paused during seed 1 to free the GPU. It will be resumed later
under its own pre-registration (PREDICTION.md).

## Design (fixed before running)

Run 5 uses the run-4 design with these changes:
- **Student and harness.** The student is a multi-step SQL agent on qwen2.5:7b-instruct
  (`rsi/agent.py`). Each turn it calls one of list_tables, describe, run_sql or submit.
- **Editable fields.**
  - Text: system_prompt, tool_guide, rules (a memory shown before every task).
  - Settings: schema_upfront, describe_sample_rows, result_preview_rows, max_steps,
    verify_before_submit.
- **Seeds and splits.** 6 seeds, 20261211 to 20261216.
  - E: 50 Spider-train hard/extra tasks.
  - E2: 50 fresh tasks from the same databases.
  - H: a fixed 200 of the 322 eligible Spider-dev hard/extra tasks.
  - B: a fixed 200 of the 398 BIRD Mini-Dev simple/moderate tasks.
- **Run length.** 8 generations × 3 candidates per arm.
- **Arms.**
  - **A:** keeps any E gain of 1 or more.
  - **B:** cosine edit budget falling from 3 to 1, keep threshold set by placebo edits,
    leak check, a 32B critic that reads the rules field, and pruning.
  - **C:** random edits from generic menus, with A's keep rule.
- **Infrastructure.** The student is served by a second Ollama server with 8 parallel slots.
  In the smoke test, identical runs flipped 5 or 6 of 60 tasks, with net scores 34 to 36.
  This noise counts toward the placebo threshold.

## Analysis plan (fixed before running)

The same as run 4: `python -m rsi.pool runs_v5/s* --seed-level`.
- Primary endpoint: B vs A on H, net tasks per seed, exact two-sided Wilcoxon over 6 seeds,
  α = 0.05. With 6 seeds the test can reach p < 0.05 only if every seed points the same way
  (p = 0.031).
- Secondary endpoints are as in run 4, with Holm correction.
- A seed that crashes is rerun with the same seed. No seed is dropped because of its results.

## Predictions (mean net tasks across seeds)

| Arm | E (of 50) | E2 (of 50) | H (of 200) | B (of 200) |
|---|---|---|---|---|
| A | +5 | +1 | -2 | -1 |
| B | +2 | +1 | +1 | 0 |
| C | +3 | 0 | 0 | 0 |

1. **Primary.** B is ahead of A on H by about 3 tasks. The test does not reach p < 0.05.
2. **Selection gap.** The E minus E2 gap is positive for A in at least 5 of 6 seeds.
   I predict it is larger than in run 4, because the agent's scores are noisier.
3. **Leakage.** In at least 2 of 6 seeds, Arm A keeps an edit to `rules` or a prompt that
   names a tuning-set table or column (`leak_problems`). Arm B rejects such edits.
4. **Transfer.** Neither arm's mean gain on H or B exceeds 2% of the set.

**Reasoning.** The agent harness has free-text memory and prompts. That gives an
unregularized proposer room to write tuning-set-specific advice, which is the overfitting
RRSI targets. With E at 50 tasks and agent noise of about ±5 tasks, most E gains will be
selection. B's critic and placebo threshold should block both the leaks and the noise edits,
but probably not by enough to detect at n = 200 with 6 seeds.
