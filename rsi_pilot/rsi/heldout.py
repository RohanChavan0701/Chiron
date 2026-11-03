"""Held-out evaluation after BOTH arms finish.

Runs baseline, Arm A final and Arm B final on E, H and B; reports accuracy,
paired 95% bootstrap CIs, exact McNemar tests (each arm vs baseline, and A vs B
directly), and transfer ratios (secondary; None when E gain < 2 tasks).

CLI: python -m rsi.heldout
"""
from __future__ import annotations

import argparse
import json

from rsi.config import RUNS, ROOT, load_yaml
from rsi.runner import arms_of, evaluate, load_context
from rsi.stats import compare, transfer_ratio


def fmt_p(p: float) -> str:
    return f"{p:.3f}" if p >= 0.001 else "<0.001"


def pairs_for(arms: tuple[str, ...]) -> list[tuple[str, str]]:
    pairs = [(f"arm_{a}", "baseline") for a in arms]
    if "A" in arms and "B" in arms:
        pairs.append(("arm_B", "arm_A"))
    if "C" in arms:
        pairs += [(f"arm_{a}", "arm_C") for a in ("A", "B") if a in arms]
    return pairs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args()
    ctx = load_context(workers=args.workers)
    arms = arms_of(ctx.cfg)
    finals = {a: RUNS / f"arm_{a}" / "final.yaml" for a in arms}
    missing = [str(p) for p in finals.values() if not p.exists()]
    if missing:
        raise SystemExit(f"Evolution not finished; missing {missing}")
    harnesses = {"baseline": load_yaml(ROOT / "harness.yaml"), **{f"arm_{a}": load_yaml(p) for a, p in finals.items()}}
    splits = [s for s in ("E", "E2", "H", "B") if s in ctx.tasks]

    vec, acc, tok = {}, {}, {}
    for name, h in harnesses.items():
        for split in splits:
            r = evaluate(ctx, h, split, purpose="heldout_final")
            vec[(name, split)] = r["vector"]
            acc[(name, split)] = r["accuracy"]
            tok[(name, split)] = (r["prompt_tokens"] + r["completion_tokens"]) / r["n"]

    n = ctx.splits["n_per_split"]
    results = {"n_per_split": n, "splits": splits, "arms": list(arms),
               "accuracy": {f"{k[0]}/{k[1]}": v for k, v in acc.items()},
               "passed": {f"{k[0]}/{k[1]}": sum(v.values()) for k, v in vec.items()},
               "tokens_per_task": {f"{k[0]}/{k[1]}": v for k, v in tok.items()}, "tests": {}, "transfer": {}}
    pairs = pairs_for(arms)
    for new, base in pairs:
        for split in splits:
            results["tests"][f"{new}_vs_{base}/{split}"] = compare(vec[(base, split)], vec[(new, split)], seed=ctx.cfg["seed"])
    for a in [f"arm_{x}" for x in arms]:
        gE = acc[(a, "E")] - acc[("baseline", "E")]
        gE_tasks = sum(vec[(a, "E")].values()) - sum(vec[("baseline", "E")].values())
        results["transfer"][a] = {s: transfer_ratio(acc[(a, s)] - acc[("baseline", s)], gE, gE_tasks)
                                  for s in splits if s != "E"}
    (RUNS / "results.json").write_text(json.dumps(results, indent=1))

    hdr = " | ".join(splits)
    lines = [f"| Harness | {hdr} | tokens/task (H) |", "|---|" + "---|" * (len(splits) + 1)]
    for name in harnesses:
        lines.append(f"| {name} | " + " | ".join(f"{acc[(name, s)]:.1%}" for s in splits) + f" | {tok[(name, 'H')]:.0f} |")
    lines += ["", "| Comparison | Set | Delta | 95% CI | Improved/Regressed | McNemar p |", "|---|---|---|---|---|---|"]
    for key, c in results["tests"].items():
        cmp_name, split = key.split("/")
        lines.append(f"| {cmp_name.replace('_vs_', ' vs ')} | {split} | {c['delta']:+.1%} | "
                     f"[{c['ci95'][0]:+.1%}, {c['ci95'][1]:+.1%}] | {c['improved']}/{c['regressed']} | {fmt_p(c['p_mcnemar'])} |")
    lines += ["", "Transfer ratio (gain on the set / E gain; secondary, None when E gain < 2 tasks): "
              + "; ".join(f"{a}: " + ", ".join(f"{s}={v[s]}" for s in v) for a, v in results["transfer"].items()),
              "", f"Set sizes: {n}. Per-run tests are uncorrected; the pre-registered analysis is across "
              "seeds (rsi.pool)."]
    md = "\n".join(lines)
    (RUNS / "results.md").write_text(md + "\n")
    print(md)


if __name__ == "__main__":
    main()
