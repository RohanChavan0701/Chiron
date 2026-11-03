Seed-level analysis over 6 seeds (s20261111, s20261112, s20261113, s20261114, s20261115, s20261116).
Unit = seed. Per seed: net tasks (improved - regressed) for comparisons; for gap_X, the arm's
E gain minus its E2 gain in percentage points. Exact two-sided Wilcoxon signed-rank across seeds;
secondary p-values Holm-corrected.

| Endpoint | Set | Per-seed values | Mean | 95% CI (seeds) | Positive/negative seeds | p | p (Holm) |
|---|---|---|---|---|---|---|---|
| **primary** arm_B vs arm_A | H | -25, -1, -7, +3, -3, +7 | -4.3 tasks | [-13.7, +2.7] | 2/4 | 0.562 | - |
| arm_A vs baseline | H | +11, +1, +8, +0, +11, -7 | +4.0 tasks | [-1.5, +8.8] | 4/1 | 0.188 | 1.000 |
| arm_B vs baseline | H | -14, +0, +1, +3, +8, +0 | -0.3 tasks | [-6.5, +4.3] | 3/1 | 0.875 | 1.000 |
| arm_A vs arm_C | E | +7, +1, +3, -2, -4, +5 | +1.7 tasks | [-1.5, +4.7] | 4/2 | 0.438 | 1.000 |
| arm_A vs arm_C | H | +18, +3, -15, +2, +8, -19 | -0.5 tasks | [-10.8, +9.5] | 4/2 | 1.000 | 1.000 |
| arm_B vs arm_A | B | -2, +4, +10, -3, -1, +7 | +2.5 tasks | [-1.2, +6.5] | 3/3 | 0.438 | 1.000 |
| gap_A | E-E2 | +14, +3, +5, +0, +22, +1 | +7.5 pp | [+1.7, +14.3] | 5/0 | 0.062 | 0.500 |
| gap_B | E-E2 | +2, +0, +3, +5, +16, +0 | +4.3 pp | [+0.8, +9.3] | 4/0 | 0.125 | 0.875 |
| gap_C | E-E2 | +6, +2, +3, -0, +24, -5 | +5.0 pp | [-1.2, +13.3] | 4/2 | 0.312 | 1.000 |
