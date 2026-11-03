| Harness | E | E2 | H | B | tokens/task (H) |
|---|---|---|---|---|---|
| baseline | 47.0% | 44.0% | 34.5% | 14.1% | 478 |
| arm_A | 54.0% | 46.0% | 37.0% | 12.3% | 8053 |
| arm_B | 50.0% | 44.0% | 34.8% | 14.8% | 914 |
| arm_C | 51.0% | 45.0% | 41.6% | 12.3% | 4395 |

| Comparison | Set | Delta | 95% CI | Improved/Regressed | McNemar p |
|---|---|---|---|---|---|
| arm_A vs baseline | E | +7.0% | [-4.0%, +18.0%] | 20/13 | 0.296 |
| arm_A vs baseline | E2 | +2.0% | [-9.0%, +12.0%] | 15/13 | 0.851 |
| arm_A vs baseline | H | +2.5% | [-3.1%, +8.1%] | 45/37 | 0.440 |
| arm_A vs baseline | B | -1.8% | [-5.3%, +1.8%] | 21/28 | 0.392 |
| arm_B vs baseline | E | +3.0% | [-3.0%, +9.0%] | 6/3 | 0.508 |
| arm_B vs baseline | E2 | +0.0% | [-5.0%, +5.0%] | 3/3 | 1.000 |
| arm_B vs baseline | H | +0.3% | [-2.2%, +2.8%] | 9/8 | 1.000 |
| arm_B vs baseline | B | +0.8% | [-1.3%, +2.8%] | 10/7 | 0.629 |
| arm_C vs baseline | E | +4.0% | [-7.0%, +14.0%] | 17/13 | 0.585 |
| arm_C vs baseline | E2 | +1.0% | [-9.0%, +11.0%] | 14/13 | 1.000 |
| arm_C vs baseline | H | +7.1% | [+1.9%, +12.7%] | 52/29 | 0.014 |
| arm_C vs baseline | B | -1.8% | [-5.1%, +1.8%] | 21/28 | 0.392 |
| arm_B vs arm_A | E | -4.0% | [-15.0%, +7.0%] | 13/17 | 0.585 |
| arm_B vs arm_A | E2 | -2.0% | [-12.0%, +8.0%] | 12/14 | 0.845 |
| arm_B vs arm_A | H | -2.2% | [-7.5%, +3.4%] | 38/45 | 0.510 |
| arm_B vs arm_A | B | +2.5% | [-1.3%, +6.3%] | 34/24 | 0.237 |
| arm_A vs arm_C | E | +3.0% | [-6.0%, +12.0%] | 11/8 | 0.648 |
| arm_A vs arm_C | E2 | +1.0% | [-9.0%, +11.0%] | 14/13 | 1.000 |
| arm_A vs arm_C | H | -4.7% | [-9.6%, +0.0%] | 24/39 | 0.077 |
| arm_A vs arm_C | B | +0.0% | [-3.0%, +3.0%] | 19/19 | 1.000 |
| arm_B vs arm_C | E | -1.0% | [-12.0%, +11.0%] | 17/18 | 1.000 |
| arm_B vs arm_C | E2 | -1.0% | [-11.0%, +9.0%] | 13/14 | 1.000 |
| arm_B vs arm_C | H | -6.8% | [-12.4%, -1.2%] | 31/53 | 0.021 |
| arm_B vs arm_C | B | +2.5% | [-1.0%, +6.1%] | 32/22 | 0.220 |

Transfer ratio (gain on the set / E gain; secondary, None when E gain < 2 tasks): arm_A: E2=0.2857142857142857, H=0.35492457852706255, B=-0.2512562814070349; arm_B: E2=0.0, H=0.10351966873706014, B=0.2512562814070351; arm_C: E2=0.25, H=1.7857142857142847, B=-0.43969849246231096

Set sizes: {'E': 100, 'E2': 100, 'H': 322, 'B': 398}. Per-run tests are uncorrected; the pre-registered analysis is across seeds (rsi.pool).
