# CLAUDE.md — Chiron

> Project context for AI coding assistants working in this repo.

## What this is (one sentence)
Runtime self-correction for a small language model: a harness watches a student on a stream of problems (text-to-SQL on Spider by default; coding, GSM8K and finance via adapters), a detector fires when windowed accuracy **drifts**, and a correction stage turns verified teacher repairs into few-shot memory so the same student recovers. Weights never change. A second line of work, `rsi_pilot/`, tests whether an LLM-driven harness-evolution loop transfers to held-out data (so far: tuning-set gains do not transfer).

## The loop (4 stages)
```
 HARNESS --TelemetryRecord--> DETECTOR --DriftEvent--> CORRECTION
     ^                                                      |
     |  AgentConfig.few_shot_examples (starts empty; correction appends) |
     +----------------------------------------------------------------------+
              all stages append typed events -> events.jsonl --> VIEWER
```
The growing `few_shot_examples` list **is** the agent learning. That feedback path is the spine of the project.

## Architecture
| Stage | Dir | Consumes | Emits |
|-------|-----|----------|-------|
| Harness / telemetry | `harness/` | Spider data | `TelemetryRecord` |
| Detector | `detector/` | `TelemetryRecord` | `DriftEvent` |
| Correction / learning | `correction/` | `DriftEvent` + failing cases | `CorrectionAction` |
| Viewer | `viewer/` | `events.jsonl` | (UI) |
| Adapters | `adapters/` + `core/adapter.py` | domain data | `TaskAdapter` for harness |
| RSI pilot | `rsi_pilot/` (standalone) | Spider dev + BIRD Mini-Dev | `runs*/results.md`, `audit.json` |

Each stage directory has its own `CLAUDE.md` with the contract + implementation notes. `rsi_pilot/README.md` documents the pilot's design, leakage controls and all run results.

Current plan and GPU work: `docs/DEV_PLAN.md`. Before launching or terminating any cloud instance, read `rsi_pilot/CLOUD_RUN.md`; its spending limits and termination rules are the author's and are not to be changed by an agent.

## Shared rules
@.claude/rules/00-architecture.md
@.claude/rules/01-contracts.md
@.claude/rules/02-tech-decisions.md
@.claude/rules/03-provenance.md
@.claude/rules/04-workflow.md

## First thing, every session
1. Read the relevant stage's `CLAUDE.md`.
2. Build against **mock fixtures** (`python fixtures/generate_mocks.py`) — no live API required for tests.
3. Treat `contracts/schemas.py` as frozen unless you intentionally version the contract.

## Run from repo root
All imports assume repo root on path: `from contracts.schemas import TelemetryRecord`. Run commands from the repo root (or `pip install -e .`).
