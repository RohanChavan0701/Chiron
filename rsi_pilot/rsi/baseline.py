"""Baseline phase: noise floor on E, then the baseline on E, H and B.

1. Runs the baseline harness on E `--reps` times without the cache. The spread
   (max - min tasks passed) is the noise floor; evolution keeps an edit only if
   it beats the current harness by at least spread + 1 tasks.
2. Runs the baseline on H and B (allowed: the baseline is never tuned).
3. Prints the sanity checks from the plan: E baseline in about 15% to 80%,
   B baseline at least 5%, and seconds per task.

CLI: python -m rsi.baseline [--reps 3] [--workers 1]
"""
from __future__ import annotations

import argparse
import json

from rsi.config import RUNS, ROOT, load_yaml
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
    (RUNS / "noise_floor.json").write_text(json.dumps(nf, indent=1))

    out = {"E": reps[-1]}
    for split in ("H", "B"):
        out[split] = evaluate(ctx, h, split, purpose="baseline")
    (RUNS / "evals").mkdir(parents=True, exist_ok=True)
    for split, res in out.items():
        (RUNS / "evals" / f"baseline_{split}.json").write_text(json.dumps(res, indent=1))

    print(f"Noise floor: E passed across {args.reps} runs = {passed}; spread {nf['spread_tasks']}; "
          f"{len(flips)} tasks flipped")
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
