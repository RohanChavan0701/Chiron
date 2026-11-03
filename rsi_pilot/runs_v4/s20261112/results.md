| Harness | E | E2 | H | B | tokens/task (H) |
|---|---|---|---|---|---|
| baseline | 46.0% | 36.0% | 33.5% | 14.1% | 482 |
| arm_A | 50.0% | 37.0% | 33.9% | 13.1% | 1060 |
| arm_B | 46.0% | 36.0% | 33.5% | 14.1% | 482 |
| arm_C | 49.0% | 37.0% | 32.9% | 13.6% | 1101 |

| Comparison | Set | Delta | 95% CI | Improved/Regressed | McNemar p |
|---|---|---|---|---|---|
| arm_A vs baseline | E | +4.0% | [+0.0%, +9.0%] | 5/1 | 0.219 |
| arm_A vs baseline | E2 | +1.0% | [-6.0%, +8.0%] | 7/6 | 1.000 |
| arm_A vs baseline | H | +0.3% | [-2.5%, +3.1%] | 11/10 | 1.000 |
| arm_A vs baseline | B | -1.0% | [-3.0%, +1.0%] | 6/10 | 0.454 |
| arm_B vs baseline | E | +0.0% | [+0.0%, +0.0%] | 0/0 | 1.000 |
| arm_B vs baseline | E2 | +0.0% | [+0.0%, +0.0%] | 0/0 | 1.000 |
| arm_B vs baseline | H | +0.0% | [+0.0%, +0.0%] | 0/0 | 1.000 |
| arm_B vs baseline | B | +0.0% | [+0.0%, +0.0%] | 0/0 | 1.000 |
| arm_C vs baseline | E | +3.0% | [-4.0%, +10.0%] | 8/5 | 0.581 |
| arm_C vs baseline | E2 | +1.0% | [-8.0%, +10.0%] | 10/9 | 1.000 |
| arm_C vs baseline | H | -0.6% | [-4.7%, +3.7%] | 23/25 | 0.885 |
| arm_C vs baseline | B | -0.5% | [-3.8%, +2.8%] | 21/23 | 0.880 |
| arm_B vs arm_A | E | -4.0% | [-9.0%, +0.0%] | 1/5 | 0.219 |
| arm_B vs arm_A | E2 | -1.0% | [-8.0%, +6.0%] | 6/7 | 1.000 |
| arm_B vs arm_A | H | -0.3% | [-3.1%, +2.5%] | 10/11 | 1.000 |
| arm_B vs arm_A | B | +1.0% | [-1.0%, +3.0%] | 10/6 | 0.454 |
| arm_A vs arm_C | E | +1.0% | [-7.0%, +9.0%] | 8/7 | 1.000 |
| arm_A vs arm_C | E2 | +0.0% | [-8.0%, +8.0%] | 8/8 | 1.000 |
| arm_A vs arm_C | H | +0.9% | [-3.4%, +5.3%] | 27/24 | 0.780 |
| arm_A vs arm_C | B | -0.5% | [-3.5%, +2.5%] | 19/21 | 0.875 |
| arm_B vs arm_C | E | -3.0% | [-10.0%, +4.0%] | 5/8 | 0.581 |
| arm_B vs arm_C | E2 | -1.0% | [-10.0%, +8.0%] | 9/10 | 1.000 |
| arm_B vs arm_C | H | +0.6% | [-3.7%, +4.7%] | 25/23 | 0.885 |
| arm_B vs arm_C | B | +0.5% | [-2.8%, +3.8%] | 23/21 | 0.880 |

Transfer ratio (gain on the set / E gain; secondary, None when E gain < 2 tasks): arm_A: E2=0.25000000000000033, H=0.07763975155279383, B=-0.251256281407035; arm_B: E2=None, H=None, B=None; arm_C: E2=0.3333333333333339, H=-0.20703933747412068, B=-0.16750418760469007

Set sizes: {'E': 100, 'E2': 100, 'H': 322, 'B': 398}. Per-run tests are uncorrected; the pre-registered analysis is across seeds (rsi.pool).
