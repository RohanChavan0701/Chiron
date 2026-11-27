# Predictions for the run-5 schema-only ablation

**Status: draft, not registered until committed and pushed before the first ablation result.**

Date: TBD (the commit that registers this file).
Code: `rsi/ablate.py`, `ablations_v5.yaml`, `scripts/run_ablation.sh`, `scripts/run_ablation_all.sh`,
`tests/test_ablate.py`.

## Question

In run 5, all three arms reach about 58% on held-out Spider (H) from a 46.4% baseline, and
random edits (C) match the LLM proposer (A minus C: -1.3 tasks, -0.67 pp). Is the gain mostly
one field, `schema_upfront: full`? The baseline shows only table names in the first message.

## Design (fixed before running)

- **Harnesses.** The run-5 baseline (`harness_agent.yaml`) and `schema_only`: the baseline with
  exactly one field changed, `schema_upfront: tables -> full` (`ablations_v5.yaml`). The tool
  refuses any variant that changes zero or more than one field.
- **Sets.** H (a fixed 200 Spider-dev hard/extra tasks) and B (a fixed 200 BIRD Mini-Dev
  simple/moderate tasks), the same tasks as run 5. Splits are regenerated with
  `python -m rsi.splits`; before any evaluation, `python -m rsi.ablate check` aborts unless H
  and B have 200 tasks each and every H task id in run 5's `audit.json` test-suite flags is in H.
- **Replicates.** Six sessions, keyed to the run-5 seeds 20261211-20261216, each with that
  seed's run-5 environment (`frozen_v5_s<SEED>.yaml`, `runs_v5/s<SEED>`). The student seed is
  fixed and H/B do not depend on the seed, so for a fixed harness **the six seeds replicate the
  evaluation, not a search**: their spread is server nondeterminism (8 parallel slots). Run 5's
  baseline scored 96, 95, 91, 95, 93 and 87 of 200 on H across seeds.
- **Pairing.** In every session the baseline and `schema_only` are both evaluated fresh (no
  cache), on the same server. Order alternates by seed parity: even seeds baseline first, odd
  seeds `schema_only` first. The order is recorded.
- **Leakage.** The held-out guard in `rsi/runner.py` is unchanged. Every H/B access is logged to
  `runs_v5/s<SEED>/heldout_access.jsonl` with purpose `ablation_baseline` or `ablation_schema_only`.
- **Commands.** `scripts/run_ablation_all.sh 8`, then
  `python -m rsi.ablate report runs_v5/s2026121?` (writes `runs_v5/ablation_seed_level.md`).

## What was already seen before writing this

All run-5 results were known (README "Run 5", `runs_v5/summary.csv`). In particular:
- **One existing, post hoc data point for this exact harness.** Seed 20261214's arm B final
  harness is exactly baseline + `schema_upfront: full`. It scored 117/200 = 58.5% on H (that
  seed's baseline: 95/200, so +22 tasks, +11.0 pp) and 65/200 on B (baseline 41/200, +12.0 pp).
  Its tokens per task were 1,844 on H (baseline 2,033) and 4,720 on B (baseline 2,165).
- **7 of the 18 run-5 final harnesses do not set `schema_upfront: full`** (A in seeds 12, 15, 16;
  B in seed 12; C in seeds 12, 14, 15) and still scored 56.0% to 60.0% on H. So a schema-only
  result near 58% would show the full schema is **sufficient** for the gain, not that it is
  necessary.

## Analysis plan (fixed before running)

- **Primary endpoint.** `schema_only` minus the same-session baseline on H, per replicate, in
  net tasks and pp: mean and sample SD across the six replicates, exact two-sided Wilcoxon
  signed-rank over the six (`rsi.pool.wilcoxon_exact`). With 6 replicates the smallest possible
  p is 0.031, and it requires all six to agree.
- **Secondary.** The same on B. Tokens per task (variant / same-session baseline), on H and B.
- **Reference (unpaired).** `schema_only`'s mean next to run 5's arm means (A, B, C) from
  `runs_v5/summary.csv`. This is a different session: context, not a paired comparison.
- A session that crashes is rerun with the same seed. No session is dropped because of its results.

## Reporting commitment (written before results)

The per-replicate table is reported whatever it shows. Pre-stated readings, using the arms'
mean H gain over the run-5 baseline (+12.1 pp; A +11.8, B +12.0, C +12.4):

1. **`schema_only` H gain within 2 pp of the arms' mean gain (+10.1 to +14.1 pp):** "one field is
   sufficient for the gain; with 7 of 18 evolved harnesses reaching the same level without it,
   the edit space has several cheap routes to the same ceiling, which is why random edits match
   the proposer."
2. **`schema_only` H gain under half the arms' gain (under +6.0 pp):** "the gain needs more than
   the schema; the cause is still open."
3. **In between (+6.0 to +10.1 pp):** report as partial, no causal sentence.

4. **More than 2 pp above the arms' mean gain (over +14.1 pp):** "one field alone does at least
   as well as the evolved harnesses; the other kept edits added nothing measurable on H." No
   claim that they hurt, since the arm means come from a different session and hardware.

## Predictions

1. `schema_only` H gain over the same-session baseline is +10 to +13 pp (mean), positive in 6 of 6
   replicates. (proposed, owner to confirm)
2. On B (BIRD), the gain is positive but smaller than the evolved arms' mean B gain (+16.3 pp).
   (proposed, owner to confirm)
3. On H, tokens per task within 15% of the same-session baseline. H only: the seed-20261214 data
   point above was -9% on H but 2.2x the baseline on B, where schemas are larger, so on B the
   prediction is 1.5x to 3x the baseline. (proposed, owner to confirm)

## Hardware

One Vultr cloud GPU instance, plan `vcg-a100-12c-120g-80vram` (1x NVIDIA A100 80 GB), chosen by
the owner on 2026-11-27. All six replicates run on that one instance in one launch. Ollama
0.40.13 and 8 parallel slots, as in run 5; the student model digest is recorded in the run logs.

This differs from run 5 (Lambda 1x A10). So only the paired same-session comparison
(`schema_only` minus the baseline scored in the same session) is evidence. The run 5 arm means
are context only, and the fresh baseline's mean on this hardware is reported next to run 5's
46.4% so any hardware shift is visible.

## Deviations

