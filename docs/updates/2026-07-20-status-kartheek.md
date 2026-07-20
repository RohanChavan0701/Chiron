# Status Update — Agent Self-Improvement (RSI-Mem)

**To:** Kartheek
**From:** Rohan Chavan
**Date:** 2026-07-20
**Repo:** `agent-self-improvement`

## One-paragraph summary

We are building a runtime self-improvement layer for AI agents: a weak "student" model fails on hard work, a stronger "teacher" converts those failures into reusable memory (playbooks, trap-avoidance rules, worked examples), and the same student — with that frozen memory, no fine-tuning — performs better on new, held-out problems. The coding-domain phase is complete and produced a decisive (and publishable) negative finding that reshaped the plan; we have now pivoted to an expert-reasoning benchmark (FinancePro-Bench, 400 rubric-graded finance questions) where the memory mechanism has a structurally better fit, executing a 20-week research plan with pre-registered success bars and kill criteria.

## What we proved in the coding phase (completed)

All numbers from real runs, multi-repeat, committed in `docs/FINDINGS_CODING.md`:

1. **The pipeline works mechanically.** Drift detection fires, teacher repairs verify against unit tests, memory reaches the student's prompts (confirmed by a per-run injection audit we built).
2. **Student capacity is a hard precondition.** A 3B student cannot absorb teaching on hard problems (p ≈ 0.0000 vs a strong model on identical questions).
3. **The key negative result: teacher-verified memory is not automatically useful.** On two capacity-adequate students, the same memory bundle produced zero effect on one (confirmed across 4 repeats) and a *deterministic −26.5 point* accuracy drop on the other (identical across 3 repeats). Correct examples ≠ helpful examples.
4. **Measurement discipline established.** We quantified provider-side nondeterminism (deltas under ~6 points are noise on our stack) and now require ≥3 repeats + paired statistics before believing any effect.

Finding #3 is the scientific core going forward: memory items must be admitted by **measured student improvement** ("uplift gating"), not by teacher correctness. No published system in our reference set does this — it is our novel mechanism.

## Current phase: FinancePro-Bench (started today)

Why this benchmark: 400 expert finance questions with point-based rubrics that *name* specific analytical traps (T1–Tn penalties). Traps are explicit, recurring, and category-structured — the ideal target for a "trap registry" memory artifact. Continuous rubric scores also give a denser training/evaluation signal than binary unit tests.

**Plan:** `docs/RSI_MEM_V2_FINANCE.md` — 6 phases / 20 weeks, success bar = +4 normalized points on held-out with p < 0.05, AND real memory must beat a style-only placebo (guards against the model learning to "sound rubric-y" instead of reasoning better).

**Progress today (Phase 0):**

| Item | Status |
|---|---|
| Dataset cached, licensed (CC-BY-4.0), splits frozen 200 train / 80 validation / 120 held-out, category-stratified, seed-pinned | ✅ Done, committed |
| Rubric firewall (students can never see grading rubrics — enforced by tests, not convention) | ✅ Done |
| LLM judge harness (rubric-following grader, strict output parsing, judge ≠ teacher to avoid self-preference bias) | ✅ Code done, tested |
| Judge reliability check (grade 40 answers twice; gate: mean absolute difference ≤ 5 points or the benchmark is unusable at our effect size) | 🔄 Running — answer generation ~90% done |
| Student model selection by measured headroom + held-out baselines | Next |

## Working model

Two-agent workflow: Claude (Fable) owns research planning, work orders, statistical review, and honesty enforcement; Cursor executes implementation tasks against those work orders. Every live result is independently re-verified before acceptance.

## Risks being managed

- **Judge noise / judge gaming** — reliability gate before any baselines; placebo-memory control arm; the judge never knows which arm produced an answer.
- **Small data budget** (400 questions total) — frozen splits, held-out touched exactly once per evaluated arm, paired bootstrap statistics.
- **Pre-registered kill criteria** — if the judge is too noisy, if real memory can't beat placebo, or if the largest affordable student still shows no lift, the plan says exactly what we do next (including the honest negative-result write-up path).

## Next 2 weeks

1. Judge reliability gate → student headroom probe → held-out baselines (Phase 0 exit).
2. Trap census + failure taxonomy on training-stream failures (Phase 1) — determines whether the trap registry or the playbooks carry Phase 2.
3. First uplift-gated memory build and validation-slice measurement.

Happy to walk through the findings docs or the plan in detail.
