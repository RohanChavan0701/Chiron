# Predictions for run 8 (DRAFT, not registered)

**Status.** Draft written 2026-11-27 by the AI assistant at the author's request, before any
run-8 code or data exists. It becomes a pre-registration only when the author has confirmed or
edited every number and the file is committed and pushed before the first session starts.
Design: `RUN8_DESIGN.md`. Sessions: 3, seeds 20261501 to 20261503.

## Analysis plan (fixed before running)

- Unit: the session. Paired within session. Mean and SD across sessions; exact two-sided
  Wilcoxon reported but, with 3 sessions, the smallest p is 0.25, so no endpoint is called
  "significant"; readings use the pre-stated bands below.
- Primary: condition 3 (LoRA, baseline harness) minus condition 1 (base, baseline harness) on
  H, in pp.
- Secondary, Holm-corrected as one family on H: 2 minus 1, 3 minus 2, 4 minus 2. All four on
  B reported with the same statistics. Tokens per task per condition.
- A crashed session is rerun with the same seed. No session is dropped for its results.
- A harvest keep rate under 500 kept trajectories stops the run before training; reported as
  "not enough verified rollouts at this harness".

## Pre-stated readings for the primary (3 minus 1 on H, mean)

1. **At or above +9 pp (within 3 pp of the ablation's +11.6):** the adapter carries what the
   schema prompt carried; weights and prompt are interchangeable routes for this information.
2. **+3 to +9 pp:** partial transfer into weights; report as partial, no causal sentence.
3. **Under +3 pp:** the information did not move into weights at this data size and recipe;
   in-context delivery stays the working route. Say explicitly that one LoRA configuration was
   tried.
4. **Below -3 pp:** the adapter hurt; report the `describe`-before-`run_sql` diagnostic.

## Predictions (numbers to be confirmed or edited by the author)

| # | Quantity | Prediction |
|---|---|---|
| 1 | Primary, 3 minus 1 on H | +4 to +8 pp (reading 2). The adapter learns to call `describe` early more often, which recovers part of the schema effect, but not the full column list the prompt gave for free. |
| 2 | 2 minus 1 on H (replication under vLLM) | +9 to +14 pp, positive in 3 of 3. |
| 3 | 3 minus 2 on H | negative, -4 to -8 pp. |
| 4 | 4 minus 2 on H | within 2 pp of zero. The adapter adds nothing when the prompt already supplies the schema. |
| 5 | On B, 3 minus 1 | smaller than on H relative to the prompt route: under half of 2 minus 1 on B. |
| 6 | Tokens per task | condition 3 below condition 1 on H (fewer wasted steps), both below 2 on B. |
| 7 | Harvest keep rate on Spider train with `schema_only` | 55 to 70%. |
| 8 | `describe` before first `run_sql`, condition 3 versus 1 | at least 1.5x more often. |

## Reasoning

- The ablation measured the information's in-context effect exactly; run 8 holds the
  information fixed and varies the route. The adapter is trained on about 850 rollouts, each
  showing a correct query written with the schema visible but with the schema deleted from the
  training prompt; what it can learn is behaviour (fetch the schema, then write), not the
  schemas of held-out databases, which it never sees. So the prediction is partial transfer.
- Run 5 showed that gains transfer when the baseline lacks general information. A LoRA that
  learns "look before you query" is general; a LoRA that memorizes train-DB columns is not and
  cannot help on H or B.

## Deviations

None yet.
