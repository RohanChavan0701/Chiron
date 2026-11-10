# Run 7 predictions

Status: REGISTERED 2026-11-10 by the commit that adds this file, before the run 7 instance is
launched and before any run 7 data exists. The numbers were proposed in a draft, accepted by
the author, and amended twice before registration (see "Changes before registration").
Design: `RUN7_DESIGN.md`.

Basis for the proposed numbers: run 6 stage 1 (exploratory, 150 tasks, same catalog), where the
P2 recompute multiplier was 1.72 (weak anchor) and 1.58 (strong) at k = 8, m = 75.

All quantities use the frozen analysis in `RUN7_DESIGN.md`: greedy replay, k = 8, m = 150,
300 fresh FinQA dev tasks, weak anchor, 40 catalog edits.

## Primary

**H1. Judge selection inflates the winner's curse.**
Curse multiplier for P2 recompute versus truth selection: point estimate between 1.3 and 2.0,
bootstrap 95% interval lower bound above 1.15. The interval resamples tasks with the edit
catalog fixed, so H1 is a claim about this set of 40 edits. The interval that also resamples
edits is reported as secondary and is not a criterion.
Fails if the lower bound is at or below 1.0, or the point estimate is outside 1.3 to 2.0.

## Secondary

**H2. The multiplier is predictable from variance components.**
Observed multiplier within 25% of sqrt(r_pp / r_tt).

**H3. No Goodhart amplification.**
Persistent bias of the greedy P2 winner minus persistent bias under the random rule: absolute
value below 1.5 points, 95% interval includes 0.

**H4. A judge with a reference adds little curse.**
P1 multiplier between 0.6 and 1.25.

**H5. Curse tracks judge variance, not judge accuracy.** (low confidence)
The P2 verdict judge, which had lower AUROC than recompute in run 6 stage 0 (0.55 versus 0.69)
but approves about 92% of answers, has a smaller multiplier than P2 recompute.

**H6. Real gain of the selected edit.**
The greedy P2 winner's real gain on fresh tasks is at or below zero (point estimate), and not
above the truth-selected winner's real gain.

## Descriptive, no prediction

- Share of the judge's per-task error that changes when the judge is asked again (judge repeat).
- Multiplier across the secondary grid of k and m.
- Per-source breakdown (placebo, style, substance, targeted, structural).

## What each outcome would mean

- H1 and H2 hold: label-free selection has a predictable extra curse; report the formula and
  the recommendation to re-score winners on fresh tasks before reporting gains.
- H1 fails low (multiplier near 1): the run 6 effect was itself a noise winner. Report as null.
- H3 fails (bias amplified): the Goodhart claim from run 6 comes back on fresh tasks; report
  both, and say run 6 stage 1 missed it.
- H5 fails: the variance account is incomplete; report what the verdict judge did.

## Changes before registration

Both were made after a power check on run 6 stage 1 data and before any run 7 data.

1. H1 interval: the draft resampled tasks and edits jointly. On run 6 that interval's lower
   bound was 1.05 (weak anchor) and 1.01 (strong) with point estimates of 1.72 and 1.58, and
   more tasks do not shrink the part due to having 40 edits. Tasks-only gave 1.17 and 1.20.
   Cost: H1 no longer speaks to edits outside the catalog.
2. H4 range: the draft said 0.8 to 1.25. The run 6 weak-anchor value was 0.77, so the draft
   range was already contradicted by data in hand. Widened to 0.6 to 1.25.

## Deviations

Any change after registration is logged here with its reason.

1. Hardware (2026-11-10, before launch, no run 7 data yet): the author approved one H100 for
   this run to get results sooner, but none had capacity, so the run is on the A10 named in the
   design after all. The exception stays in `CLOUD_RUN.md` and `lambda_api` and was not used.
2. Speed changes (2026-11-10, before launch, no run 7 data yet), at the author's request to make
   the A10 run faster. Models, prompts, seeds, sampling settings, tasks and the analysis are
   unchanged.
   - Ollama server: 8 parallel request slots (run 6 used 6), flash attention on, models kept
     loaded. Slot count and attention kernel change how requests are batched and computed, and
     run 6 showed batching moves individual student answers slightly, so run 7 is not a
     bit-for-bit continuation of the run 6 setup. The registered quantities compare selectors
     within run 7 and do not depend on that. If 8 slots do not fit on the GPU the run falls
     back to 6.
   - Verdict regrade and judge repeat ask only the P2 judge again. P1 and P3 are copied from
     the main grades, since they do not depend on the P2 prompt. The judge repeat therefore
     reports a flip rate for P2 only.
