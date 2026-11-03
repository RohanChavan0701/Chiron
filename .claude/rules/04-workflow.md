# RULE: Workflow & git

## Stages are isolated by frozen seams
`contracts/schemas.py` is the only shared dependency. Each stage builds and tests against
its input-seam mock (`python fixtures/generate_mocks.py`), then integration is a matter of
swapping the mock for the real upstream output.

- Detector → `fixtures/mock_telemetry.jsonl`
- Correction → `fixtures/mock_drift_events.jsonl` (+ failing-case bundles)
- Viewer → `fixtures/mock_events.jsonl`
- Harness → real adapter data (it is the source; no input mock)

Hermetic tests (`pytest -q` from repo root) need no API key. CI runs them on 3.11 and 3.12.

## rsi_pilot has its own workflow
`rsi_pilot/` runs from its own directory with its own venv and `frozen*.yaml`. Follow its
README run order: splits → predictions committed → baseline → evolve → heldout → audit.
The runner refuses to score a non-baseline harness on held-out sets until both arms have
`final.yaml`; do not work around that.

## Git
- Branch per line of work (`feat/<stage>`, `feat/<experiment>`). Pull before push.
- `contracts/schemas.py` changes are versioned, announced, and made once.
- Run outputs (`runs*/`, `splits*.json`, `frozen*.yaml`) are committed with the code that
  produced them so results are reproducible from the log.
- Pre-register predictions (`rsi_pilot/PREDICTION.md`) in a commit that precedes the run.
