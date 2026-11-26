# Chiron

**Agent evaluation and runtime repair with frozen model weights.**

Chiron has two experiments. The runtime loop detects accuracy drift and adds verified teacher repairs to an agent's context. The harness study asks whether changing what a SQL agent can see and do improves performance on held-out tasks.

[Results](#results) · [Architecture](docs/architecture.svg) · [Experiment design](rsi_pilot/README.md) · [Project notes](docs/PROJECT_NOTES.md)

## Results

### Run 5: harness performance and random-edit control

A 7B SQL agent uses a 32B proposer to revise its harness. The harnesses are frozen before scoring on held-out databases and a second benchmark. Each row below aggregates six seeds, with 200 tasks per benchmark in each seed.

| Harness | Held-out Spider | BIRD Mini-Dev |
| --- | ---: | ---: |
| Baseline | 46.4% | 20.1% |
| Plain LLM proposer | 58.2% | 36.7% |
| Regularized LLM proposer | 58.4% | 35.8% |
| Random-edit control | 58.8% | 36.6% |

The edits helped all three arms. The LLM proposer showed no measurable advantage over random edits on held-out Spider. The baseline exposed table names only, and all three arms often surfaced the full schema or added useful examples. Regularization did not produce a clear accuracy gain over the plain proposer. An exploratory comparison found fewer tokens per held-out task with regularization, 1,918 versus 4,969 for the plain proposer.

**Grader audit.** On an earlier run, about half of the tuning-set passes contained wrong queries that happened to produce the expected result on a single database. Rescoring against test-suite databases exposed the false positives. Later runs split by database and guarded access to the held-out sets. Spider 1.0 may already be in the student's training data.

[Run 5 design and limitations](rsi_pilot/README.md#run-5-multi-step-sql-agent-pre-registered) · [Per-seed results](rsi_pilot/runs_v5/seed_level.md) · [Committed measurements](rsi_pilot/runs_v5/summary.csv)

### Runtime teacher repair: coding

Student `meta-llama/Llama-3.2-3B-Instruct`, teacher `minimax/minimax-m2.5` on [Prime](https://docs.primeintellect.ai/inference/overview). Drift fired on the hard bucket, the teacher repaired the failures, verified repairs became few-shot memory, and the same student recovered on the evaluated hard bucket. This is a same-distribution demonstration.

| Hard coding problems | Accuracy |
|---|---:|
| Before correction | 0.273 |
| After correction | **0.455** |
| Gain | **+0.182** |

Reproduce with `bash scripts/use_prime_student.sh full`.

### Runtime teacher repair: text-to-SQL

This small runtime demonstration used no held-out split. Spider 1.0 may be in the students' training data.

| Setup | Before | After | Gain |
|---|---:|---:|---:|
| Local 1.5B student + MiniMax teacher | 0.100 | **0.333** | +0.233 (3.3x) |
| MiniMax student + teacher | 0.300 | **0.567** | +0.267 |

### Research infrastructure

- **Experiment design**: frozen splits, tuning / fresh / held-out / cross-benchmark sets, 6-seed paired statistics (exact Wilcoxon, Holm correction), leakage checks, test-suite re-scoring.
- **Cloud runs on Lambda A10 GPUs**: API client with budget ledger, auto-terminate watchdog, one-command bootstrap; runs 4 and 5 (36 arm-runs) cost about $49 in total. See [`rsi_pilot/CLOUD_RUN.md`](rsi_pilot/CLOUD_RUN.md).
- **Write-up and figures**: [`docs/writeup/post.md`](docs/writeup/post.md), [`docs/PROJECT_NOTES.md`](docs/PROJECT_NOTES.md) (architecture diagrams and the full project record).

---

## How the loop works

```
Harness ──telemetry──▶ Detector ──drift──▶ Correction (teacher)
   ▲                                              │
   └──────── few-shots (+ optional KG rules) ─────┘
                    events.jsonl ──▶ Viewer
```

| Piece | Job |
|-------|-----|
| [`harness/`](harness/) | Runs the student, scores outputs |
| [`detector/`](detector/) | Windowed accuracy; fires when it drops |
| [`correction/`](correction/) | Teacher repair → verified few-shots; optional KG |
| [`viewer/`](viewer/) | Plots the run from `events.jsonl` |

The student **weights never change**. Only its prompt memory changes.

**Memory lookup:** few-shots are filtered by domain (`db_id` / topic). KG rules match by **substring** (trigger phrase or table/column name in the question), not embeddings.

---

## Setup

Python ≥ 3.10.

```bash
git clone https://github.com/RohanChavan0701/Chiron.git
cd Chiron
pip install -e .
pip install -r requirements.txt   # if you want the viewer / extras
```

Hermetic tests (no API key):

```bash
python fixtures/generate_mocks.py
pytest -q
```

Put keys in `.env` (gitignored), e.g.:

```bash
PRIME_API_KEY=...          # coding on Prime
# or
OPENROUTER_API_KEY=...
```

---

## Run something real

### Coding on Prime (recommended entrypoint)

```bash
bash scripts/use_prime_student.sh list
bash scripts/use_prime_student.sh smoke    # student + teacher unit-test check
bash scripts/use_prime_student.sh probe    # cheap WITH/WITHOUT
bash scripts/use_prime_student.sh full     # full loop + recovery
```

Hard-curriculum style eval (learn on hard, score held-out hard):

```bash
bash scripts/use_prime_student.sh curriculum
```

Overrides: `PRIME_AGENT_MODEL=...`, `PRIME_TEACHER_MODEL=...`.

### Coding on OpenRouter

```bash
bash scripts/use_openrouter_student.sh smoke
bash scripts/use_openrouter_student.sh curriculum
```

### Orchestrator (any adapter)

```bash
python orchestrator.py --adapter coding --full --fresh
python orchestrator.py --adapter spider --probe
python orchestrator.py --adapter gsm8k --full --fresh
```

### Viewer (offline)

```bash
make demo
# or: VIEWER_LOG=events.jsonl uvicorn viewer.app:app --port 8011
```

---

## Layout

```
contracts/     Shared schemas + events.jsonl I/O
adapters/      coding, spider_sql, gsm8k_math, finance
harness/       Student client, feeds, eval / sandbox
detector/      Drift detection
correction/    Teacher, few-shots, KG (graph / inject)
viewer/        Live UI over the event log
analysis/      Paired bootstrap CIs
fixtures/      Problem subsets + mocks
scripts/       Prime / OpenRouter entrypoints, held-out freezing, multi-seed eval
rsi_pilot/     Self-improving harness experiments (own venv, README, run logs, cloud tooling)
orchestrator.py
```

---

## More domains

- **GSM8K**: uplift-gated memory that admits only examples shown to help ([`docs/FINDINGS_REASONING.md`](docs/FINDINGS_REASONING.md)).
- **Finance / PRBench**: rubric-graded reasoning with per-task teacher plans (feature branches `feat/finance-*`, `feat/q1-self-plan`).
- **Coding**: curriculum runs and multi-seed evaluation ([`docs/FINDINGS_CODING.md`](docs/FINDINGS_CODING.md)).

## Origin

The four-stage loop and orchestrator were built in a hackathon window starting 2026-07-01. The adapters, findings docs, and `rsi_pilot/` are follow-on work on the same codebase; the git log is the record of what landed when.

---

## Author

[Rohan Chavan](https://github.com/rohanpc0701)
