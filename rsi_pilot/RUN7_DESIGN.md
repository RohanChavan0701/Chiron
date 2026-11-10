# Run 7 design: judge noise and the winner's curse in label-free selection

Status: DRAFT for the author's review. Nothing here has run. Predictions are in
`PREDICTION_run7.md` and are not registered until the author accepts them and they are
committed before launch.

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
