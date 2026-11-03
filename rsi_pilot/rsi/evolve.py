"""Harness evolution on E only. Two arms:

A (unconstrained): any number of fields per edit; best E score wins. Leak checks
  are run and logged but not enforced, so we can report how often A leaks.
B (regularized, RRSI-lite): at most `arm_b_max_fields` fields per edit, dropping
  to `arm_b_max_fields_late` from generation `arm_b_late_from_generation`;
  deterministic leak check plus an LLM critic reject benchmark-specific edits;
  after the run, any field whose revert to baseline does not lower E is reverted.

A candidate is kept only if it beats the current harness on E by at least the
keep threshold: max(min_keep_delta_tasks, noise spread + 1), where the noise
spread comes from runs/noise_floor.json (baseline run 3x on E).

Run 4 (`evolution.arms: [A, B, C]`):
C (random search, the selection control): no LLM. Each candidate is a random valid
  edit from rsi/edits.py; same keep rule as A. Tests whether A's tuning-set gain is
  more than best-of-N selection.
A keeps any edit that improves E by `unreg_keep_delta_tasks` (the paper's
  unregularized baseline). B keeps an edit only if it beats the placebo threshold
  (rsi.baseline) and uses a cosine edit budget (`arm_b_budget: cosine`).

CLI: python -m rsi.evolve --arm A   (B and C can run in parallel)
"""
from __future__ import annotations

import argparse
import json
import random
import time

import yaml

from rsi.config import BASELINE, HARNESS_KIND, RUNS, ROOT, append_jsonl, dump_yaml, load_yaml, resolve
from rsi.edits import cosine_budget, random_edit
from rsi.harness import EDITABLE_FIELDS, HarnessError, diff_fields, harness_id, validate
from rsi.leakcheck import LeakChecker
from rsi.llm import make_llm, parse_json
from rsi.runner import Context, evaluate, load_context
from rsi.schema import serialize

PROPOSER_SYSTEM = """You improve the harness of a small text-to-SQL model (a 1.5B-parameter student).
The model is frozen; you may only change harness configuration fields.
Propose edits that would help on unseen databases and questions, not just the failures shown.
Return only JSON."""

if HARNESS_KIND == "agent":
    # Run 5. Prompts for the sql kind stay byte-identical to runs 1-4.
    PROPOSER_SYSTEM = """You improve the harness of a small SQL agent (a local 7B-parameter student) that
explores a database with tools (list_tables, describe, run_sql) and then submits one SQL query.
The model is frozen; you may only change harness fields: its prompts, tool guide, a rules
memory shown before every task, and loop settings.
Propose edits that would help on unseen databases and questions, not just the failures shown.
Return only JSON."""

CRITIC_SYSTEM = """You audit proposed harness edits for a text-to-SQL agent.
An edit is benchmark-specific if it encodes knowledge of the particular databases, tables,
columns, values, questions or answers it was tuned on, rather than general text-to-SQL practice.
Return only JSON."""


def field_spec() -> str:
    return "\n".join(f"- {k}: {d}" for k, (_, d, _) in EDITABLE_FIELDS.items())


def failure_traces(ctx: Context, res: dict, k: int, rng: random.Random, show_gold: bool) -> str:
    by_id = {t.task_id: t for t in ctx.tasks["E"]}
    fails = [r for r in res["records"] if not r["pass"]]
    picks = rng.sample(fails, min(k, len(fails)))
    out = []
    for i, r in enumerate(picks, 1):
        t = by_id[r["task_id"]]
        schema = serialize(t.db_path, "compact", 0, True)
        s = (f"## Failure {i}\nSchema:\n{schema}\nQuestion: {t.question}\n"
             f"Model SQL (final attempt): {r['pred_sql']}\n"
             f"Outcome: {'execution error: ' + r['pred_error'] if r['pred_error'] else 'ran but returned the wrong result'}\n"
             f"Attempts used: {r['n_attempts']}")
        if HARNESS_KIND == "agent":
            steps = "; ".join(f"{a['tool']}({(a['arg'] or '')[:80]})" for a in r["attempts"])
            s += f"\nAgent steps ({r.get('ended', '?')}): {steps}"
        if show_gold:
            s += f"\nGold SQL: {t.gold_sql}"
        out.append(s)
    return "\n\n".join(out)


def edit_history(log_path, max_items: int = 20) -> str:
    """Earlier candidates this arm tried, with outcome, so the proposer does not repeat them."""
    from rsi.config import read_jsonl
    lines = []
    for r in read_jsonl(log_path):
        if r.get("event") != "candidate":
            continue
        out = f"E={r['E_passed']}" if "E_passed" in r else r.get("decision", "?")
        lines.append(f"- gen {r['gen']}: {json.dumps(r.get('edits'), ensure_ascii=False)[:400]} -> {out}")
    if not lines:
        return "None yet."
    return "\n".join(lines[-max_items:])


def proposer_prompt(cur: dict, res: dict, traces: str, n: int, max_fields: int | None,
                    history: str | None = None) -> str:
    # Empty when history is off, so run-1 prompts are unchanged byte for byte.
    hist_block = ("" if history is None else
                  "\nEdits already tried in earlier generations (do not repeat these; prefer untried "
                  "directions):\n" + history + "\n")
    limit = (f"Each candidate may change at most {max_fields} field(s)." if max_fields
             else "Each candidate may change any number of fields.")
    return f"""Current harness (YAML):
```yaml
{yaml.safe_dump(cur, sort_keys=False)}```

Editable fields and allowed values:
{field_spec()}

Current score on the tuning set: {res['passed']}/{res['n']}.
{hist_block}
Failure traces from the tuning set:
{traces}

Propose exactly {n} different candidate edits. {limit}
Only include fields you change, with their complete new values.
Return a JSON array: [{{"edits": {{"field": new_value}}, "rationale": "one sentence"}}]"""


def critic_prompt(cur: dict, new: dict, rationale: str) -> str:
    changed = {k: {"old": cur[k], "new": new[k]} for k in diff_fields(cur, new)}
    return f"""Proposed edit (old and new values):
```json
{json.dumps(changed, indent=1)}
```
Proposer's rationale: {rationale}

Is this edit benchmark-specific? Return {{"benchmark_specific": true|false, "reason": "one sentence"}}"""


def prune_decision(e_with: int, e_without: int, tok_with: int, tok_without: int,
                   threshold: int, cost_ratio: float | None) -> tuple[bool, str]:
    """Revert a field if removing it does not lower E, or (RRSI's cost rule) if its E gain
    is within noise (< keep threshold) while it makes the harness cost_ratio x more expensive."""
    if e_without >= e_with:
        return True, "no_E_loss"
    if cost_ratio and (e_with - e_without) < threshold and tok_with > cost_ratio * tok_without:
        return True, "gain_within_noise_and_expensive"
    return False, "keeps_its_weight"


def keep_threshold(cfg: dict, runs_dir=RUNS, arm: str = "B") -> int:
    ev = cfg["evolution"]
    if arm in ("A", "C") and "unreg_keep_delta_tasks" in ev:
        return ev["unreg_keep_delta_tasks"]
    base = ev["min_keep_delta_tasks"]
    nf = runs_dir / "noise_floor.json"
    if nf.exists():
        d = json.loads(nf.read_text())
        if "placebo" in d:
            return max(base, d["placebo"]["threshold_tasks"])
        return max(base, d["spread_tasks"] + 1)
    if ev.get("arm_b_budget") == "cosine":
        raise FileNotFoundError("run 4 needs noise_floor.json with placebo results; run rsi.baseline first")
    return base


def max_fields_for(ev: dict, arm: str, g: int) -> int | None:
    if arm == "B":
        if ev.get("arm_b_budget") == "cosine":
            return cosine_budget(g, ev["generations"], ev["arm_b_max_fields"], ev["arm_b_min_fields"])
        return ev["arm_b_max_fields"] if g < ev["arm_b_late_from_generation"] else ev["arm_b_max_fields_late"]
    if arm == "C":
        return ev.get("arm_c_max_fields", 3)
    return None


def run_arm(ctx: Context, arm: str, llm, critic=None) -> dict:
    ev = ctx.cfg["evolution"]
    out_dir = ctx.runs_dir / f"arm_{arm}"
    if (out_dir / "final.yaml").exists():
        raise FileExistsError(f"{out_dir}/final.yaml exists; move it aside to rerun")
    out_dir.mkdir(parents=True, exist_ok=True)
    log = out_dir / "log.jsonl"
    rng = random.Random(f"{ctx.cfg['seed']}-{arm}")
    threshold = keep_threshold(ctx.cfg, ctx.runs_dir, arm)
    critic = critic or llm

    # `base_harness` (POISON_AUDIT.md persistence phase) starts evolution from an evolved
    # harness instead of the baseline harness. Pruning and the summary still compare to the
    # baseline, so a field inherited from the starting harness can be reverted if it no longer
    # earns its keep.
    orig = validate(load_yaml(BASELINE))
    base = validate(load_yaml(resolve(ev["base_harness"]))) if ev.get("base_harness") else orig
    cur = dict(base)
    cur_res = evaluate(ctx, cur, "E", purpose=f"evolve_{arm}")
    leak = LeakChecker(ctx.tasks["E"])
    # Run 4: also log (never act on) edits that name held-out identifiers, so the audit can
    # report them. Acting on them would feed held-out information into selection.
    hleak = (LeakChecker([t for s in ("H", "B") for t in ctx.tasks[s]], ngram=10**6)
             if "E2" in ctx.tasks else None)
    append_jsonl(log, {"event": "start", "arm": arm, "time": time.time(), "keep_threshold": threshold,
                       "harness_id": harness_id(cur), "E_passed": cur_res["passed"],
                       "proposer": None if arm == "C" else ctx.cfg["proposer"].get("model"),
                       "critic": (ctx.cfg.get("critic") or ctx.cfg["proposer"]).get("model") if arm == "B" else None})

    for g in range(1, ev["generations"] + 1):
        max_fields = max_fields_for(ev, arm, g)
        if arm == "C":
            cands = [{"edits": random_edit(cur, rng, max_fields), "rationale": "random"}
                     for _ in range(ev["candidates_per_generation"])]
            append_jsonl(log, {"event": "proposals", "gen": g, "n": len(cands), "proposer_model": "random"})
        else:
            traces = failure_traces(ctx, cur_res, ev["failures_shown"], rng, ev["show_gold_sql_to_proposer"])
            history = (edit_history(log, ev.get("history_items", 20)) if ev.get("show_edit_history", False)
                       else None)
            prompt = proposer_prompt(cur, cur_res, traces, ev["candidates_per_generation"], max_fields, history)
            reply = llm(PROPOSER_SYSTEM, prompt)
            try:
                cands = parse_json(reply.text)
                if isinstance(cands, dict):
                    cands = [cands]
            except ValueError as e:
                cands = []
                append_jsonl(log, {"event": "proposer_parse_error", "gen": g, "error": str(e), "reply": reply.text})
            append_jsonl(log, {"event": "proposals", "gen": g, "n": len(cands), "proposer_model": reply.model,
                               "proposer_tokens": [reply.input_tokens, reply.output_tokens],
                               "max_fields": max_fields})

        scored = []
        for ci, c in enumerate(cands[: ev["candidates_per_generation"]]):
            rec = {"event": "candidate", "gen": g, "idx": ci, "edits": c.get("edits"),
                   "rationale": c.get("rationale", "")}
            try:
                edits = c.get("edits") or {}
                if not isinstance(edits, dict) or not edits:
                    raise HarnessError("empty or non-object edits")
                new = validate({**cur, **edits})
            except (HarnessError, AttributeError, TypeError) as e:
                rec.update(decision="rejected_invalid", reason=str(e)); append_jsonl(log, rec); continue
            changed = diff_fields(cur, new)
            rec["changed_fields"] = changed
            if not changed:
                rec.update(decision="rejected_noop"); append_jsonl(log, rec); continue
            problems = leak.check(cur, new)
            rec["leak_problems"] = problems
            if hleak is not None:
                rec["heldout_name_hits"] = hleak.check(cur, new)
            if arm == "B":
                if len(changed) > max_fields:
                    rec.update(decision="rejected_too_many_fields", max_fields=max_fields); append_jsonl(log, rec); continue
                if problems:
                    rec.update(decision="rejected_leakcheck"); append_jsonl(log, rec); continue
                cr = critic(CRITIC_SYSTEM, critic_prompt(cur, new, rec["rationale"]))
                try:
                    verdict = parse_json(cr.text)
                except ValueError:
                    verdict = {"benchmark_specific": True, "reason": "unparseable critic reply; rejected to be safe"}
                rec["critic"] = verdict
                if verdict.get("benchmark_specific", True):
                    rec.update(decision="rejected_critic"); append_jsonl(log, rec); continue
            res = evaluate(ctx, new, "E", purpose=f"evolve_{arm}")
            rec.update(decision="scored", harness_id=harness_id(new), E_passed=res["passed"],
                       tokens=res["prompt_tokens"] + res["completion_tokens"])
            append_jsonl(log, rec)
            scored.append((res["passed"], -(res["prompt_tokens"] + res["completion_tokens"]), ci, new, res))

        if scored:
            scored.sort(key=lambda x: (x[0], x[1], -x[2]), reverse=True)
            best_passed, _, best_idx, best, best_res = scored[0]
            delta = best_passed - cur_res["passed"]
            kept = delta >= threshold
            append_jsonl(log, {"event": "generation", "gen": g, "best_idx": best_idx, "delta": delta,
                               "threshold": threshold, "kept": kept})
            if kept:
                cur, cur_res = best, best_res
                dump_yaml(cur, out_dir / f"gen{g}.yaml")
        else:
            append_jsonl(log, {"event": "generation", "gen": g, "kept": False, "reason": "no scorable candidates"})

    if arm == "B":
        for f in diff_fields(orig, cur):
            trial = validate({**cur, f: orig[f]})
            res = evaluate(ctx, trial, "E", purpose="evolve_B_prune")
            tok_with = cur_res["prompt_tokens"] + cur_res["completion_tokens"]
            tok_without = res["prompt_tokens"] + res["completion_tokens"]
            reverted, why = prune_decision(cur_res["passed"], res["passed"], tok_with, tok_without,
                                           threshold, ev.get("prune_cost_ratio"))
            append_jsonl(log, {"event": "prune", "field": f, "E_with": cur_res["passed"],
                               "E_without": res["passed"], "tokens_with": tok_with,
                               "tokens_without": tok_without, "reverted": reverted, "why": why})
            if reverted:
                cur, cur_res = trial, res

    dump_yaml(cur, out_dir / "final.yaml")
    summary = {"arm": arm, "final_harness_id": harness_id(cur), "E_base": None, "E_final": cur_res["passed"],
               "n": cur_res["n"], "changed_from_baseline": diff_fields(orig, cur), "keep_threshold": threshold}
    if ev.get("base_harness"):
        summary["started_from"] = str(ev["base_harness"])
        summary["changed_from_start"] = diff_fields(base, cur)
    summary["E_base"] = evaluate(ctx, orig, "E", purpose=f"evolve_{arm}")["passed"]
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    append_jsonl(log, {"event": "done", **summary})
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=["A", "B", "C"])
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args()
    ctx = load_context(workers=args.workers)
    llm = None if args.arm == "C" else make_llm(ctx.cfg["proposer"])
    critic = make_llm(ctx.cfg["critic"]) if (ctx.cfg.get("critic") and args.arm == "B") else None
    s = run_arm(ctx, args.arm, llm, critic)
    print(json.dumps(s, indent=1))


if __name__ == "__main__":
    main()
