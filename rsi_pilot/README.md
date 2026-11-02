# Regularized RSI pilot (AgentWatch / Chiron)

**Question.** Does a self-improving harness loop tuned on Spider transfer to held-out
Spider databases and to BIRD, and does RRSI-style regularization change that?

**Status.** Pipeline built and tested on synthetic data only. No experimental results yet.
This is a pilot: n=50 per set, one seed, a 1.5B student.

Inspired by RRSI (Regularized Recursive Self-Improvement of Agent Harnesses, arXiv
2609.24972). This repo does not use RRSI's code; Arm B is a small reimplementation
of three of its ideas (edit-size budget that shrinks, a critic against
benchmark-specific edits, pruning edits that do not pull their weight).

## Design

| Set | Source | Role |
|---|---|---|
| E | 50 Spider dev tasks, hard/extra | Evolution only |
| H | 50 Spider dev tasks, hard, **from databases not in E** | Held out |
| B | 50 BIRD Mini-Dev tasks (SQLite) | Held out, different benchmark |

E and H are split by `db_id` because Spider dev has only 20 databases; a random split
would make H nearly the same test as E.

| Arm | Edits per candidate | Selection |
|---|---|---|
| A: unconstrained | Any number of fields | Best E score |
| B: regularized | At most 2 fields, 1 from generation 4 | Deterministic leak check + LLM critic reject benchmark-specific edits; after the run, revert any field whose removal does not lower E |

Both arms: 5 generations x 3 candidates, 10 failure traces shown per generation, and a
candidate is kept only if it beats the current harness on E by at least the noise floor
(spread across 3 baseline runs) + 1 task.

### Leakage controls

- The runner refuses to run any non-baseline harness on H or B until both arms have
  `final.yaml`, and logs every H/B evaluation to `runs/heldout_access.jsonl`.
- The proposer sees only E failures. Gold SQL is hidden from it by default
  (`show_gold_sql_to_proposer: false`).
- Few-shot examples come from Spider train only; the pool asserts it shares no
  database with E, H or B.
- Student temperature, seed, and whether BIRD's evidence hint is included are in
  `frozen.yaml` and cannot be edited by the loop.
- Arm A's edits are leak-checked too (logged, not enforced), so the README can report
  how often unconstrained evolution named benchmark identifiers.

### Verifier

The default verifier is AgentWatch's own checker (`../harness/evaluator.py`, imported,
not copied), as the plan specifies. It lowercases and string-casts values, allows no
column reordering, and compares duplicate-sensitive sorted lists (its docstring says
frozensets; the code sorts lists). The alternative, `verifier: spider_official`, is
Spider's comparison vendored from taoyds/test-suite-sql-eval (Apache 2.0): typed values,
column permutation allowed, bag semantics. Every task records both verdicts, and the audit
reports how often they disagree. Test-suite re-scoring always uses Spider's comparison.
Both check row order only when the gold query has ORDER BY. DISTINCT is kept.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

Data (not committed):

- `data/spider/`: `dev.json`, `train_spider.json`, `tables.json`, `database/<db_id>/<db_id>.sqlite`
- `data/bird_minidev/`: the Mini-Dev SQLite json and `dev_databases/<db_id>/<db_id>.sqlite`
- Optional for the audit: Spider test-suite databases (`database/` folder from test-suite-sql-eval)

Student: `ollama pull qwen2.5:1.5b-instruct` (confirm it matches the AgentWatch tag in
`frozen.yaml`). To run arms in parallel or use `--workers > 1`, start Ollama with
`OLLAMA_NUM_PARALLEL` set, and check the noise floor afterwards: parallel batching can
break determinism.

Proposer: free and local by default, `qwen2.5:14b-instruct` served by the same Ollama
instance as the student (`ollama pull qwen2.5:14b-instruct`), through Ollama's
OpenAI-compatible API. Fixed weights keep the run reproducible. It fits beside the student
on a 24 GB GPU such as an A10. A 14B proposer is much weaker than the frontier models the
RRSI and HarnessCompass papers used, so a null result may reflect proposer quality; say so
in the write-up. Alternatives in `frozen.yaml`: an OpenRouter free model (free models rotate
and are rate-limited; record the exact model name), or Claude via the Anthropic SDK.

## Run order

Run everything from `rsi_pilot/`; the AgentWatch verifier is imported from the repo root.

```bash
.venv/bin/python -m pytest -q                      # 32 plumbing tests, synthetic data
.venv/bin/python -m rsi.splits                     # writes splits.json
git add PREDICTION.md && git commit -m "Predictions"   # fill it in first
.venv/bin/python -m rsi.baseline                   # noise floor on E x3, baseline on E/H/B
.venv/bin/python -m rsi.evolve --arm A             # run A and B in two terminals
.venv/bin/python -m rsi.evolve --arm B
.venv/bin/python -m rsi.heldout                    # results.md, results.json
.venv/bin/python -m rsi.audit --testsuite-dir path/to/test-suite/database
```

`rsi.baseline` warns if the E baseline is outside 15% to 80%, if B is below 5% (then
rerun `rsi.splits --bird-fallback` and record it), or if a task takes over 2 s.

## Outputs

- `splits.json`, `runs/noise_floor.json`
- `runs/arm_{A,B}/log.jsonl`: every proposal, leak check, critic verdict, score and decision
- `runs/arm_{A,B}/final.yaml`, `summary.json`
- `runs/results.md`: accuracy per harness and set; deltas with paired 95% bootstrap CIs;
  improved/regressed counts; exact McNemar p for A vs baseline, B vs baseline, and B vs A
- `runs/audit.json`, `runs/audit_bird_labels.csv` (20 BIRD passes to hand-label)

## Reading the results

- Exact McNemar with n=50 needs at least 6/0 for p < 0.05 (5/0 gives 0.0625). Nine tests are
  reported uncorrected; treat a single p-value as weak evidence. A null is the expected outcome.
- Report raw gains with CIs first. The transfer ratio is secondary: E gain is the best of
  up to 15 candidates on the same 50 tasks, so it is inflated, and the ratio is reported as
  None when E gain is under 2 tasks.

## Results

Not yet run.

## Limitations

One seed, n=50 per set, one student model, one proposer model. Spider and BIRD are likely
in the student's pretraining data; this affects all arms equally but limits absolute claims.
