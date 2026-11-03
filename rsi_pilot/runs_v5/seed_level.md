Seed-level analysis over 6 seeds (s20261211, s20261212, s20261213, s20261214, s20261215, s20261216).
Unit = seed. Per seed: net tasks (improved - regressed) for comparisons; for gap_X, the arm's
E gain minus its E2 gain in percentage points. Exact two-sided Wilcoxon signed-rank across seeds;
secondary p-values Holm-corrected.

| Endpoint | Set | Per-seed values | Mean | 95% CI (seeds) | Positive/negative seeds | p | p (Holm) |
|---|---|---|---|---|---|---|---|
| **primary** arm_B vs arm_A | H | -4, +1, +4, +3, +2, -3 | +0.5 tasks | [-2.0, +2.8] | 4/2 | 0.844 | - |
| arm_A vs baseline | H | +23, +17, +26, +19, +23, +33 | +23.5 tasks | [+19.7, +27.8] | 6/0 | 0.031 | 0.250 |
| arm_B vs baseline | H | +19, +18, +30, +22, +25, +30 | +24.0 tasks | [+20.2, +27.8] | 6/0 | 0.031 | 0.250 |
| arm_A vs arm_C | E | +1, -3, +0, -2, +0, -1 | -0.8 tasks | [-2.0, +0.2] | 1/3 | 0.375 | 1.000 |
| arm_A vs arm_C | H | -7, -1, +3, -4, -1, +2 | -1.3 tasks | [-4.0, +1.3] | 2/4 | 0.531 | 1.000 |
| arm_B vs arm_A | B | +11, -16, -10, -15, +4, +15 | -1.8 tasks | [-11.3, +8.2] | 3/3 | 0.719 | 1.000 |
| gap_A | E-E2 | +12, +12, -18, -6, -8, +8 | +0.0 pp | [-9.3, +8.3] | 3/3 | 0.875 | 1.000 |
| gap_B | E-E2 | +4, +10, -16, -12, -12, +2 | -4.0 pp | [-11.3, +4.0] | 3/3 | 0.438 | 1.000 |
| gap_C | E-E2 | -2, +22, -8, +10, -8, +0 | +2.3 pp | [-5.7, +11.3] | 2/3 | 0.750 | 1.000 |
