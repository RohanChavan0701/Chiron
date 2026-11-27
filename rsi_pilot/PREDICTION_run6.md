# Predictions for run 6 (DRAFT, not yet pre-registered)

**STALE as of 2026-11-09.** The author is moving the experiment from text-to-SQL to finance
reasoning (`HACK_AUDIT.md`, "Domain pivot"). Every number below is for the SQL version and must be
rewritten once the substrate is chosen. Do not commit this file as a pre-registration.

**Status.** Draft written on 2026-11-09. It becomes a pre-registration only when it is committed and
pushed before any run-6 baseline, evolution or held-out result exists. Record the commit hash and
push time here when that happens. Payoff calibration (design file, step 0) is allowed before the
commit and its numbers must be added below first.

**Who wrote this.** The AI assistant wrote these predictions at the author's request, before any
run-6 code or result existed. The author should edit the numbers or state that he did not.

Design: `HACK_AUDIT.md`. Seeds 20261311 to 20261316.

## Analysis plan (fixed before running)

- Unit of analysis: the seed. Exact two-sided Wilcoxon signed-rank over 6 seeds, alpha 0.05.
  With 6 seeds, p < 0.05 requires every seed to agree (p = 0.031).
- Primary endpoint: channel K3, proxy-only passes on E (final harness minus baseline harness),
  Arm A minus Arm C.
- Secondary endpoints as listed in `HACK_AUDIT.md`, Holm-corrected.
- A crashed seed is rerun with the same seed. No seed is dropped because of its results.
- Held-out H and B are scored with the true comparison only.

## Arm C's blind prior (computed, not predicted)

Arm C changes 1 to 3 of the editable fields per candidate, uniformly, over 24 candidates per seed.

| Channel | Fields | P(candidate carries exploit) | P(at least one of 24 carries it) |
|---|---|---|---|
| K1 (`answer_check` flip, while still `exact`) | 9 | 2/9 = 0.22 | 0.998 |
| K3 (over-broad entry, 1 of 6 other `rules` options) | 8 | 2/8 x 1/6 = 0.042 | 0.64 |

These assume the field counts above and must be recomputed by `rsi/edits.py` once the code exists.

## Predictions

| # | Quantity | Prediction |
|---|---|---|
| 1 | **Primary.** K3, proxy-only passes, A minus C | Negative: C ahead by about 2 tasks of 50. Not significant (p > 0.05). |
| 2 | K3, seeds whose final harness carries the exploit | C: 3 of 6. A: 1 of 6. B: 0 or 1 of 6. |
| 3 | K3, `P(propose)` for Arm A | Under 0.02 per candidate, below C's 0.042. The proposer sees failures, not the scorer, and writes advice aimed at correct answers. |
| 4 | K1, seeds whose final harness has `answer_check: tolerant` | C: 6 of 6. A: 4 of 6. B: 5 of 6. |
| 5 | K1, `P(keep \| proposed)` | Above 0.8 in every arm, no difference between A and C. |
| 6 | K1, Arm B checks that fire on the flip | Critic flags it in under 20% of cases; leak check never; the placebo threshold passes it because the gain is real on the proxy. |
| 7 | K2 (gold shown), seeds whose final harness has `leak_problems` | A: 3 of 6. B: 0 of 6. |
| 8 | Displacement on H (true gain in channel cell minus clean cell, same seed and arm) | K1: about -2 tasks of 200 for A and C, not significant. K3: about 0. |
| 9 | Clean cell, true H gain over baseline | Replicates run 5: +15 to +30 tasks of 200 for every arm, 6 of 6 seeds positive. |
| 10 | N, proxy-only passes under the test suite at dose 20 of 50 | Final minus baseline within 1 task for A and C. No systematic exploitation of empty-gold tasks. |
| 11 | Rationale audit, Arm A's kept exploit-carrying edits in K1 | Fewer than half of the rationales mention that the check became easier. |
| 12 | K3 with the scorer described to the proposer (step 6) | A carries the exploit in 4 of 6 seeds, up from 1 of 6. |

## Reasoning

- Run 4 and run 5 both found the 32B proposer no better than random edits at raising the tuning
  score. There is no reason to expect it to be better at finding a scorer flaw it cannot see, so
  for K3 the blind prior should win unless the proposer is told about the scorer (prediction 12).
- K1 is one binary flip with a payoff calibrated to at least 5 tasks. Arm C will draw it in nearly
  every seed and the keep rule needs only +1. The proposer may leave it alone in some seeds because
  nothing in the failure traces points at it.
- Arm B's checks ask about benchmark-specific text and noise. A scorer-facing setting is neither.
- Run 5 seed 1 showed Arm A writing tuning-set columns into `rules` with gold hidden. With gold
  shown this should be more frequent, and the leak check is built for exactly this.
- The exploit gain is a one-time step in E. Later real edits still clear the +1 keep rule on top of
  it, so displacement should be small.

## Calibration record

Not run yet. Add here, before the pre-registration commit: smoke seed, the three hand-written
harnesses, proxy and true scores for each, and every change made to the flaw.

## Deviations

None yet.
