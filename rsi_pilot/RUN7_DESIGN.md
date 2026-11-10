# Run 7 design: judge noise and the winner's curse in label-free selection

Status: RUN COMPLETE (2026-11-10). Predictions were registered in `PREDICTION_run7.md` before
launch. Results and the verdict on each prediction are at the end of this file.

## Where this comes from

Run 6 stage 1 (`RUN6_DESIGN.md`, exploratory) tested whether a loop that selects harness edits
on a label-free judge turns into a reward hacker. It did not: the kept edit carried no more
persistent judge bias than a random one. What selection did concentrate was noise. Under the
reference-free judge the winner's curse was 1.6 to 1.7 times the curse under truth selection,
and the variance model predicted 1.4 to 1.6. Run 7 is the confirmatory test of that one effect.

## Claim

When a self-improvement loop picks the best of k candidate edits using a judge instead of
labels, the reported gain is inflated by a winner's curse of size

    curse ≈ c_k * sqrt(r / m)

where m is the number of selection tasks, c_k is the expected maximum of k standard normals,
and r is the residual (edit x task) variance of the selector's per-task gain. For truth
selection r = r_tt. For judge selection r = r_pp, which adds the judge's per-task error to the
student's. So

    curse multiplier = curse(judge) / curse(truth) ≈ sqrt(r_pp / r_tt)

Two consequences that run 7 checks:

1. The multiplier is predictable from the bank's variance components, without running a loop.
2. It tracks the judge's residual variance, not its accuracy. A judge that approves nearly
   everything is a poor judge with a small curse. A judge that disagrees with truth on 30% of
   episodes in both directions has a large one.

Prior work: 2610.09239 measures the winner's curse under true-metric selection with LLM
proposers. It does not cover judge selection or decompose the judge's share. Run 5 of this
repo showed random edits match an LLM proposer under truth selection.

## What is new relative to run 6

| | Run 6 stage 1 | Run 7 |
|---|---|---|
| Status | exploratory | pre-registered |
| Tasks | 150, two anchors | 300 fresh, one anchor |
| Selectors | truth, P1, P2 recompute | plus P2 verdict (high approval, low AUROC) |
| Judge repeat | none | judge re-run on a fixed subset of harnesses |
| Uncertainty | none on the multiplier | bootstrap over tasks (edits fixed); joint as secondary |
| Replay decomposition | changed mid-analysis | frozen before launch |

## Setting

- Domain: FinQA dev, 300 tasks, seed 20261403, disjoint from the 250 used in run 6. FinQA is
  public and may be in the student's pretraining data; the claim is about selection noise, which
  does not depend on the student having seen the tasks, but every number carries that caveat.
- Student `qwen2.5:7b-instruct`, judge `llama3.1:8b`, Ollama 0.40.13, same as run 6.
- Anchor: the weak anchor only (`rsi/fin_edits.py::WEAK`). Tradeoff: one anchor on 300 tasks
  gives a tighter multiplier than two anchors on 150; the cost is no second-anchor replication
  inside the run. Run 6 already showed the two anchors agree.
- Edits: the 40-edit hand-written catalog, unchanged. Tradeoff: LLM-proposed edits would make
  the edit set less hand-picked, but the proposer is untested and would add about 2.5 h. Left
  as a follow-up.
- Baseline: 3 repeats.

## Measurements

1. Bank: 43 harness runs x 300 tasks, graded by truth, P1, P2 recompute.
2. Regrade all 43 with the P2 verdict prompt (judge calls only).
3. Judge repeat: re-run the P2 recompute judge on the same stored episodes for the 3 baselines
   and 10 edits (the first 10 in catalog order, fixed now). This splits the judge's per-task
   error into a part that changes when the judge is asked again and a part that does not.
   It decides whether averaging repeated judgements can shrink the curse.

## Analysis (frozen)

- Replay: `rsi.replay.replay` as committed in 8caf360, greedy rule, k = 8, m = 150 (half the
  tasks), 3000 rounds. Curse = mean `noise`. Multiplier = curse(selector) / curse(truth).
- Theory: sqrt(r_cc(selector) / r_cc(truth)) from `rsi.goodhart.components`.
- Interval (registered): 1000 bootstrap resamples of tasks, edit catalog fixed, percentile 95%.
  The claim is therefore about this set of 40 edits. Secondary, reported but not a criterion:
  the same with tasks and edits resampled jointly.
  Implementation (`rsi.run7.curse_boot`, checked against `rsi.replay.replay` in the tests): a
  resampled task carries its multiplicity as a weight and the selection/fresh split is made
  over the original tasks, so a task never sits on both sides. 400 replay rounds per resample.
  Weighting halves the effective number of selection tasks, so the interval for the curse in
  points is too high and is not reported as a result; the multiplier is a ratio of two curses
  on the same resample and is the registered quantity.
- Goodhart check: mean persistent `bias` of the greedy winner minus that of the random rule.
- Secondary grid, descriptive only: k in {4, 8, 20, 40}, m in {25, 75, 150}.
- Config `frozen_v7.yaml`; remote script `cloud/run7_remote.sh`; analysis `python -m rsi.run7
  analyze` on the laptop. Tests `tests/test_run7.py`.

Power check on run 6 stage 1 data (150 tasks, m = 75, 300 resamples), done before launch:
the joint interval for the P2 multiplier was 1.05 to 2.40 (weak) and 1.01 to 2.61 (strong);
resampling tasks only gave 1.17 to 2.07 and 1.20 to 2.44. Doubling the tasks narrows the task
part but not the part that comes from having 40 edits. For that reason the registered interval
resamples tasks only (amended 2026-11-10, before registration and before any run 7 data).

## Stop rules and cost

One A10, same guardrails as `CLOUD_RUN.md`. Estimate: bank 6.3 h, verdict regrade 1 h, judge
repeat 1.1 h, setup 0.3 h: about 8.7 h, about $11.20. Cap requested: $15, 11.6 h. If the bank
is not done by hour 9, skip the judge repeat first, then the verdict regrade. A launch needs
the author's go-ahead.

## Known weaknesses

- The effect is moderate and the theory is a standard order-statistics argument. This is a
  careful measurement with a practical recommendation, not a surprising result.
- One domain, one student, one judge model. No claim beyond this setting.
- Hand-written edits with almost no real headroom. The curse is the whole reported gain here;
  in an edit space with real improvements its share would be smaller.
- A single run per edit, so student run-to-run noise and edit x task interaction are not
  separated. The judge repeat separates only the judge's part.
- Predictions were drafted after seeing run 6 stage 1, on the same catalog and anchor. The
  fresh tasks are what make run 7 confirmatory.

## Results (2026-11-10, registered analysis)

Run: one A10 (`chiron-run7`, us-west-1), 09:48 to 18:44 UTC, 8.9 h, est $11.52, terminated at
job end. 43 harness runs on 300 fresh FinQA dev tasks, none skipped; verdict regrade on all 43;
judge repeat on 13. Numbers: `runs_v7/analyze.json`. FinQA is public and may be in the
student's pretraining data. One domain, one student, one judge model, 40 hand-written edits.

Baseline truth at the weak anchor: 51.0 / 52.0 / 51.7%.

Greedy best of 8 edits on 150 selection tasks, 3000 replay rounds (points):

| Selector | Agrees with truth | Approves | Reported | Real | Persistent bias | Curse | Multiplier | Theory |
|---|---|---|---|---|---|---|---|---|
| Truth | 100% | 53% | +5.1 | +2.4 | 0 | +2.7 | 1.00 | 1.00 |
| P1, judge with reference | 90% | 58% | +5.3 | +2.5 | 0.0 | +2.8 | 1.06 | 1.07 |
| P2, recompute judge | 74% | 57% | +5.8 | +2.3 | -0.1 | +3.6 | 1.36 | 1.37 |
| P2 verdict judge | 62% | 88% | +3.9 | +2.6 | -0.4 | +1.7 | 0.64 | 0.87 |

95% intervals for the multiplier, tasks resampled with the catalog fixed (registered): P1 0.86
to 1.35, P2 1.06 to 1.82, P2 verdict 0.49 to 1.08. Tasks and edits resampled (secondary): P2
0.95 to 1.96.

### Predictions

| | Prediction | Result | Verdict |
|---|---|---|---|
| H1 (primary) | P2 multiplier 1.3 to 2.0, interval lower bound above 1.15; fails at or below 1.0 | 1.36, interval 1.06 to 1.82 | **Inconclusive.** Point estimate in range (at its low edge), lower bound between the fail line and the pass line |
| H2 | Multiplier within 25% of sqrt(r_pp / r_tt) | 1.36 observed, 1.37 predicted | Holds |
| H3 | Winner's bias within 1.5 points of a random pick's, interval includes 0 | +0.7 points, interval -0.8 to +2.1 | Holds |
| H4 | P1 multiplier 0.6 to 1.25 | 1.06 | Holds (also inside the draft's 0.8 to 1.25) |
| H5 | Verdict judge has a smaller multiplier than recompute | 0.64 versus 1.36 | Holds |
| H6 | P2 winner's real gain at or below zero, and not above the truth-selected winner's | +2.3 points; truth-selected +2.4 | **Fails** on the first clause, holds on the second |

### Reading

1. The extra curse from judge selection is real in direction and matches the variance formula
   to within a point, but it is smaller than run 6 suggested (1.36 against 1.6 to 1.7) and the
   primary criterion was not met. The exploratory estimate shrank on fresh data, as such
   estimates do.
2. Most of the inflation is not the judge's. Selecting on truth itself reports +5.1 for a real
   +2.4. The recompute judge adds about one more point of curse. The practical rule is the
   same for labels and judges: re-score the winner on tasks it was not selected on.
3. Curse tracks the judge's residual variance, not its accuracy (H5). The verdict judge agrees
   with truth least (62%) and approves 88% of answers, so its scores barely vary and its curse
   is below truth selection's. The formula is less exact there (0.87 predicted, 0.64 observed),
   and the secondary grid shows the verdict multiplier falling as m grows.
4. No Goodhart amplification, again (H3). Selection did not concentrate judge bias.
5. H6 failed because run 7's edits have real headroom: 32 of 40 raise truth, and every
   selector's winner gains about 2.3 to 2.6 points for real. Run 6 stage 1 found almost none
   on 150 tasks at the same anchor. So judge selection did not pick worse edits than truth
   selection here; it reported a slightly more inflated number for an equally good edit.
6. Judge repeat (descriptive): asked again about the same 3,900 stored episodes, with
   temperature 0 and the same seed, the recompute judge changed its verdict on 11.8%, and on
   20.9% of the episodes where it had disagreed with truth. Part of the judge's noise is
   therefore re-ask instability under batched serving, which averaging repeated judgements
   would reduce. How much of the curse that removes was not measured.

### Deviations in the analysis

- The registered analysis was started when 10 of the 13 judge-repeat harnesses had finished,
  to save wall time. The bank and the verdict regrade were complete, and no registered
  quantity uses the repeat grades. The `judge_repeat` block in `analyze.json` was recomputed
  afterwards on all 13.
- The point multiplier comes from 3000 replay rounds; the secondary grid's k = 8, m = 150 cell,
  from a different random stream, gives 1.32. Monte Carlo error is about 0.03, so "inside 1.3
  to 2.0" is marginal.
- Run-time deviations (hardware, server settings, P2-only regrades, a 12 minute setup stall)
  are in `PREDICTION_run7.md`.
