# Fixed-harness ablation, seed level (6 replicate sessions)

Each session scores the run-5 baseline harness and each single-field variant fresh (no cache),
in the same session on the same server. H and B are the same tasks for every seed and the
student seed is fixed, so the seeds replicate the evaluation (server nondeterminism), not a search.

Variants: `schema_only` = baseline with `schema_upfront: "full"`; `sample_rows_only` = baseline with `describe_sample_rows: 3`; `steps_only` = baseline with `max_steps: 8`; `verify_only` = baseline with `verify_before_submit: true`

## Per seed

| Seed | Harness | Order | H passed | H tokens/task | B passed | B tokens/task |
|---|---|---|---|---|---|---|
| 20261211 | baseline | 9 | 96/200 | 2036 | 38/200 | 2291 |
| 20261211 | schema_only | 1 | 119/200 | 1784 | 83/200 | 3623 |
| 20261211 | sample_rows_only | 3 | 97/200 | 2693 | 36/200 | 2872 |
| 20261211 | steps_only | 7 | 102/200 | 2336 | 38/200 | 2898 |
| 20261211 | verify_only | 5 | 98/200 | 2404 | 41/200 | 2735 |
| 20261212 | baseline | 1 | 92/200 | 2040 | 41/200 | 2346 |
| 20261212 | schema_only | 3 | 117/200 | 1771 | 91/200 | 3398 |
| 20261212 | sample_rows_only | 5 | 100/200 | 2768 | 40/200 | 3290 |
| 20261212 | steps_only | 9 | 111/200 | 2390 | 41/200 | 2945 |
| 20261212 | verify_only | 7 | 99/200 | 2423 | 41/200 | 2890 |
| 20261213 | baseline | 9 | 93/200 | 1971 | 41/200 | 2201 |
| 20261213 | schema_only | 1 | 120/200 | 1775 | 83/200 | 3608 |
| 20261213 | sample_rows_only | 3 | 98/200 | 2659 | 38/200 | 2934 |
| 20261213 | steps_only | 7 | 101/200 | 2396 | 44/200 | 2841 |
| 20261213 | verify_only | 5 | 97/200 | 2405 | 41/200 | 2778 |
| 20261214 | baseline | 1 | 100/200 | 2007 | 42/200 | 2236 |
| 20261214 | schema_only | 3 | 118/200 | 1813 | 86/200 | 3607 |
| 20261214 | sample_rows_only | 5 | 90/200 | 2465 | 40/200 | 2794 |
| 20261214 | steps_only | 9 | 95/200 | 2289 | 39/200 | 2818 |
| 20261214 | verify_only | 7 | 88/200 | 2407 | 38/200 | 2755 |
| 20261215 | baseline | 9 | 98/200 | 2033 | 41/200 | 2233 |
| 20261215 | schema_only | 1 | 119/200 | 1764 | 86/200 | 3618 |
| 20261215 | sample_rows_only | 3 | 95/200 | 2542 | 43/200 | 3091 |
| 20261215 | steps_only | 7 | 106/200 | 2362 | 44/200 | 2826 |
| 20261215 | verify_only | 5 | 97/200 | 2401 | 37/200 | 2925 |
| 20261216 | baseline | 1 | 95/200 | 2041 | 35/200 | 2244 |
| 20261216 | schema_only | 3 | 120/200 | 1767 | 79/200 | 3686 |
| 20261216 | sample_rows_only | 5 | 98/200 | 2555 | 43/200 | 2987 |
| 20261216 | steps_only | 9 | 99/200 | 2384 | 40/200 | 2886 |
| 20261216 | verify_only | 7 | 96/200 | 2399 | 38/200 | 2836 |

## Per harness, across seeds (percent of the set; SD is the sample SD across seeds)

| Harness | Set | Seeds | Mean | SD | Tokens/task mean |
|---|---|---|---|---|---|
| baseline | H | 6 | 47.8% | 1.5 | 2022 |
| baseline | B | 6 | 19.8% | 1.3 | 2258 |
| schema_only | H | 6 | 59.4% | 0.6 | 1779 |
| schema_only | B | 6 | 42.3% | 2.0 | 3590 |
| sample_rows_only | H | 6 | 48.2% | 1.8 | 2614 |
| sample_rows_only | B | 6 | 20.0% | 1.4 | 2995 |
| steps_only | H | 6 | 51.2% | 2.8 | 2359 |
| steps_only | B | 6 | 20.5% | 1.3 | 2869 |
| verify_only | H | 6 | 47.9% | 2.0 | 2407 |
| verify_only | B | 6 | 19.7% | 0.9 | 2820 |

## Paired: variant minus same-session baseline

Net tasks = variant passed - baseline passed (= improved - regressed). Exact two-sided Wilcoxon
signed-rank across seeds (`rsi.pool.wilcoxon_exact`); with 6 seeds the smallest possible p is 0.031.
`schema_only` on H is the primary endpoint (uncorrected). Every other variant on H is one
Holm-corrected family (`rsi.pool.holm`); B rows are raw p only.

| Variant | Set | Per-seed net tasks | Per-seed pp | Mean pp | SD pp | Improved/regressed (summed) | Positive/negative seeds | Tokens/task ratio (mean) | Wilcoxon p | p (Holm) |
|---|---|---|---|---|---|---|---|---|---|---|
| schema_only | H | +23, +25, +27, +18, +21, +25 | +11.5, +12.5, +13.5, +9.0, +10.5, +12.5 | +11.6 | 1.6 | 218/79 | 6/0 | 0.88 | 0.031 | - |
| schema_only | B | +45, +50, +42, +44, +45, +44 | +22.5, +25.0, +21.0, +22.0, +22.5, +22.0 | +22.5 | 1.3 | 330/60 | 6/0 | 1.59 | 0.031 | - |
| sample_rows_only | H | +1, +8, +5, -10, -3, +3 | +0.5, +4.0, +2.5, -5.0, -1.5, +1.5 | +0.3 | 3.2 | 68/64 | 4/2 | 1.29 | 0.750 | 1.000 |
| sample_rows_only | B | -2, -1, -3, -2, +2, +8 | -1.0, -0.5, -1.5, -1.0, +1.0, +4.0 | +0.2 | 2.1 | 63/61 | 2/4 | 1.33 | 0.875 | - |
| steps_only | H | +6, +19, +8, -5, +8, +4 | +3.0, +9.5, +4.0, -2.5, +4.0, +2.0 | +3.3 | 3.9 | 76/36 | 5/1 | 1.17 | 0.094 | 0.281 |
| steps_only | B | +0, +0, +3, -3, +3, +5 | +0.0, +0.0, +1.5, -1.5, +1.5, +2.5 | +0.7 | 1.4 | 51/43 | 3/1 | 1.27 | 0.500 | - |
| verify_only | H | +2, +7, +4, -12, -1, +1 | +1.0, +3.5, +2.0, -6.0, -0.5, +0.5 | +0.1 | 3.3 | 45/44 | 4/2 | 1.19 | 0.594 | 1.000 |
| verify_only | B | +3, +0, +0, -4, -4, +3 | +1.5, +0.0, +0.0, -2.0, -2.0, +1.5 | -0.2 | 1.6 | 40/42 | 2/2 | 1.25 | 0.500 | - |

## Reference (unpaired)

**Reference from run 5, different session, not a paired comparison.** Run 5 final harnesses
and baseline, mean over its 6 seeds (`runs_v5/summary.csv`):

| Run 5 harness | H mean | H gain vs run-5 baseline | B mean | B gain vs run-5 baseline |
|---|---|---|---|---|
| baseline | 46.4% | +0.0 pp | 20.1% | +0.0 pp |
| arm_A | 58.2% | +11.8 pp | 36.7% | +16.6 pp |
| arm_B | 58.4% | +12.0 pp | 35.8% | +15.7 pp |
| arm_C | 58.8% | +12.4 pp | 36.6% | +16.5 pp |

Arms' mean H gain over the run-5 baseline: +12.1 pp.

Arms' mean B gain over the run-5 baseline: +16.3 pp.

Variant means above against these arm means compare different sessions; if the server, GPU
or Ollama version differs from run 5, only the paired table is a valid comparison.
