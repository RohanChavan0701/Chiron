| Harness | E | H | B | tokens/task (H) |
|---|---|---|---|---|
| baseline | 40% | 58% | 6% | 361 |
| arm_A | 48% | 46% | 6% | 2995 |
| arm_B | 50% | 64% | 10% | 2330 |

| Comparison | Set | Delta | 95% CI | Improved/Regressed | McNemar p |
|---|---|---|---|---|---|
| arm_A vs baseline | E | +8% | [-6%, +24%] | 9/5 | 0.424 |
| arm_A vs baseline | H | -12% | [-28%, +4%] | 6/12 | 0.238 |
| arm_A vs baseline | B | +0% | [-8%, +8%] | 2/2 | 1.000 |
| arm_B vs baseline | E | +10% | [-8%, +28%] | 13/8 | 0.383 |
| arm_B vs baseline | H | +6% | [-6%, +18%] | 7/4 | 0.549 |
| arm_B vs baseline | B | +4% | [-4%, +12%] | 3/1 | 0.625 |
| arm_B vs arm_A | E | +2% | [-14%, +18%] | 8/7 | 1.000 |
| arm_B vs arm_A | H | +18% | [+2%, +34%] | 13/4 | 0.049 |
| arm_B vs arm_A | B | +4% | [-4%, +12%] | 3/1 | 0.625 |

Transfer ratio (held-out gain / E gain; secondary, None when E gain < 2 tasks): arm_A: H=-1.5, B=0.0; arm_B: H=0.6000000000000006, B=0.4000000000000002

Exact McNemar with n=50: 6/0 is the smallest all-one-way split with p < 0.05. Nine tests are reported without correction; read single p-values as weak evidence.
