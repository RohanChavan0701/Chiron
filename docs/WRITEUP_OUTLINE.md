# Write-up outline: "Four ways a self-improvement loop fooled its own metric"

Status: outline, not prose. Every number below has a source file; do not change a number
without changing the source. Target 1,800 to 2,500 words plus three figures. Venue: a
post on a personal site or GitHub Pages, cross-posted to LessWrong / Alignment Forum, with
the repo linked in the first paragraph.

## Working titles

1. Four ways a self-improvement loop fooled its own metric
2. Tuning-set gains that never left the tuning set: a self-correction post-mortem
3. What it took to find out my agent wasn't learning

Pick 1 unless it reads as clickbait after drafting. The title must not promise a positive
result.

## Thesis (one paragraph, goes first)

I built a runtime self-correction loop for small language models: detect accuracy drift,
have a stronger teacher repair the failures, verify the repairs by execution, and feed them
back as prompt memory. It worked on every same-distribution demo I ran. Then I added the
controls a result needs to survive (frozen held-out splits, frozen memory, repeated runs,
paired tests, test-suite re-scoring, pre-registration), and across three domains and a
harness-evolution variant the gains did not survive any of them. The contribution is not the
loop. It is the list of ways the loop's own metric was wrong, and the control that caught
each one.

## Audience

Research engineers and evals people at labs. They will skim for the method, the numbers,
and whether you knew what you were measuring. Write for a reader who will open the repo.

## Section plan

### 1. The system in six sentences (with Figure 1a)

Student, detector, teacher, verified few-shot memory, student re-run. Weights never change.
Four stages, one event log. Adapters: Spider text-to-SQL, coding (MBPP+/HumanEval+), GSM8K.
Link `README.md` and `docs/architecture.svg`. Keep this short; the reader can get the rest
from the repo.

### 2. Fooled once: same-distribution recovery is not transfer

Source: `docs/FINDINGS_CODING.md` sections A to C, `README.md` Results.

- Coding, Llama-3.2-3B student, MiniMax-M2.5 teacher: hard-bucket 0.273 → 0.455 after
  correction (+0.182). Single seed, same stream. This is the number a demo would show.
- Hard-curriculum eval, same student: 0.111 → 0.111. Zero transfer.
- Frozen-memory ablation, n=29 held-out hard: none 0.103, examples 0.034, rules 0.103, both
  0.034. Injection audit confirmed 2.93 examples per prompt, 0% zero-injection, so
  retrieval plumbing was not the failure.
- Control that caught it: freeze memory, score on problems not used to build it.

Point to make: "teacher-verified" and "useful to the student" are different properties.
The teacher's repairs were correct. They did not help.

### 3. Fooled twice: the student was below the floor

Source: `docs/FINDINGS_CODING.md` sections C to F.

- Capacity pair on identical questions: qwen3-coder bare 0.931 vs 3B+memory 0.034, 26/29
  discordant, McNemar p ≈ 0.0000. The 3B student could not use the memory.
- Band sweep: a student has to sit roughly 0.3 to 0.6 unaided or the experiment cannot
  show learning. Table of six models with verdicts.
- In-band replication, mistral-nemo: curriculum pass +0.172, frozen ablation 0.000,
  confirmed by 4 repeats where per-repeat delta was +0.059, +0.029, −0.029, −0.059.
- In-band replication, Qwen3.5-4B: examples arm 0.552 → 0.310, Δ −0.241, 10 regressed vs 3
  improved, 95% CI [−0.473, −0.010]. Three repeats at temp 0: Δ −0.265 identical every time.
  Deterministic harm.
- KG rules channel: zero discordant pairs across all three students. Inert.
- Control that caught it: repeat runs at temp 0 and look at per-question flips before
  trusting a single-run p-value. Deltas under ~0.06 are noise on this stack.

Point to make: fixing capacity made the result worse, not better. The in-band student was
the one that was deterministically harmed.

### 4. Fooled three times: a utility gate that passed validation and failed held-out

Source: `docs/FINDINGS_REASONING.md`.

- GSM8K, Llama-3.2-3B (in band at 0.467). Gate kept only items with measured positive
  uplift on a LEARN validation slice: kept 3 of 8 candidates, dropped u ≤ 0.
- Curriculum headline +0.083 (0.333 → 0.417).
- Frozen ablation, same 28 held-out questions: none 0.321, uplift-memory 0.179, Δ −0.143,
  3 improved / 7 regressed, p = 0.34. Direction is harm.
- 43% of held-out prompts received zero of the three items (topic-filtered retrieval).
  Validation uplift was real and did not predict held-out relevance.
- Control that caught it: frozen ablation again, plus the injection audit that explained why.

### 5. Fooled four times: harness evolution overfits the tuning set (Figure 2)

Source: `rsi_pilot/README.md`, `rsi_pilot/runs_pooled_v2v3.md`.

- Setup: an LLM proposer edits the student's harness config (RRSI-style, arXiv 2609.24972).
  E = 50 Spider dev hard tasks for evolution; H = 50 Spider dev hard tasks from databases
  not in E; B = 50 BIRD Mini-Dev. Arm A unconstrained, Arm B RRSI-lite (edit budget, critic,
  pruner). 1.5B student, 14B proposer. The runner refuses to score a non-baseline harness
  on H or B until both arms are final, and logs every access.
- Pooled over four runs (200 tasks per set): A vs baseline E +20 (p = 0.007), H −9
  (p = 0.20), B +1. B vs baseline E +19 (p = 0.014), H −2 (p = 0.86), B +1.
- Run 2 alone showed B over A on H by +18% (p = 0.049). It did not replicate: −6% and +2%
  in the next two seeds. Pooled +7 of 200, p = 0.25. Say plainly that this was reported as
  a lead and then killed by replication.
- One of three replicates found no edit worth keeping in either arm. The critic rejected
  zero candidates across all replicates.
- Control that caught it: split held-out by database, not by random task, because Spider
  dev has 20 databases and a random split makes H nearly a re-test of E.

### 6. The metric itself was wrong (Figure 3)

Source: `rsi_pilot/README.md` Audit section.

- Re-scoring run 1 on Spider's test-suite databases: about half of E passes were false
  positives, many from gold queries that return no rows. baseline 24 → 12, A 31 → 16,
  B 29 → 13. E gains shrank from +7 to +4 (A) and +5 to +1 (B).
- Fix in run 2: exclude tasks whose gold query returns no rows. Test-suite false positives
  fell to 2 to 4 of 20 to 25.
- Spider 1.0 is also the benchmark most likely to be in the student's pretraining
  (SPENCE, ACL 2026, arXiv 2604.17771). This affects all arms equally and caps absolute
  claims. BIRD is the cleaner held-out set, which is why it is in the design.
- Control that caught it: run two verifiers on every task and report their disagreement
  rate; re-score passes against a stricter oracle.

### 7. What I would say to someone building one of these

Keep to five or six items. Candidates:

1. Freeze the held-out set before the first run and make the code refuse to touch it.
2. Freeze memory before scoring. Same-stream recovery is a demo, not a result.
3. Repeat at temp 0 and count per-question flips; the aggregate hides them.
4. Measure memory by consumer gain, not producer correctness.
5. Check the verifier against a stricter oracle before optimizing against it.
6. Pre-register. Runs 1 to 3 did not; run 4 does, and the prediction is a null.

### 8. What is pre-registered next (short)

Source: `rsi_pilot/PREDICTION.md`.

Run 4: 10 seeds, E = 100 and a fresh E2 = 100 from the same databases, H = all 322 eligible
Spider dev hard/extra, B = all 398 eligible BIRD Mini-Dev. Adds Arm C (random edits, same
keep rule) as the selection control. Primary endpoint B vs A on H by exact Wilcoxon across
seeds. Predicted: B ahead by about 3 tasks and not significant; A's E-minus-E2 selection gap
significant; A no better than random search on H; no arm's held-out gain above 1% of the set.
State who wrote the predictions (the assistant, at the author's request) and that the commit
precedes any result. Promise a follow-up post with the result either way.

### 9. Related work (one paragraph, no survey)

RRSI (2609.24972) for the regularization ideas Arm B borrows. HGM (2510.21614) for the
claim that tuning-set score does not predict self-improvement potential, which is what
section 5 observes. TTRL (2504.16084) for self-signal collapse, the same shape as the
test-suite false positives in section 6. TraceLift (2605.03862) for utility-gated memory,
which section 4 implements and finds insufficient. DGM (2505.22954) as the positive result
this work does not reproduce at small scale. One sentence each.

## Figures

1. (a) Architecture, reuse `docs/architecture.svg`. (b) Coding: same-distribution recovery
   curve next to the frozen-ablation bars for the same student. Two panels, one message.
2. rsi_pilot pooled net tasks, E vs H vs B, both arms, with the sign-test p above each bar.
   Data in `rsi_pilot/runs_pooled_v2v3.md`.
3. E passes before and after test-suite re-scoring, run 1, three harnesses. Data in
   `rsi_pilot/README.md` Audit table.

## What not to claim

- Do not say regularization "helps." Pooled B vs A on H is +7 of 200, p = 0.25.
- Do not say the loop "fails." It fails to transfer at these scales with these students.
- Do not cite the Spider +0.233 / +0.267 numbers from `docs/design.md` without saying they
  are 30-query same-distribution demos.
- Do not describe the proposer as frontier. It is 14B (runs 1 to 3) and 32B (run 4).
- Do not drop the "predictions were not registered for runs 1 to 3" admission.

## Before publishing

- [ ] Fill `rsi_pilot/runs*/audit_bird_labels.csv` (20 BIRD passes per run, hand-labeled).
      It has sat empty across four runs and a reader will ask.
- [ ] Decide: publish on runs 1 to 3 now with run 4 as the pre-registered follow-up, or wait
      for run 4. Recommendation: publish now. The pre-registration is itself evidence of
      discipline, and waiting blocks on GPU time.
- [ ] Regenerate the three figures from the source files, not from memory.
- [ ] Have one person who has not seen the repo read it and say back what the claim is.
- [ ] Repo on `main`: README links `rsi_pilot`, `docs/FINDINGS_*.md`, this outline removed
      or replaced by the published post's URL.
