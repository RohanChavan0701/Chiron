"""Baseline phase: noise floor on E, then the baseline on E, H and B.

1. Runs the baseline harness on E `--reps` times without the cache. The spread
   (max - min tasks passed) is the noise floor; evolution keeps an edit only if
   it beats the current harness by at least spread + 1 tasks.
2. Runs the baseline on H and B (allowed: the baseline is never tuned).
3. Prints the sanity checks from the plan: E baseline in about 15% to 80%,
   B baseline at least 5%, and seconds per task.

Run 4 (`evolution.placebo: true`): also scores 10 placebo harnesses (meaning-preserving
rewordings of the system prompt, rsi/edits.py) on E. Arm B's keep threshold is the
smallest gain that the best of `candidates_per_generation` placebo edits reaches with
probability <= `placebo_alpha`. The baseline is also run on E2.

CLI: python -m rsi.baseline [--reps 3] [--workers 1]
"""
from __future__ import annotations

import argparse
import json

from rsi.config import RUNS, ROOT, load_yaml
from rsi.edits import PLACEBO_PROMPTS, placebo_threshold
from rsi.harness import diff_fields
from rsi.runner import evaluate, load_context


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args()
    ctx = load_context(workers=args.workers)
    h = load_yaml(ROOT / "harness.yaml")

    reps = [evaluate(ctx, h, "E", use_cache=False, purpose=f"noise_rep{i}") for i in range(args.reps)]
    passed = [r["passed"] for r in reps]
    flips = sorted(k for k in reps[0]["vector"] if len({r["vector"][k] for r in reps}) > 1)
    nf = {"reps": args.reps, "passed": passed, "spread_tasks": max(passed) - min(passed),
          "flipping_tasks": flips, "student": ctx.cfg["student"]}
    ev = ctx.cfg["evolution"]
    if ev.get("placebo"):
        base_e = reps[-1]["passed"]
        deltas, ids = [], []
        for i, prompt in enumerate(PLACEBO_PROMPTS):
            ph = {**h, "system_prompt": prompt}
            if not diff_fields(h, ph):
                continue
            r = evaluate(ctx, ph, "E", purpose=f"placebo{i}")
            deltas.append(r["passed"] - base_e)
            ids.append(r["harness_id"])
        k = ev["candidates_per_generation"]
        nf["placebo"] = {"deltas_tasks": deltas, "harness_ids": ids, "k": k, "alpha": ev["placebo_alpha"],
                         "threshold_tasks": placebo_threshold(deltas, k, ev["placebo_alpha"],
                                                              ev["min_keep_delta_tasks"])}
    (RUNS / "noise_floor.json").write_text(json.dumps(nf, indent=1))

    out = {"E": reps[-1]}
    for split in [s for s in ctx.tasks if s != "E"]:
        out[split] = evaluate(ctx, h, split, purpose="baseline")
    (RUNS / "evals").mkdir(parents=True, exist_ok=True)
    for split, res in out.items():
        (RUNS / "evals" / f"baseline_{split}.json").write_text(json.dumps(res, indent=1))

    print(f"Noise floor: E passed across {args.reps} runs = {passed}; spread {nf['spread_tasks']}; "
          f"{len(flips)} tasks flipped")
    if "placebo" in nf:
        print(f"Placebo deltas on E: {nf['placebo']['deltas_tasks']} -> Arm B keep threshold "
              f"{nf['placebo']['threshold_tasks']} tasks")
    for split, res in out.items():
        sec = res["student_seconds"] / max(res["n"], 1)
        print(f"Baseline {split}: {res['passed']}/{res['n']} = {res['accuracy']:.1%} | {sec:.2f}s/task")
    e = out["E"]["accuracy"]
    if not 0.15 <= e <= 0.80:
        print(f"WARNING: E baseline {e:.0%} is outside 15%-80%; the loop has little room to move. "
              "Change E's difficulty mix (frozen.yaml splits.e_hardness), regenerate splits, record it.")
    if out["B"]["accuracy"] < 0.05:
        print("WARNING: B baseline below 5%. Regenerate splits with --bird-fallback and record it in the README.")
    sec = out["E"]["student_seconds"] / max(out["E"]["n"], 1)
    if sec > 2:
        print(f"NOTE: {sec:.1f}s/task > 2s. Consider candidates_per_generation: 2 in frozen.yaml.")


if __name__ == "__main__":
    main()
