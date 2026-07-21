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

**Protocol:** 20 category-stratified VALIDATION ids (seed 42), bare student prompt
(`AGENT_USE_EXAMPLES=0`), temp 0, `max_tokens=2048`, judge `openai/gpt-5.2` with
`JUDGE_PASSES=1`. Endpoint: Prime. Thinking disabled for student gen via
`chat_template_kwargs.enable_thinking=false` (required for `qwen/qwen3.6-27b`,
which otherwise returned empty `content`).

### Means (verbatim from `runs/finance_headroom_summary.json`)

```json
{
  "qwen/qwen3-8b": 9.262307868713286,
  "qwen/qwen3-30b-a3b-instruct-2507": 15.752503500053054,
  "qwen/qwen3.6-27b": 26.305344197683876
}
```

| Model | n graded / 20 | Mean normalized | In band 15–40? |
|-------|--------------:|----------------:|:---------------|
| `qwen/qwen3-8b` | 19 | **9.262** | No (&lt;15) |
| `qwen/qwen3-30b-a3b-instruct-2507` | 19 | **15.753** | Yes |
| `qwen/qwen3.6-27b` | 18 | **26.305** | Yes |

**Ungradable / excluded:** `fpb-00262` (rubric lacks `Item R*(max N)` — all models);
`fpb-00072` for 27b only (empty judge output after repair-retry). Answers generated
for all 20 ids × 3 models.

**Chosen student:** `qwen/qwen3.6-27b` — smallest model in band [15, 40]
(SIZE_ORDER: 8b out of band; 27b &lt; 30b MoE among in-band). Fallback
`qwen/qwen3.5-35b-a3b` not needed.

### Reliability (band-range) — after student pick

**Protocol:** same 20 headroom answers from `qwen/qwen3.6-27b` → grade a second
time in a fresh context (pass2) → Pearson *r* + MAD on normalized pairs.

#### Low-range (G0.2, for comparison)

| Metric | Value |
|--------|------:|
| n pairs | 26 |
| pearson_r | 0.829 |
| MAD | 4.456 |
| gate | PASS_SINGLE → `JUDGE_PASSES=1` |
| Student answers | `qwen/qwen3-8b` (~mean 8) |

#### Band-range (verbatim from `runs/finance_band_recheck_summary.json`)

```json
{
  "label": "reliability (band-range)",
  "student_model": "qwen/qwen3.6-27b",
  "n": 17,
  "pearson_r": 0.9617178576630094,
  "mad": 4.188280804907782,
  "gate": "PASS_SINGLE",
  "JUDGE_PASSES": 1,
  "mean_pass1": 25.685534723244224,
  "mean_pass2": 26.76587003266326
}
```

| Criterion | Result |
|-----------|--------|
| MAD ≤ 5 | **Yes** (MAD ≈ **4.19**) → **`JUDGE_PASSES=1` stands** |
| 5 &lt; MAD ≤ 8 | n/a |
| MAD &gt; 8 (STOP) | **No** |

**Verdict: BAND-RANGE GATE PASSED — proceed to held-out baselines with `JUDGE_PASSES=1`.**

Incomplete pairs (excluded from n=17): `fpb-00262` (bad rubric), `fpb-00072`
(empty judge both passes), `fpb-00025` (pass2 missing TOTAL after repair).

## D. Held-out baselines (G0.3)

**Protocol:** 120 held-out ids (seed 42), bare prompt, temp 0, single generation
each arm. Judge `openai/gpt-5.2`, `JUDGE_PASSES=1`. Gradable rubrics only:
**n=114** (6 held-out rubrics lack `Item R*(max N)` — excluded).
Student `qwen/qwen3.6-27b`; teacher `minimax/minimax-m3`.

### Overall (verbatim from `runs/finance_baselines_summary.json`)

```json
{
  "n_common": 114,
  "student_model": "qwen/qwen3.6-27b",
  "teacher_model": "minimax/minimax-m3",
  "JUDGE_PASSES": 1,
  "student": {
    "mean": 26.044389794853984,
    "ci_low": 22.331181470979256,
    "ci_high": 29.81132193409253,
    "n": 114.0
  },
  "teacher": {
    "mean": 35.79372726601678,
    "ci_low": 31.55940986829282,
    "ci_high": 40.27847491929874,
    "n": 114.0
  },
  "delta_teacher_minus_student": {
    "delta": 9.749337471162795,
    "ci_low": 5.390109038918876,
    "ci_high": 14.037220484460821,
    "p_value": 0.0
  }
}
```

| Arm | Mean | 95% bootstrap CI | n |
|-----|-----:|------------------:|--:|
| Student `qwen/qwen3.6-27b` | **26.044** | [22.331, 29.811] | 114 |
| Teacher `minimax/minimax-m3` | **35.794** | [31.559, 40.278] | 114 |
| Δ (teacher − student) | **9.749** | [5.390, 14.037] | paired; p=0.0 |

### Per-category means + student trap hits

| Category | n | Student mean | Teacher mean | Student traps_hit |
|----------|--:|-------------:|-------------:|-------------------|
| Accounting | 4 | 17.43 | 27.28 | T1×2, T3×2, T4×1, T8×1 |
| Banking | 4 | 9.46 | 17.48 | T2×1, T4×1, T9×1 |
| Commodities | 3 | 27.62 | 39.14 | T1×1, T2×1, T3×4, T8×1 |
| Compliance | 2 | 14.00 | 81.76 | T1×1, T2×1, T3×2, T6×1, T8×1 |
| Corporate Development | 3 | 11.25 | 24.86 | T10×1, T2×4, T3×2, T6×3, T9×1 |
| Corporate Finance | 4 | 33.70 | 41.85 | — |
| Credit | 3 | 13.91 | 15.80 | T4×1, T6×1 |
| Crypto & Digital Assets | 4 | 29.55 | 48.98 | T1×3, T10×1, T2×3, T3×4, T5×1, T8×3, T9×2 |
| Derivatives | 4 | 18.32 | 41.67 | T1×1, T4×2, T6×2, T9×1 |
| ESG | 4 | 43.77 | 50.62 | T1×3, T3×1, T4×3, T5×2, T7×2 |
| FinTech | 2 | 54.38 | 32.81 | T8×3 |
| Hedge Funds | 2 | 29.89 | 36.47 | T5×1, T6×1 |
| Infrastructure | 4 | 15.57 | 50.75 | T1×2, T4×1 |
| Insurance | 4 | 14.19 | 9.76 | T10×2, T2×1, T4×2, T6×1, T7×3, T8×2, T9×1 |
| Investment Banking | 4 | 21.45 | 33.93 | T3×1, T4×2, T7×1 |
| Investor Relations | 4 | 39.23 | 54.11 | T4×1, T5×2, T7×2 |
| Legal | 4 | 42.59 | 35.85 | T6×1 |
| Macro | 4 | 29.23 | 40.01 | T3×1, T5×1 |
| Operations | 3 | 35.89 | 75.69 | T3×2, T4×1, T5×1 |
| Portfolio Management | 4 | 35.08 | 40.30 | T1×1, T3×1, T5×1, T8×1 |
| Private Credit | 3 | 18.81 | 51.83 | T3×1, T8×1 |
| Private Equity | 4 | 36.71 | 24.27 | T3×2, T6×2, T9×1 |
| Rates | 4 | 20.29 | 24.60 | T1×2, T2×1, T3×1, T6×1, T7×1, T9×1 |
| Real Estate | 4 | 19.08 | 21.80 | T1×1, T10×1, T3×3, T4×2, T7×2, T9×2 |
| Research | 4 | 27.43 | 24.89 | T3×1, T4×2 |
| Retail Banking | 3 | 39.25 | 35.28 | T3×1, T4×2 |
| Risk Management | 4 | 33.14 | 39.81 | T1×1, T10×1, T3×1, T4×1, T8×1, T9×1 |
| Structured Products | 3 | 28.13 | 39.31 | T5×1, T6×1, T8×2, T9×1 |
| Tax | 4 | 2.34 | 22.46 | T1×1, T3×1, T7×1, T8×1 |
| Trading | 3 | 22.96 | 51.53 | T1×1, T10×1, T3×1 |
| Treasury | 2 | 75.50 | 47.25 | T2×1, T8×1 |
| Venture Capital | 3 | 7.01 | 15.57 | T3×1, T4×1, T6×1, T8×1 |
| Wealth Management | 3 | 17.60 | 11.72 | T1×2, T2×3 |

### Trap-hit census (aggregate — Phase-1 preview)

**Student totals:**

```json
{
  "T1": 19,
  "T2": 11,
  "T3": 23,
  "T9": 8,
  "T5": 8,
  "T8": 13,
  "T6": 12,
  "T4": 16,
  "T7": 8,
  "T10": 5
}
```

**Teacher totals:**

```json
{
  "T7": 11,
  "T8": 10,
  "T4": 11,
  "T2": 11,
  "T5": 10,
  "T6": 9,
  "T9": 9,
  "T3": 13,
  "T1": 16,
  "T10": 5,
  "T11": 1
}
```

**Highlight:** student trap mass concentrates on **T3** (23), **T1** (19), **T4** (16),
**T8** (13), **T6** (12). Teacher also hits **T1** (16) / **T3** (13) but at lower
counts overall — trap-registry memory is a plausible Phase-1 lever.


---

*Updated 2026-07-21 after G0.3 held-out baselines (3c).*
