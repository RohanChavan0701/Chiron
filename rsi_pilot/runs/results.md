| Harness | E | H | B | tokens/task (H) |
|---|---|---|---|---|
| baseline | 48% | 20% | 10% | 321 |
| arm_A | 62% | 26% | 8% | 428 |
| arm_B | 58% | 28% | 12% | 606 |

| Comparison | Set | Delta | 95% CI | Improved/Regressed | McNemar p |
|---|---|---|---|---|---|
| arm_A vs baseline | E | +14% | [+0%, +28%] | 10/3 | 0.092 |
| arm_A vs baseline | H | +6% | [-6%, +18%] | 6/3 | 0.508 |
| arm_A vs baseline | B | -2% | [-12%, +6%] | 2/3 | 1.000 |
| arm_B vs baseline | E | +10% | [+0%, +20%] | 6/1 | 0.125 |
| arm_B vs baseline | H | +8% | [-2%, +18%] | 6/2 | 0.289 |
| arm_B vs baseline | B | +2% | [-4%, +8%] | 2/1 | 1.000 |
| arm_B vs arm_A | E | -4% | [-16%, +8%] | 4/6 | 0.754 |
| arm_B vs arm_A | H | +2% | [-4%, +10%] | 2/1 | 1.000 |
| arm_B vs arm_A | B | +4% | [-6%, +14%] | 4/2 | 0.688 |

Transfer ratio (held-out gain / E gain; secondary, None when E gain < 2 tasks): arm_A: H=0.4285714285714285, B=-0.14285714285714288; arm_B: H=0.8000000000000004, B=0.19999999999999996

Exact McNemar with n=50: 6/0 is the smallest all-one-way split with p < 0.05. Nine tests are reported without correction; read single p-values as weak evidence.
