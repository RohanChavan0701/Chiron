# Regularized RSI pilot (AgentWatch / Chiron)

**Question.** Does a self-improving harness loop tuned on Spider transfer to held-out
Spider databases and to BIRD, and does RRSI-style regularization change that?

**Status.** Pilot run once on 2026-11-02 (see Results): a null result.
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

Run on 2026-11-02 on one NVIDIA A10 (Lambda), Ollama 0.40.13, student `qwen2.5:1.5b-instruct`,
proposer and critic `qwen2.5:14b-instruct`. One seed, n=50 per set. Raw outputs:
`runs/results.md`, `runs/results.json`, `runs/audit.json`, `runs/arm_{A,B}/`, `splits.json`.

**Headline: a null result.** No comparison reaches p < 0.05, and no confidence interval
excludes zero or a loss. Arm B kept more of its E gain on held-out Spider than Arm A, but the
difference is one or two tasks.

| Harness | E (tuned on) | H (held-out Spider) | B (BIRD) | prompt tokens/task (H) |
|---|---|---|---|---|
| baseline | 48% | 20% | 10% | 321 |
| arm_A (unconstrained) | 62% | 26% | 8% | 428 |
| arm_B (regularized) | 58% | 28% | 12% | 606 |

| Comparison | E | H | B |
|---|---|---|---|
| A vs baseline | +14% [+0, +28], 10/3, p=0.092 | +6% [-6, +18], 6/3, p=0.51 | -2% [-12, +6], 2/3, p=1.0 |
| B vs baseline | +10% [+0, +20], 6/1, p=0.125 | +8% [-2, +18], 6/2, p=0.29 | +2% [-4, +8], 2/1, p=1.0 |
| B vs A | -4% [-16, +8], 4/6, p=0.75 | +2% [-4, +10], 2/1, p=1.0 | +4% [-6, +14], 4/2, p=0.69 |

Cells: delta, paired 95% bootstrap CI, improved/regressed tasks, exact McNemar p (uncorrected).
Transfer ratio (secondary): A: H 0.43, B -0.14; B: H 0.80, B 0.20.

**What evolution kept.** Arm A kept one edit (generation 2): a rewritten system prompt that
asks for "one or more SQLite queries", 1 sample row per table, and foreign keys turned off.
Arm B ended with one field changed, `sample_rows: 3`; pruning reverted `max_retries` because
removing it did not lower E. Arm B's leak check rejected 1 candidate and its critic 2. None of
Arm A's 15 candidates tripped the leak check.

**Audit: E passes are inflated.** Re-scored on Spider's test-suite databases, about half of the
E passes are false positives, many from gold queries that return no rows:

| Harness | E passes -> survive test suite | H passes -> survive |
|---|---|---|
| baseline | 24 -> 12 | 10 -> 8 |
| arm_A | 31 -> 16 | 13 -> 11 |
| arm_B | 29 -> 13 | 14 -> 10 |

Under the test suite, E gains shrink from +7 to +4 tasks (A) and +5 to +1 (B). E is a noisy
optimization target; this may matter more than the choice of arm. The two single-database
verifiers (AgentWatch and Spider's comparison) disagreed once in the whole run.
`runs/audit_bird_labels.csv` (BIRD passes to hand-label) has not been labeled yet.

**Noise floor.** Baseline on E three times at temperature 0: 25, 24, 24 (one task flipped), so
the keep threshold was 2 tasks.

**Leakage.** `runs/heldout_access.jsonl` shows non-baseline harnesses touched H and B only in
`rsi.heldout` and `rsi.audit`, after both arms had `final.yaml`.

### Deviations from the plan

- **Predictions were not registered.** `PREDICTION.md` was left blank and the run went ahead
  at the user's request, so there is no record that expectations preceded results.
- **Arm B was restarted.** The first Arm B run crashed in generation 2 when the student wrote two
  SQL statements and `sqlite3.Warning` escaped the executor (fixed in `rsi/sqlexec.py`). Arm B
  was rerun from generation 1; scored harnesses came from the cache, but the proposer is not
  seeded, so its proposals differ from the crashed run. The crashed log is kept in
  `runs/arm_B_crashed_run1/`. Arm A and the baseline never hit this path.
- **Few-shot pool.** Spider train and BIRD Mini-Dev share the `formula_1` database; its 80
  train examples were removed from the pool (`rsi/runner.py`). Neither final harness uses
  few-shot examples.
- **Proposer settings.** The proposer and critic used Ollama's default sampling with no seed and
  the server's default 4096-token context (prompts were about 3k tokens). Evolution is not
  exactly reproducible.

## Limitations

One seed, n=50 per set, one student model, one proposer model. Spider and BIRD are likely
in the student's pretraining data; this affects all arms equally but limits absolute claims.
