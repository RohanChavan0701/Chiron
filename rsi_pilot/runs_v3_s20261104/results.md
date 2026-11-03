| Harness | E | H | B | tokens/task (H) |
|---|---|---|---|---|
| baseline | 38% | 50% | 6% | 395 |
| arm_A | 54% | 40% | 2% | 1512 |
| arm_B | 48% | 42% | 4% | 1348 |

| Comparison | Set | Delta | 95% CI | Improved/Regressed | McNemar p |
|---|---|---|---|---|---|
| arm_A vs baseline | E | +16% | [+2%, +32%] | 12/4 | 0.077 |
| arm_A vs baseline | H | -10% | [-24%, +4%] | 4/9 | 0.267 |
| arm_A vs baseline | B | -4% | [-12%, +4%] | 1/3 | 0.625 |
| arm_B vs baseline | E | +10% | [-6%, +26%] | 11/6 | 0.332 |
| arm_B vs baseline | H | -8% | [-22%, +6%] | 4/8 | 0.388 |
| arm_B vs baseline | B | -2% | [-10%, +4%] | 1/2 | 1.000 |
| arm_B vs arm_A | E | -6% | [-20%, +8%] | 5/8 | 0.581 |
| arm_B vs arm_A | H | +2% | [-4%, +8%] | 2/1 | 1.000 |
| arm_B vs arm_A | B | +2% | [+0%, +6%] | 1/0 | 1.000 |

Transfer ratio (held-out gain / E gain; secondary, None when E gain < 2 tasks): arm_A: H=-0.6249999999999998, B=-0.24999999999999992; arm_B: H=-0.8000000000000004, B=-0.2

Exact McNemar with n=50: 6/0 is the smallest all-one-way split with p < 0.05. Nine tests are reported without correction; read single p-values as weak evidence.
