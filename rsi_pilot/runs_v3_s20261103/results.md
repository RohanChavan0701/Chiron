| Harness | E | H | B | tokens/task (H) |
|---|---|---|---|---|
| baseline | 40% | 56% | 16% | 362 |
| arm_A | 56% | 60% | 22% | 2228 |
| arm_B | 58% | 54% | 16% | 2840 |

| Comparison | Set | Delta | 95% CI | Improved/Regressed | McNemar p |
|---|---|---|---|---|---|
| arm_A vs baseline | E | +16% | [+0%, +32%] | 14/6 | 0.115 |
| arm_A vs baseline | H | +4% | [-8%, +16%] | 5/3 | 0.727 |
| arm_A vs baseline | B | +6% | [-6%, +20%] | 7/4 | 0.549 |
| arm_B vs baseline | E | +18% | [+2%, +34%] | 13/4 | 0.049 |
| arm_B vs baseline | H | -2% | [-14%, +10%] | 4/5 | 1.000 |
| arm_B vs baseline | B | +0% | [-12%, +12%] | 5/5 | 1.000 |
| arm_B vs arm_A | E | +2% | [-12%, +16%] | 7/6 | 1.000 |
| arm_B vs arm_A | H | -6% | [-16%, +4%] | 2/5 | 0.453 |
| arm_B vs arm_A | B | -6% | [-14%, +2%] | 1/4 | 0.375 |

Transfer ratio (held-out gain / E gain; secondary, None when E gain < 2 tasks): arm_A: H=0.24999999999999947, B=0.3749999999999999; arm_B: H=-0.11111111111111124, B=0.0

Exact McNemar with n=50: 6/0 is the smallest all-one-way split with p < 0.05. Nine tests are reported without correction; read single p-values as weak evidence.
