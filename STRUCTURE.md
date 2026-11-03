# Repo structure & what's locked vs flexible

## Locked (shared contracts)
- `contracts/schemas.py` — frozen data contracts between stages.
- `contracts/eventlog.py` — the single events.jsonl read/write helper.
- `.claude/rules/*.md` — architecture, contracts, tech decisions, provenance, workflow.
- root `CLAUDE.md` — project context; auto-loaded in Claude Code sessions here.

## Flexible (build & extend)
- `harness/` — student loop, execution eval, telemetry
- `detector/` — windowed drift detection
- `correction/` — few-shot learning + knowledge-graph rules
- `viewer/` — FastAPI + Chart.js view over `events.jsonl`
- `adapters/` + `core/adapter.py` — domain plug-ins (coding, spider_sql, gsm8k_math, finance)
- `analysis/` — bootstrap CIs
- `rsi_pilot/` — standalone harness-evolution pilot with its own venv, README and run logs

Add implementation notes to each stage's `CLAUDE.md`. Personal notes go in `CLAUDE.local.md` (gitignored).

## Start here
1. `pip install -e .`  (or `pip install -r requirements.txt`)
2. `python fixtures/generate_mocks.py`  — creates mock data for offline development.
3. Open the relevant stage's `CLAUDE.md` and go. Each stage can be developed against mocks independently.
