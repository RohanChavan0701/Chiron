# FinancePro-Bench findings (RSI-Mem v2)

Honest numbers only. Nulls and skips reported as such.

## A. Dataset + splits (G0.1)

- Source: `Sanscritic/finance-pro-bench` HF split `test` (400 rows), CC-BY-4.0.
- Cache: `fixtures/finance_pro_bench.json` + `fixtures/FINANCE_LICENSE`.
- Manifest: `fixtures/finance_manifest.json`, seed **42**.
  - train-stream **200** / validation **80** / held-out **120**
  - Disjoint; `--check` OK; no tiny categories (&lt;3).

## B. Judge reliability (G0.2) — EXIT GATE

**Protocol:** 40 stratified validation questions → one student answer each → judge twice in fresh contexts → Pearson *r* + MAD on normalized scores.

| Setting | Value |
|--------|--------|
| Student (answers) | `qwen/qwen3-8b` (Prime early; OpenRouter for remainder after Prime timeouts) |
| Judge | `openai/gpt-5.2` @ temp 0 on Prime |
| Teacher (assert ≠ judge) | `minimax/minimax-m3` |
| Sample | n=40 stratified from validation; **33** non-empty answers; **26** complete grade pairs |

### Answer generation yield

| Metric | Count |
|--------|------:|
| Planned | 40 |
| Usable answers | 33 |
| Failed / empty (timeouts, JSON errors) | 7 |

### Test–retest (verbatim from `runs/judge_reliability_summary.json`)

```json
{
  "n": 26,
  "pearson_r": 0.8289546719998755,
  "mad": 4.455873696256521,
  "gate": "PASS_SINGLE",
  "JUDGE_PASSES": 1,
  "mean_pass1": 7.763384690026545,
  "mean_pass2": 8.416652338484711
}
```

### Gate decision

| Criterion | Result |
|-----------|--------|
| MAD ≤ 5 | **Yes** (MAD ≈ **4.46**) → **single judge pass** (`JUDGE_PASSES=1`) |
| 5 &lt; MAD ≤ 8 | n/a |
| MAD &gt; 8 (K1) | **No** |

**Verdict: GATE PASSED — proceed to G0.3/G0.4 with `JUDGE_PASSES=1`.**

### Known judge / rubric issues (do not hide)

- Some rubrics fail `Item R*(max N)` extraction (`fpb-00262`, `fpb-00208`) — those items excluded from pairs.
- Occasional empty judge output / missing `TOTAL` after one repair-retry → pair incomplete, excluded from MAD *n*.
- Hand-audit sample (15 Qs): `runs/judge_audit_sample.md` — **flag for Rohan**.

### Student score context (not a baseline)

Mean normalized score on this validation reliability set is ~8 (pass1/pass2). That is **not** the Phase 0 held-out baseline; it only characterizes this probe sample under a weak 8B student.

## C. Headroom probe (G0.4)

*(LIVE numbers pending — harness ready in `scripts/finance_baselines.py`)*

| Model | n graded | Mean normalized | In band 15–40? |
|-------|---------:|----------------:|:---------------|
| `qwen/qwen3-8b` | — | — | — |
| `qwen/qwen3-30b-a3b-instruct-2507` | — | — | — |
| `qwen/qwen3.6-27b` | — | — | — |

**Chosen student:** *(pending LIVE)*

### Reliability (band-range) — after student pick

*(pending 3b)*

## D. Held-out baselines (G0.3)

*(pending 3c — only after band-range gate)*

---

*Updated 2026-07-20 — G0.2 done; Task-3 hermetic harness staged.*
