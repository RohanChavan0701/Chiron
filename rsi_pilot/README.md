# Regularized RSI pilot (AgentWatch / Chiron)

**Question.** Does a self-improving harness loop tuned on Spider transfer to held-out
Spider databases and to BIRD, and does RRSI-style regularization change that?

**Status.** Run five times on 2026-11-02 (runs 1-3). Run 1 (see Results): a null result. Run 2, after a critique of
run 1 (see Run 2): B vs A on H p=0.049 uncorrected. Run 3, three replicates of run 2: that result
did not replicate; tuning-set gains reliably fail to transfer in both arms (see Run 3).
This is a pilot: n=50 per set, a 1.5B student; runs 1 and 2 use one seed each, run 3 adds three.

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

## Run 2: after the critique of run 1

Same day, same models, run with `RSI_FROZEN=frozen_v2.yaml RSI_SPLITS=splits_v2.json
RSI_RUNS=runs_v2`. Run 1's files are untouched. Changes (all in `frozen_v2.yaml`):

- Proposer through Ollama's native API with fixed temperature (0.7), seed and a 16k context.
- Critic is a different model family, `llama3.1:8b` (temperature 0), not the proposer.
- Both arms see a history of earlier candidates and their E scores.
- Arm B pruning also reverts a field whose E gain is under the keep threshold and that makes
  the harness 1.25x more expensive.
- Splits: at most 6 tasks per database (E now spans 10 databases, H 9; 5 was infeasible) and
  tasks whose gold query returns no rows are excluded. E, H and B are therefore different
  task sets from run 1, so compare conclusions, not numbers.
- Noise floor from 5 baseline runs instead of 3.

Predictions were again not registered. Several run-2 E databases (car_1, museum_visit,
network_1) were run-1 H databases; the run-2 proposer saw only run-2 E failures, but the
run-2 changes were designed after looking at run 1's results.

| Harness | E | H | B | prompt tokens/task (H) |
|---|---|---|---|---|
| baseline | 40% | 58% | 6% | 361 |
| arm_A (unconstrained) | 48% | 46% | 6% | 2995 |
| arm_B (regularized) | 50% | 64% | 10% | 2330 |

| Comparison | E | H | B |
|---|---|---|---|
| A vs baseline | +8% [-6, +24], 9/5, p=0.42 | -12% [-28, +4], 6/12, p=0.24 | +0% [-8, +8], 2/2, p=1.0 |
| B vs baseline | +10% [-8, +28], 13/8, p=0.38 | +6% [-6, +18], 7/4, p=0.55 | +4% [-4, +12], 3/1, p=0.63 |
| B vs A | +2% [-14, +18], 8/7, p=1.0 | +18% [+2, +34], 13/4, p=0.049 | +4% [-4, +12], 3/1, p=0.63 |

**What changed in the picture.**

- *Same direction as run 1, stronger.* Arm A's E gain did not transfer: it lost 6 tasks on H.
  Arm B kept most of its gain (+3 on H, +2 on B). B vs A on H is the only comparison with
  p < 0.05 (0.049), one of nine uncorrected tests; with a Bonferroni correction it is not
  significant. Treat it as a lead to replicate, not a finding.
- *Empty-gold exclusion worked.* No pass came from an empty gold result, and test-suite false
  positives on E fell from about half of passes (run 1) to 2-4 of 20-25. Test-suite-corrected
  passes: E baseline 17, A 20, B 23; H baseline 21, A 18, B 24. The ordering B > baseline > A
  on H holds under the stricter check.
- *The student was fully deterministic* (five E runs all scored 20), so the keep threshold
  fell to 1 task. Arms kept edits worth +1 to +3 tasks on E; real (no sampling noise), but small enough to be
  overfitting to E.
- *Both arms converged on 3 sample rows plus 3 few-shot examples*, raising prompt cost about
  7x (361 to 2300-3000 tokens per H task). In run 1 few-shot never helped. The difference
  between the arms is in the rest: A uses fixed few-shot examples and an E-flavoured suffix
  ("handling multiple years or conditions"); B uses lexical (question-matched) examples, one
  retry and no suffix. That may explain the H gap, but this run does not test it.
- *The cost rule never fired.* With a threshold of 1, any 1-task drop counts as above
  noise, so Arm B kept all four of its changed fields, including a retry worth 1 task for
  about 40% more tokens.
- *The new critic approved every candidate* (0 of 15 rejected), the opposite failure from run
  1's critic, which rejected generic edits. The leak check flagged two Arm A candidates for
  the common word "addresses" (a table name in an E database).

## Run 3: three replicates of run 2

Three more runs with run 2's settings, changing only the top-level seed (new E/H/B splits)
and the proposer seed: `frozen_v3_s20261103.yaml`, `..._s20261104`, `..._s20261105`. One more
change: a minimum keep threshold of 2 tasks (`min_keep_delta_tasks: 2`), because the student
is deterministic and run 2's threshold had fallen to 1. Predictions were not registered.

| Run | Baseline E/H/B | Arm A E/H/B | Arm B E/H/B |
|---|---|---|---|
| run 2 | 40/58/6 | 48/46/6 | 50/64/10 |
| seed 20261103 | 40/56/16 | 56/60/22 | 58/54/16 |
| seed 20261104 | 38/50/6 | 54/40/2 | 48/42/4 |
| seed 20261105 | 46/54/8 | 46/54/8 | 46/54/8 |

(Accuracy in %, 50 tasks per set.) In seed 20261105 neither arm found any candidate that beat
the baseline by 2 tasks in 15 tries, so both final harnesses are the baseline.

Pooled over run 2 and the three replicates (`runs_pooled_v2v3.md`; exact sign test on summed
improved/regressed tasks; runs share models and task pools, so they are not fully independent):

| Comparison | E net tasks (p) | H net tasks (p) | B net tasks (p) |
|---|---|---|---|
| A vs baseline | +20 (0.007) | -9 (0.20) | +1 (1.0) |
| B vs baseline | +19 (0.014) | -2 (0.86) | +1 (1.0) |
| B vs A | -1 (1.0) | +7 (0.25) | +0 (1.0) |

**What the replicates show.**

- *Run 2's B-over-A result did not replicate.* B vs A on H was +18% in run 2, -6% in seed
  20261103 and +2% in 20261104. Pooled it is +7 tasks over 200, p = 0.25.
- *The robust finding is that E gains do not transfer.* Both arms reliably improve the set they
  are tuned on (+20 and +19 net tasks pooled), and neither improves held-out Spider or BIRD.
  Arm A is net negative on H (-9); Arm B is about flat (-2). That is consistent with RRSI's
  claim that regularization limits damage, but this pilot cannot distinguish it from noise.
- *Run 2's fixed-vs-lexical few-shot idea is not supported.* In the replicates every final
  harness that uses few-shot examples uses lexical selection, and transfer still varied in sign.
- *Evolution often does nothing useful.* One of three replicates found no edit worth keeping in
  either arm, and the critic rejected 0 candidates across all replicates.

## Run 4: pre-registered, six seeds, random-search control

Design, analysis plan and predictions are in `PREDICTION.md`, committed before any run-4
result existed. Three arms per seed: A (LLM proposer, greedy keep), B (RRSI-lite: edit
budget, placebo-calibrated keep threshold, critic, leak check, pruning) and C (random edits,
same keep rule as A). E (100 tasks) is the tuning set; E2 (100 fresh tasks from the same
pool) measures selection noise; H (322 Spider dev hard/extra) and B (398 BIRD Mini-Dev) are
held out. 10 generations x 3 candidates per arm. Unit of analysis is the seed; test is the
exact two-sided Wilcoxon signed-rank across seeds; secondaries Holm-corrected. Six seeds
(20261111 to 20261116) per amendment 1. Output: `runs_v4/pooled_seed_level.md` from
`python -m rsi.pool runs_v4/s* --seed-level`.

**Primary endpoint (B vs A on H): null.** Per-seed net tasks -25, -1, -7, +3, -3, +7; mean
-4.3 tasks of 322, 95% CI [-13.7, +2.7], p = 0.56. Arm B is not better than Arm A on held-out
Spider; if anything it is slightly behind.

| Endpoint | Set | Mean | 95% CI (seeds) | +/- seeds | p | p (Holm) |
|---|---|---|---|---|---|---|
| **B vs A (primary)** | H | -4.3 tasks | [-13.7, +2.7] | 2/4 | 0.562 | - |
| A vs baseline | H | +4.0 tasks | [-1.5, +8.8] | 4/1 | 0.188 | 1.000 |
| B vs baseline | H | -0.3 tasks | [-6.5, +4.3] | 3/1 | 0.875 | 1.000 |
| A vs C | E | +1.7 tasks | [-1.5, +4.7] | 4/2 | 0.438 | 1.000 |
| A vs C | H | -0.5 tasks | [-10.8, +9.5] | 4/2 | 1.000 | 1.000 |
| B vs A | B | +2.5 tasks | [-1.2, +6.5] | 3/3 | 0.438 | 1.000 |
| gap A (E gain - E2 gain) | E-E2 | +7.5 pp | [+1.7, +14.3] | 5/0 | 0.062 | 0.500 |
| gap B | E-E2 | +4.3 pp | [+0.8, +9.3] | 4/0 | 0.125 | 0.875 |
| gap C | E-E2 | +5.0 pp | [-1.2, +13.3] | 4/2 | 0.312 | 1.000 |

Mean gain over baseline in net tasks (passed by arm minus passed by baseline), predicted vs
observed:

| Arm | E (of 100) | E2 (of 100) | H (of 322) | B (of 398) |
|---|---|---|---|---|
| A, predicted / observed | +8 / +8.8 | +2 / +1.3 | -2 / +4.0 | 0 / -2.8 |
| B, predicted / observed | +4 / +4.2 | +2 / -0.2 | +1 / -0.3 | +1 / -0.3 |
| C, predicted / observed | +6 / +7.2 | +1 / +2.2 | -1 / +4.5 | 0 / -0.5 |

Per seed, tasks passed (baseline / A / B / C):

| Seed | E | E2 | H | B |
|---|---|---|---|---|
| 20261111 | 33/47/35/40 | 34/34/34/35 | 108/119/94/101 | 55/55/53/58 |
| 20261112 | 46/50/46/49 | 36/37/36/37 | 108/109/108/106 | 56/52/56/54 |
| 20261113 | 47/54/50/51 | 44/46/44/45 | 111/119/112/134 | 56/49/59/49 |
| 20261114 | 46/46/51/48 | 43/43/43/45 | 111/111/114/109 | 56/56/53/63 |
| 20261115 | 40/57/55/61 | 47/42/46/44 | 111/122/119/114 | 54/55/54/54 |
| 20261116 | 45/56/45/51 | 42/52/42/53 | 108/101/108/120 | 55/48/55/51 |

**Predictions.**

1. *Primary: B about 3 tasks ahead of A on H, not significant.* **Partly held.** Not
   significant, as predicted, but the sign was wrong: B is 4.3 tasks behind A on average.
2. *Selection gap significant for A (Holm p < 0.05), smaller for B.* **Did not hold.** A's gap
   is positive in 5 of 6 seeds (one seed is 0) and averages +7.5 pp, but p = 0.062 raw and 0.50
   after Holm. With one zero seed only five seeds enter the test, whose smallest possible p is
   0.0625, so this endpoint could not reach significance. B's gap is smaller (+4.3 pp), as
   predicted.
3. *A >= C on E by a couple of tasks, no different on H.* **Held.** A is +1.7 tasks over C on E
   and -0.5 on H, neither significant. The 32B LLM proposer adds nothing measurable over random
   edits plus best-of-3 selection in this 9-knob space.
4. *Neither arm's mean held-out gain exceeds 1% of the set (3.2 tasks on H, 4.0 on B).*
   **Did not hold for A**, whose mean H gain is +4.0 tasks (+1.2%), not significant (p = 0.19)
   and matched by random search (C: +4.5). Held for B on both sets and for A on BIRD.

**What run 4 shows.**

- *Tuning-set gains are mostly selection.* Every arm gains on E (+4 to +9 tasks) and keeps
  little of it on fresh E2 tasks from the same pool (-0.2 to +2.2). This is the run 2-3 finding,
  now with a direct measurement of the gap.
- *No held-out transfer, and no benefit from regularization.* Neither arm moves held-out Spider
  or BIRD beyond noise. RRSI-lite's checks make Arm B change less (two of six seeds keep the
  baseline harness unchanged) but do not make it transfer better.
- *The LLM proposer is no better than random search.* Arm C matches Arm A on every set.
- Run 2's B-over-A result (+18% on H) is now contradicted by a pre-registered six-seed test.

### Run 4 deviations

- **Six seeds instead of ten** (amendment 1, written before any seed finished).
- **Seed 20261111 restarted from scratch.** Its first attempt on the author's original
  instance stopped after 8 minutes, before any evolution result.
- **Seed 20261112, arm C rerun.** Arm C crashed in generation 8 when the local Ollama server
  returned one HTTP 500 to a student call (the only 500 in the run; Ollama logged no error). The
  pre-registered rule is to rerun a crashed seed from scratch; instead only arm C was rerun from
  scratch with the same seed and settings, and the finished A and B arms were kept, because arms
  are independent processes and A and B had completed normally. The crashed arm's files and the
  Ollama log excerpt are in `runs_v4/s20261112/logs/crash_C_1138/`. The rerun was decided before
  any seed-20261112 result was read.
- **Hardware.** Seeds ran two per instance on three Lambda 1x A10 instances in parallel, with
  the same Ollama version (0.40.13) and model digests as the original instance, from the working
  branch shipped as a git bundle. Instance spend: about $17.40 (ledger `cloud/ledger.jsonl`).
- **Student determinism.** Baseline repeats on E differed by 0 to 2 tasks (spread 2, 0, 0, 1,
  0, 1 by seed), and baseline H counts vary from 108 to 111 across seeds on the same 322 tasks.
  The placebo-calibrated threshold for Arm B absorbs this; Arm A's and C's keep threshold of 1
  task does not, which is part of why their E gains do not carry over to E2.

## Poisoning audit (implemented, not run)

`POISON_AUDIT.md` specifies a test of whether a triggered directive carried by a few E tasks is
written into the evolved harness, whether Arm B's checks stop it, whether it survives pruning and
clean evolution, and what it does to clean and triggered copies of H and B. `rsi/poison.py` builds
the poisoned tasks and the report; `scripts/run_poison.sh` runs one cell; `tests/test_poison.py`
covers the plumbing on synthetic data. Predictions are in the design file and precede any run.
Requires run 4 to have finished, since run 4's arms are the clean control.

## Limitations

One seed, n=50 per set, one student model, one proposer model. Spider and BIRD are likely
in the student's pretraining data; this affects all arms equally but limits absolute claims.
