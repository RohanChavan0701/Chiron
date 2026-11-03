# RULE: Provenance & scope

## Origin
Chiron began as a hackathon build (first commit 2026-07-01). The four-stage loop
(`harness/`, `detector/`, `correction/`, `viewer/`) and `orchestrator.py` were built
in that window. Everything after (coding/GSM8K/finance adapters, `docs/FINDINGS_*.md`,
`rsi_pilot/`) is follow-on research on the same codebase. Do not describe the repo as
a single-day build; the git history is the record.

## What the project is
Drift detection plus automated self-correction for a small language model, evaluated
with held-out splits. The text-to-SQL agent is scaffolding. The loop and the
measurement discipline (frozen splits, leakage log, test-suite re-scoring, paired
statistics, pre-registration) are the work.

## What the viewer is
A thin window onto `events.jsonl`. It is not the product and should stay minimal.
No Streamlit.

## Claims
- Report held-out numbers before tuning-set numbers.
- Report nulls. `rsi_pilot/README.md` is the model: deltas with paired CIs, exact
  McNemar p uncorrected, improved/regressed counts, and a deviations section.
- Spider 1.0 is likely in every student's pretraining data. Say so wherever a Spider
  number appears, and prefer BIRD or test-suite re-scored results for any transfer claim.

## Rights
Spider and BIRD are public research benchmarks. `rsi_pilot/third_party/spider_eval/`
is vendored from taoyds/test-suite-sql-eval under Apache 2.0 with its LICENSE. Do not
add assets without a compatible license.
