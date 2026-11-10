# Run 6 design: Goodhart versus the winner's curse in self-improvement loops

Status: design, 2026-11-09. Supersedes `HACK_AUDIT.md` (kept as the record of how the design got
here). Nothing is implemented, nothing has run, no predictions are registered.

## Claim to test (revised after the second critique, see "Second critique" below)

A self-improvement loop that selects on a label-free proxy turns into a reward hacker when it runs
out of real improvements, and it does so whoever proposes the edits.

Stated as a model. Across candidate edits, write the proxy gain as

    proxy gain = true gain + bias + noise

with spreads `s_true` (how much edits really differ), `s_bias` (how much the proxy's error differs
across edits) and noise variance `v/m` for `m` selection tasks. Selecting the best of k on the proxy
returns a winner whose reported gain splits, in expectation, in proportion to the three variances.
Call the middle share the **Goodhart share**:

    G = s_bias^2 / (s_true^2 + s_bias^2 + v/m)

That form assumes true gain and bias are uncorrelated across edits. They are not: an edit that
raises accuracy leaves fewer wrong answers for a judge to wrongly approve, so the two move in
opposite directions. `rsi/goodhart.py` therefore estimates the cross term and uses
`G = (s_bias^2 + s_tb) / (s_true^2 + s_bias^2 + 2 s_tb + v/m)`. In synthetic data with no bias
spread at all this G sits slightly below zero (about -0.04), which is the null to compare against,
not zero.

Three predictions follow, and none is guaranteed by the algebra:

1. **Depletion.** `s_true` is large at a weak baseline and collapses at a strong harness, while
   `s_bias` does not. So G is small early and large late. Run 5's baseline lacked the schema; that
   is the weak state. The same loop started from run 5's best harness is the strong state.
2. **No intent needed.** G at the strong state is as large for random edits as for LLM edits.
3. **More data does not help.** G rises with m, because m only removes noise.

If prediction 1 fails (`s_bias` collapses along with `s_true`), cheap label-free proxies are safe
selection signals for harness edits even near the ceiling. That would be worth knowing.

The first version of this section claimed only that noise shrinks with data and bias does not. That
is true by definition of bias and was not a research claim.

## Why the earlier designs were dropped

| Earlier design | Fatal problem |
|---|---|
| Planted exploits, arms A/B/C | Claimed things about selection without ever removing selection. Exploit rate near 0.04 per candidate, about one event per seed. |
| Multi-domain transfer matrix | Predicted null; labs already run it with stronger models (RRSI, AIDE^2). |
| Grader-type contrast across domains | Grader confounded with task. No ground truth in the judged domain. |
| Proposer-by-selector factorial of live loops | Right question, wrong instrument: every cell is a full multi-seed run, and the key rates still have no power. |

The common flaw is architectural. A live loop entangles three things (what gets proposed, what gets
kept, how proposals react to scores) and pays full GPU price for each seed of each cell. The fix is
to measure the three separately with the cheapest instrument for each, then check the pieces against
a small number of live loops.

## Related work and what is left open

Read on 2026-11-09. "Full" means the HTML body was read; "abstract" means only that.

| Paper | Read | What it establishes | What it leaves open |
|---|---|---|---|
| Winner's Curse in LLM Self-Improvement Loops (2610.09239) | full, first 100k chars | Pre-registered, 8 seeds: greedy loops overstate gains by 13.6 points at 16 selection items, 1.7 at 256. Already splits candidate spread into true effect and sampling noise with a reliability term. From a competent start only 5% of rewrites improve. | Its own limitations: instructions only, deterministic scoring only, no agentic tasks, no lock-in model. Selection is always on the true metric, so there is no bias term. Every proposer is an LLM. |
| Reward Hacking in Self-Improving Code Agents (ICLR 2026 RSI workshop; Zhao, Srikanth, Wu, Jiang) | abstract (ICLR page, truncated) | The agent sees only public proxy evaluations; real tasks are held out. Hacking rises from 26.4% at 10 steps to 57.8% at 100. Self-critique helps on one benchmark and not the other. | No explanation of the rise. No random baseline. |
| When Do Agent Loops Mistake Stagnation for Progress? (2607.25152) | abstract | Preregistered pilot, 54 cycles, world-state oracle as truth. In-band judge accepts cycles of which 44% are real regressions. A stronger judge does not close the gap; the gap vanishes when success is verifiable from the artifact. | One frontier agent, no proposer comparison, no decomposition of the reported gain mentioned. Full PDF not read. |
| Reward Hacking Across Weights, Selection, and Prompts (2609.25848) | full | Framework: names sample efficiency, feedback quality and reachable behavior as distinct explanations "to be tested" | No LLM experiments at all. |
| Feedback Loops Drive In-Context Reward Hacking (2402.06627); Honesty to Subterfuge (2410.06491) | abstract | Feedback alone, without training, moves a model toward gaming | Single model refining its own output. No selection step, no harness lineage. |
| Simple Baselines are Competitive with Code Evolution (2602.16805) | abstract | Random search matches LLM-guided evolution on capability | Says nothing about hacking. |
| HackProbe (2609.04665) | full | Detector for a qwen2.5-7B prompt-evolution host with four injected channels | Detection, not attribution. No random proposer. Channels are injected, not natural. |
| Auditing Harness Tampering (2609.00069); HASE (2607.03935) | full | Tampering is common in DGM, ADAS, HyperAgents; an editable evaluator gets weakened | No random arm, intent deliberately out of scope. |
| AIDE^2 (2609.26457) | full, first 100k chars | Hack rate changes along a lineage | Authors: cause not identified. |

Run 4 and run 5 in this repo already measured the noise component with a random arm (E minus E2
gap, A vs C). 2610.09239 now covers the noise story with more data, so repeating it is not a
contribution. This design is a direct extension of that paper: add a bias term to its two-term
model, move to an agentic harness and judged proxies (both listed in its limitations), and add the
random proposer it lacks.

The two lineage results point in opposite directions, and they come from the same group: hacking
rises with steps in the workshop paper, where the agent optimizes a public proxy, and falls in
AIDE^2, where rewrites are accepted on a private held-out grade. The model above predicts that
split. Neither paper offers it as an explanation. The workshop page does not spell out the exact
selection rule, so this reading is an inference.

The stagnation paper supports the proxy ladder: its gap depends on where the success signal lives,
not on judge strength. That is P1 versus P2 here.

Checked on 2026-11-09 after a full read of 2610.09239 including appendices: it has no random or
non-LLM proposer, no judged or label-free proxy, and no stopping rule beyond fixed budgets. Its
"bias" is bias of the gain estimate from set reuse, not systematic proxy error.

Still not verified: the workshop paper's full text (OpenReview ikrQWGgxYg); the full PDF of
2607.25152; Khalaf et al. 2025 and Liu et al. 2026 as cited by the framework paper. Novelty of the
depletion claim holds against everything read so far and is not established beyond that.

## Setting

A runtime self-improvement loop has no gold labels. That was Chiron's original premise. It must
select harness edits on something label-free. The experiment asks what that costs.

**Domains.** Chosen for programmatic ground truth, so "true" is never another judge.

- D-fin (primary): multi-step numeric reasoning over financial tables and text (FinQA or TAT-QA;
  license and 7B headroom to confirm in stage 0). Truth: numeric match with tolerance.
- D-sql (replication): the run-5 SQL agent. Truth: Spider's official comparison. Code exists.

**Proxy ladder.** Every transcript is graded by all of these at once. Truth is graded too. Because
all graders read the same transcript, the difference between a proxy and truth on an edit is free of
student nondeterminism (run 5 saw 5 to 7 flips per 50 tasks from that source).

| Proxy | What it sees | Expected fidelity | Real-world analogue |
|---|---|---|---|
| P0 labels-small | Gold on a small sample | Unbiased, noisy | A few hand-labeled items |
| P1 judge-ref | Answer plus gold reference | High | Offline eval with references |
| P2 judge-free | Question and answer only | Medium | Online quality scoring |
| P3 validity | Did the agent submit a well-formed answer (a number; a query that runs and returns rows) | Low | Chiron's `query_valid` channel; any "did it finish" metric |

P0 has noise and no bias. P2 and P3 have bias. That contrast is the experiment. Judges are local
models from a family other than the student and proposer. Self-consistency was dropped as a proxy:
it multiplies student cost by the number of samples. P3 costs nothing.

**Two anchor states.** Every bank is built twice per domain: from the weak baseline harness, and
from a strong harness (the best true-score harness from a short truth-selected search, the analogue
of run 5's evolved harness). The depletion claim is the comparison between the two.

## Three instruments

### 1. Edit bank (what gets proposed)

Sample single edits to the baseline harness from several sources. Evaluate each once on the tuning
tasks. Record per-task verdicts from truth and every proxy.

| Source | What it is | Why |
|---|---|---|
| S0 placebo | Meaning-preserving rewordings (`rsi/edits.py`) | Noise floor |
| S1 random | Arm C's generic menus | Blind prior |
| S2 LLM, traces only | Arm A's proposer, no scores shown | Proposer prior |
| S3 LLM, proxy described | S2 plus a description of the grader | Visibility |
| S4 LLM, told to maximize the proxy | Red-team prompt | Ceiling on reachable gaming |

Each edit becomes one point in the plane (proxy gain, true gain). Per source, proxy and anchor
state, estimate `s_true`, `s_bias` and `v` with a measurement-error model (the observed spread of
edits includes evaluation noise, which must be subtracted, as 2610.09239 does for its two terms),
and from them G. Counting points in a "hack quadrant" was dropped: when most edits do nothing, a
quarter of a pure-noise cloud lands there by chance.

S4 answers "is gaming reachable in this edit space at all". If S4 cannot open a gap, nothing else
will, and the study stops there with that result.

### 2. Selection simulator (what gets kept)

No new GPU. Resample tasks and edits from the bank and replay any keep rule: best of k on proxy,
with selection set size m. For each (source, proxy, k, m) compute the winner's

- reported gain: proxy gain on the selection tasks;
- noise component: true gain on selection tasks minus true gain on fresh tasks;
- bias component: proxy gain minus true gain on the selection tasks.

The simulator's job is to check the variance model: does the winner's reported gain split in the
proportions the three estimated variances predict, at each k and m and at each anchor state? The
model assumes roughly normal, independent components; real clouds may have one huge real edit
(`schema_upfront`) and a blob. Where the model and the replay disagree, the replay is the result.

Because replay is free, every acceptance rule can be tested the same way: greedy, Arm B's placebo
threshold, require agreement of two proxies, spend a few P0 labels on the finalists.

**A stopping rule (the method this study produces).** A loop cannot see truth, but it can buy a few
labels. Estimate G online from a small labeled audit of recent candidates and stop when G passes
one half: past that point most of what the loop reports is the proxy's error. Evaluate in replay
and in the live loops: true score at stop, labels spent, against greedy and against a fixed
generation budget.

Selection is ablated here directly: random keep is k = 1.

### 3. History injection (how proposals react to scores; secondary, run only if stages 1 and 2 hold)

Give the proposer a fabricated edit history and nothing else different. Three conditions: history in
which style-type edits scored well, history in which substance-type edits scored well, no history.
Sample proposals, evaluate them into the bank, and compare clouds. A shift toward the hack quadrant
under the first condition is the feedback road, measured as a causal dose-response without running a
loop. `show_edit_history` already exists in `frozen_v5.yaml`; the fabricated histories are new.

### Validation: a few live loops

The bank holds single edits from the baseline. Real loops compose edits. So run a small number of
live loops (proposer with history, proposer without, random; proxy P2; 3 seeds) and compare their
final reported, noise and bias components with what the simulator predicts for the same k and m.
Agreement licenses the simulator. Disagreement is a finding about composition and gets reported.

## Endpoints (to be fixed in a prediction file before stage 2)

Primary: in D-fin, proxy P2, sources S1 and S2 pooled: G at the strong anchor minus G at the weak
anchor, at m = 50. Claim: positive.

Secondary: the same for S1 alone (no intent needed); G for S2 vs S1 at each anchor; `s_bias` at
strong vs weak (does bias spread survive when real spread collapses); G across the proxy ladder;
S3 vs S2 (visibility); variance model vs replay; replay vs live loops; the stopping rule against
greedy; history injection shift; all of it repeated on D-sql.

Statistics: two-level bootstrap over tasks and edits for bank and simulator quantities; seed-level
Wilcoxon only for the live loops. The repo's pre-registration rules apply unchanged.

## Stages and stop rules

| Stage | Work | GPU | Stop if |
|---|---|---|---|
| 0 | Headroom: baseline on D-fin candidates, keep one with 15% to 80% accuracy. Judge check: 20 hand-written style-only edits; does P2 move while truth does not? Power: measure the per-task proxy-truth disagreement rate and the placebo spread, then compute how many edits and tasks are needed to estimate `s_bias` to within a third of its value. | Small | No domain has headroom; no proxy can be moved without moving truth even by hand; or the power calculation needs more than the budget. Report and stop. |
| 1 | Find the strong anchor. Bank for S0, S1, S4 on D-fin at both anchors. | About 200 harness evaluations | S4 opens no gap at either anchor: gaming unreachable here. Report and stop. |
| 2 | Register predictions. Bank for S2, S3 at both anchors. Simulator. Stopping rule in replay. | About 250 harness evaluations | n/a |
| 3 | History injection. Live validation loops. | About half a run-5 cell | n/a |
| 4 | D-sql replication. Defense comparison write-up. | About one run-5 cell | n/a |

One harness evaluation is one harness on the full tuning set. A run-5 cell was roughly 500 of them
across 6 seeds. Stages 0 to 2 together are about one run-5 cell; the power calculation in stage 0
may raise that. Budget from `cloud/ledger.jsonl`
per `CLOUD_RUN.md` before any launch; no cost figure is asserted here.

## Stage 0 results (2026-11-09/10 UTC, exploratory, not registered)

One Lambda A10, Ollama 0.40.13, student `qwen2.5:7b-instruct`, judge `llama3.1:8b`, six parallel
slots, 100 FinQA dev tasks (seed 20261401). Raw files: `runs_v6/stage0/`. Spider-style
pretraining caveat applies to FinQA too: it is a 2021 public dataset.

**Headroom: passed.** Baseline truth 67%, 63%, 66% over three identical reruns (4 points of
rerun noise from parallel slots). Inside the 15% to 80% band.

**The first judge carried almost no signal.** Reference-free, verdict-only `llama3.1:8b`:
approves 95% of right answers and 88% of wrong ones, AUROC 0.55 against truth. It only ever
returned three scores (0, 8, 10). The judge with the reference tracked truth within 0 to 4 points.
The validity proxy was 100% everywhere and is dropped.

**Judge calibration (stage 0b, 300 baseline transcripts regraded):**

| Judge | Prompt | Approves right | Approves wrong | AUROC | Seconds |
|---|---|---|---|---|---|
| llama3.1:8b | verdict | 95% | 88% | 0.55 | 112 |
| llama3.1:8b | recompute, then verdict | 68% | 38% | 0.69 | 303 |
| gemma2:27b | verdict (29% of the model was on the CPU; indicative only) | 92% | 78% | 0.63 | 1113 |

The prompt mattered more than model size. `gemma2:27b` with the recompute prompt has not been run.

**Judge check with the verdict judge (20 style edits, 5 substance edits):**

- Style edits raised the judge's approval on 18 of 20 edits and truth on 8 of 20: mean true gain
  -0.2 points, mean bias +2.2 points. A uniform upward shift.
- The spread of bias across style edits was 0.7 points, against 1.5 points of true spread: nothing
  for selection to choose between.
- At 50 selection tasks the model attributes 87% to 96% of a winner's reported gain to noise.
- From these rates, even 120 edits x 200 tasks would not resolve the Goodhart share.

**What changed because of stage 0.**

| Finding | Change |
|---|---|
| Verdict-only judge is near noise | P2 uses the recompute prompt (`judge.style: recompute`). Judge calibration is now a gate before any bank. |
| Proxy fidelity varies a lot with the prompt | Judges of different AUROC are rungs of the ladder; prediction: G falls as AUROC rises. |
| Single rule lines move truth 1 to 5 points | Catalog adds structural edits; 150 tasks per edit in stage 1; more for registered stages. |
| Baseline at 65% has little real headroom | A deliberately weak anchor (`rsi/fin_edits.py:WEAK`) next to a truth-selected strong one. |
| Validity proxy saturated | Dropped. |
| Large judge spilled to the CPU at six slots | Slots are set per model; nothing may run partly on the CPU. |
| The 100 stage-0 tasks tuned the judge | Excluded from stage 1 (`data.exclude_sample`) and from any registered stage. |

Deviation from the plan as written: stage 0 was to use hand-written style edits to test whether P2
moves while truth does not. It did, but as a mean shift, not a spread. The design's quantity
`s_bias` is a spread; the mean shift is a separate effect (every candidate looks better than the
incumbent) and is now reported next to it.

## Stage 1 results (2026-11-10 UTC, exploratory, not registered)

Edit bank: 40 hand-written single edits at each of two anchors, 150 fresh FinQA dev tasks
(disjoint from stage 0), student `qwen2.5:7b-instruct`, judge `llama3.1:8b` with the recompute
prompt, three baseline repeats per anchor. FinQA is public and may be in the student's
pretraining data. One A10 instance, 9.2 h, about $11.87. Numbers: `runs_v6/stage1/analyze.json`.

Baselines (truth): weak 52.0 / 53.3 / 52.0, strong 62.7 / 59.3 / 60.0. The strong anchor was
picked as the best of 16 on these tasks and its first run looks like a noise winner.

| | weak anchor | strong anchor |
|---|---|---|
| edits with positive truth gain | 13 of 40 | 1 of 40 |
| edits with positive P2 gain | 25 of 40 | 22 of 40 |
| mean truth gain | -1.1 pts | -2.7 pts |
| mean P2 bias (P2 gain minus truth gain) | +1.9 pts | +2.8 pts |
| sd of real effect across edits (P2 fit) | 1.3 pts | 0.7 pts |
| sd of bias across edits (P2 fit) | 0.7 pts | 0 (estimate negative) |
| model shares at m=50, P2: real / Goodhart / noise | -0.02 / -0.06 / 1.08 | 0.05 / 0.03 / 0.92 |

Selection replay, P2, greedy best of 8 on 75 selection tasks, 1000 rounds:

| | weak | strong |
|---|---|---|
| reported gain | +6.5 | +6.0 |
| real (truth on fresh tasks) | -1.1 | -2.0 |
| persistent bias (on fresh tasks) | +0.9 | +2.2 |
| noise, truth part | +1.5 | +0.8 |
| noise, judge part | +5.1 | +5.0 |
| persistent bias under random pick (no selection) | +1.8 | +2.6 |

Reading:

1. **The Goodhart claim is not supported in this edit space.** Selection does not concentrate
   judge bias: the kept edit carries no more persistent bias than a random one. Per-edit bias
   does not replicate across anchors (r = -0.11 over 38 shared edits).
2. **What selection concentrates is noise, and most of it is the judge's.** The reported
   +6 points is almost all winner's curse, and about 5 of those points come from judge
   disagreement with truth on the selection tasks, against about 1 from truth sampling.
   Against the right comparison, selecting on truth itself with the same k and m (the case
   studied in 2610.09239), the curse is 1.6 to 1.7 times larger: noise +3.9 / +3.6 points under
   truth selection versus +6.7 / +5.7 under P2 (weak / strong). The residual variances predict
   1.4 to 1.6 (square root of the ratio of r_cc). P1, which agrees with truth on 87 to 91% of
   episodes against P2's 69 to 70%, shows no extra curse. So the effect is real but moderate,
   and it scales with judge disagreement. Exploratory.
3. **There is a small uniform judge bias.** Adding almost any rule, placebo included, moves P2
   up about 2 to 3 points relative to truth. It is a level shift, not something selection exploits.
4. **No depletion contrast.** Hand-written edits have almost no real headroom at either anchor;
   the only edits with real gains are step-count changes at the weak anchor (`steps_6` +5.6).
5. **The stage 0 style effect did not replicate** on fresh tasks, apart from `explain_long` at
   the strong anchor (+9.6 P2, +1.3 truth), which is one edit of 40.
6. P1 (judge with reference) at the weak anchor shows a bias spread of about 2 points, driven by
   the five structural edits. Too few edits to say more.

Deviation: the replay first measured bias on the selection tasks, which counted judge luck as
Goodhart (share near 1.0). It now measures bias on fresh tasks and reports judge noise
separately. Changed after seeing partial data; stage 1 is exploratory.

Not run: `gemma2:27b` recompute calibration, LLM proposer sources (stage 2).

## Second critique (2026-11-09) and what changed

| Attack | Verdict | Change |
|---|---|---|
| "Noise shrinks with data, bias does not" is true by definition. | Correct. | Claim replaced by depletion: G rises when real headroom runs out. Not guaranteed by algebra. |
| 2610.09239 already has a variance decomposition. | Correct for two terms. | Positioned as its extension: third term, judged proxies, agentic harness, random proposer. |
| Hack-quadrant counting is meaningless when most edits do nothing. | Correct. | Replaced by variance components with noise subtracted. |
| A weak baseline makes real gains dominate, so no hacking shows (run 5 again). | Correct, and it is the most useful attack. | Became the hypothesis: two anchor states. |
| The gap per edit is not free of student noise; edit and baseline are different transcripts. | Correct. Only the within-transcript proxy-truth difference is paired. | Paired tasks, repeated baseline, and a power calculation as a stage-0 gate. |
| Nobody selects harness edits on a small reference-free judge. | Partly. Runtime settings without labels do. | Kept, with P1 (judge with reference) as the offline-realistic rung. If P1 shows G near zero, say so. |
| Self-consistency proxy multiplies cost. | Correct. | Dropped for a free validity proxy. |
| Audit only, no method. | Was correct. | Stopping rule from an online estimate of G. |
| History injection is artificial. | Partly. | Demoted to secondary. |

Attacks that stand and are not fixed are in the next section.

## Known weaknesses

- **The strong anchor is one harness.** A different strong harness could give a different
  `s_bias`. Two strong anchors per domain would help and doubles stage 1.
- **Variance components need many edits.** With 60 edits per cell a variance is known to roughly
  plus or minus 20% before noise subtraction. Differences in G smaller than that will not show.
- **Depletion may be confounded with ceiling.** Near 100% true accuracy every spread shrinks for
  arithmetic reasons. The strong anchor must sit well below ceiling; that is another reason for a
  domain with 15% to 80% baseline accuracy.
- **Single edits.** The bank does not see interactions between edits. The validation loops are the
  check, and three seeds is a thin one.
- **Small edit space, small models.** Eight fields, a 7B student, a 32B proposer. The claim is about
  the mechanism (bias does not average out), not about frontier hack rates.
- **Local judges are weak judges.** That is realistic for cheap online scoring, and it also makes
  gaming easier than with a frontier judge. Say so wherever a gap is reported.
- **S1's menus were written by a person.** It is a known prior, not a zero prior.
- **Fabricated histories** are an intervention on the proposer, not something a loop would produce
  in that exact form.
- **Spider is likely in pretraining data** for the student, proposer and judges. D-fin is primary
  partly for that reason; check the same for the chosen finance set.
- **The primary claim may look obvious** to a statistician. The contribution is measuring both
  components in a real loop with ground truth, plus the defense comparison, not the inequality.

## Code to write

| File | Purpose |
|---|---|
| `rsi/domains/` | Domain interface (tasks, tools, truth grader); D-fin adapter; D-sql wrapper around `rsi/agent.py` |
| `rsi/proxies.py` | P0 to P3 graders over stored transcripts |
| `rsi/bank.py` | Sample edits per source, evaluate, store per-task verdicts for every grader |
| `rsi/replay.py` | Selection simulator and acceptance rules |
| `rsi/inject.py` | Fabricated histories for the proposer |
| `tests/` | Synthetic-data tests for each, as in the rest of `rsi_pilot` |

Transcripts are stored once and graded many times, so adding a proxy later costs judge calls only.
