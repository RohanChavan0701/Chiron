| Harness | E | E2 | H | B | tokens/task (H) |
|---|---|---|---|---|---|
| baseline | 46.0% | 43.0% | 34.5% | 14.1% | 478 |
| arm_A | 46.0% | 43.0% | 34.5% | 14.1% | 478 |
| arm_B | 51.0% | 43.0% | 35.4% | 13.3% | 856 |
| arm_C | 48.0% | 45.0% | 33.9% | 15.8% | 883 |

| Comparison | Set | Delta | 95% CI | Improved/Regressed | McNemar p |
|---|---|---|---|---|---|
| arm_A vs baseline | E | +0.0% | [+0.0%, +0.0%] | 0/0 | 1.000 |
| arm_A vs baseline | E2 | +0.0% | [+0.0%, +0.0%] | 0/0 | 1.000 |
| arm_A vs baseline | H | +0.0% | [+0.0%, +0.0%] | 0/0 | 1.000 |
| arm_A vs baseline | B | +0.0% | [+0.0%, +0.0%] | 0/0 | 1.000 |
| arm_B vs baseline | E | +5.0% | [-4.0%, +14.0%] | 13/8 | 0.383 |
| arm_B vs baseline | E2 | +0.0% | [-7.0%, +7.0%] | 6/6 | 1.000 |
| arm_B vs baseline | H | +0.9% | [-3.4%, +5.3%] | 26/23 | 0.775 |
| arm_B vs baseline | B | -0.8% | [-3.5%, +2.0%] | 14/17 | 0.720 |
| arm_C vs baseline | E | +2.0% | [-3.0%, +7.0%] | 4/2 | 0.688 |
| arm_C vs baseline | E2 | +2.0% | [-3.0%, +7.0%] | 4/2 | 0.688 |
| arm_C vs baseline | H | -0.6% | [-3.1%, +1.9%] | 7/9 | 0.804 |
| arm_C vs baseline | B | +1.8% | [-0.5%, +4.0%] | 15/8 | 0.210 |
| arm_B vs arm_A | E | +5.0% | [-4.0%, +14.0%] | 13/8 | 0.383 |
| arm_B vs arm_A | E2 | +0.0% | [-7.0%, +7.0%] | 6/6 | 1.000 |
| arm_B vs arm_A | H | +0.9% | [-3.4%, +5.3%] | 26/23 | 0.775 |
| arm_B vs arm_A | B | -0.8% | [-3.5%, +2.0%] | 14/17 | 0.720 |
| arm_A vs arm_C | E | -2.0% | [-7.0%, +3.0%] | 2/4 | 0.688 |
| arm_A vs arm_C | E2 | -2.0% | [-7.0%, +3.0%] | 2/4 | 0.688 |
| arm_A vs arm_C | H | +0.6% | [-1.9%, +3.1%] | 9/7 | 0.804 |
| arm_A vs arm_C | B | -1.8% | [-4.0%, +0.5%] | 8/15 | 0.210 |
| arm_B vs arm_C | E | +3.0% | [-6.0%, +13.0%] | 13/10 | 0.678 |
| arm_B vs arm_C | E2 | -2.0% | [-9.0%, +5.0%] | 6/8 | 0.791 |
| arm_B vs arm_C | H | +1.6% | [-2.8%, +5.9%] | 28/23 | 0.576 |
| arm_B vs arm_C | B | -2.5% | [-5.6%, +0.5%] | 15/25 | 0.154 |

Transfer ratio (gain on the set / E gain; secondary, None when E gain < 2 tasks): arm_A: E2=None, H=None, B=None; arm_B: E2=0.0, H=0.18633540372670845, B=-0.15075376884422123; arm_C: E2=1.0000000000000029, H=-0.3105590062111813, B=0.8793969849246244

Set sizes: {'E': 100, 'E2': 100, 'H': 322, 'B': 398}. Per-run tests are uncorrected; the pre-registered analysis is across seeds (rsi.pool).
