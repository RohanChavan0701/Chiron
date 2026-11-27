# Run 8 design: weights versus prompt for the same information (LoRA arm)

Status: DESIGN ONLY (2026-11-27). No code, no data, no run. `PREDICTION_run8.md` is a draft
and is not registered. Nothing here was executed on a GPU.

## Where this comes from

The run-5 ablation (`PREDICTION_schema_only.md`, result 2026-11-27) showed that one prompt
field, `schema_upfront: full`, carries the evolved harnesses' whole held-out gain: +11.6 pp on
H and +22.5 pp on B, same-session paired, 6 of 6. The information the student lacked was the
schema, delivered in context. The project's plans name the next question in several places
(`docs/RSI_MEM_PLAN.md` Phase 5, G5.1 to G5.4; `docs/RSI_MEM_V2_FINANCE.md` Phase 5): when
in-context delivery of some information works, does delivering the *same* information through
weights (a LoRA adapter) work as well, worse, or better, and do the two add?

Run 8 asks that on the run-5 substrate, where the information is known and its in-context
effect is measured.

## Why not "LoRA on verified teacher repairs" in the core loop

The checklist item was a LoRA fine-tune on the correction stage's verified teacher repairs. The
repo holds **11 real teacher-verified pairs** (`fixtures/demo_events.jsonl`, 11 teacher, 13 gold
fallback, 2 anchor); `events.jsonl` and `runs/` are gitignored and no other real correction
output is committed. Eleven pairs do not train an adapter. Collecting more needs the MiniMax
teacher API and the Spider SQLite databases, which are also not committed, and would add a
teacher-cost variable the ablation never had. Run 8 therefore uses the rsi_pilot substrate,
whose splits, leakage log and held-out guard already exist, and whose "teacher" is a harness
whose effect is measured: the schema-upfront harness verified against gold.

## Four conditions

All four are scored fresh in the same session, on the same server, on the fixed H (200 Spider
dev hard/extra) and B (200 BIRD Mini-Dev) sets as run 5 and the ablation.

| # | Student weights | Harness | Tests |
|---|---|---|---|
| 1 | base `qwen2.5:7b-instruct` | run-5 baseline (`schema_upfront: tables`) | the floor, same as the ablation's baseline |
| 2 | base | `schema_only` (`schema_upfront: full`) | the prompt route, replicates the ablation |
| 3 | base + LoRA | baseline | the weights route alone: does the adapter carry what the schema prompt carried, with the schema removed from context? |
| 4 | base + LoRA | `schema_only` | additivity, and whether the adapter hurts when the prompt already supplies the information |

Memory removed means exactly what it did in the plans: condition 3 sees only table names at
step 1, as the baseline does.

## Training data for the adapter (OPHSD-style, G5.1)

- Source tasks: Spider **train** only (the E and E2 pools' parent set, DB-disjoint from H and B,
  as in run 5; `formula_1` excluded as before). Target about 1,500 tasks, hard/extra by the
  repo's heuristic preferred, easy/medium admitted to reach the count.
- Rollouts: the base student runs each task with the `schema_only` harness. A rollout is kept
  only if its submitted SQL is correct by execution against gold (the same checker as the
  evaluations). Expected keep rate about 55 to 60% from the ablation's H numbers on a harder
  set, so about 800 to 900 trajectories; if under 500, stop and report.
- Target: supervised fine-tuning of the assistant turns of each kept trajectory, with the
  schema block **removed from the first user message** so the adapter is trained to act as the
  baseline harness would present the task. The tool observations stay as they were. This is
  the "distill the assisted behaviour into the bare student" recipe; the student never sees
  gold SQL, only its own verified rollouts.
- Adapter: LoRA rank 16, alpha 32, attention and MLP projections, 2 epochs, learning rate 1e-4,
  bf16, sequence length 4,096, seed per session. These are conventional values, not tuned;
  one configuration, no hyperparameter search (a search would need a validation set drawn from
  E2 and a second pre-registration).
- One adapter per session (three sessions, three seeds for the rollout sample and the training
  order). The adapter is trained inside the session that scores it.

## Serving

All four conditions are served by one **vLLM** OpenAI-compatible server with `--enable-lora`,
the base model and the session's adapter registered under two model names; conditions 1 and 2
use the base name, 3 and 4 the adapter name. This is a deviation from run 5 and the ablation
(Ollama 0.40.13, 8 slots) and is why conditions 1 and 2 are re-scored here rather than copied:
only within-session comparisons are evidence. Temperature 0, seed fixed, as before.

Code needed (none exists): an `openai_compatible` student in `rsi/student.py` (the proposer
client in `rsi/llm.py` is the model); a rollout harvester that keeps the **full** assistant
text (the agent currently records tool calls truncated to 500 characters, `rsi/agent.py`
146-160, which is not enough to train on); a trajectory-to-SFT exporter with the schema-strip
step and a test that the stripped first message equals the baseline harness's first message
byte for byte; a training script (`peft` + `transformers`); the session driver. The harvester
change touches the agent, so it is gated on the author.

## Endpoints (to freeze before registration)

- **Primary.** Condition 3 minus condition 1 on H, per session, net tasks and pp; mean, SD,
  exact Wilcoxon over sessions. With 3 sessions the smallest two-sided p is 0.25, so the
  primary is reported as an estimate with its SD, not as a test; six sessions would allow
  p = 0.031 and cost twice as much.
- **Secondary.** Condition 2 minus 1 (replication of the ablation under vLLM); 3 minus 2
  (weights versus prompt, the question); 4 minus 2 (additivity); all four on B; tokens per
  task per condition (the adapter's route has no schema tokens, so 3 should be the cheapest).
- **Diagnostics.** Rollout keep rate; adapter training loss curve; fraction of condition-3
  trajectories that call `describe` before the first `run_sql` (does the adapter learn to
  fetch the schema it no longer gets for free, or to guess columns?).

## Cost and time (A100 80 GB, one session)

Modal A100-80GB at 3.13 USD/h all-in, or Lambda A100 40 GB SXM4 at 1.99 USD/h (live price
2026-11-27; a 7B bf16 LoRA at 4k context fits 40 GB with gradient checkpointing, micro-batch 1).

| Step | Estimate | Basis |
|---|---|---|
| Harvest 1,500 Spider-train tasks, schema_only, 8 slots | 10 to 15 min | ablation: 400 tasks per 5 min per evaluation on A100 |
| LoRA SFT, about 850 trajectories x 2 epochs x about 2,500 tokens | 15 to 25 min | 7B LoRA, bf16, A100 |
| Score 4 conditions x (H + B) = 8 evaluations | 40 min | ablation: 10 evaluations in 23 to 28 min |
| Setup (vLLM, model pull) | 15 min | |
| **Per session** | **about 1.5 h, 3 to 5 USD** | |
| Three sessions | about 4.5 h, 10 to 15 USD | cap requested: 20 USD |

Nothing above was timed; the figures are extrapolations from the ablation's Modal records and
need a smoke session (50 harvest tasks, 1 training step, 20 held-out tasks) before the cap is
committed.

## Known weaknesses, stated now

- Spider 1.0 and BIRD are public; the student may have seen them. The claim is relative
  (weights versus prompt on the same held-out tasks), not an absolute accuracy claim.
- vLLM versus Ollama numerics differ; condition 1 here is not the ablation's baseline and is
  not compared with it except as context.
- The adapter is trained on the student's own rollouts on Spider train and evaluated on Spider
  dev and BIRD; a gain on B is the transfer result, a gain on H alone is not.
- Three sessions give an estimate, not a test. Reported as such.
- One LoRA configuration. A null may be a tuning failure; the design accepts that and says so.
