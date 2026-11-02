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
from rsi.runner import ARMS, evaluate, load_context
from rsi.stats import compare, transfer_ratio


def fmt_p(p: float) -> str:
    return f"{p:.3f}" if p >= 0.001 else "<0.001"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args()
    ctx = load_context(workers=args.workers)
    finals = {a: RUNS / f"arm_{a}" / "final.yaml" for a in ARMS}
    missing = [str(p) for p in finals.values() if not p.exists()]
    if missing:
        raise SystemExit(f"Evolution not finished; missing {missing}")
    harnesses = {"baseline": load_yaml(ROOT / "harness.yaml"), **{f"arm_{a}": load_yaml(p) for a, p in finals.items()}}

    vec, acc, tok = {}, {}, {}
    for name, h in harnesses.items():
        for split in ("E", "H", "B"):
            r = evaluate(ctx, h, split, purpose="heldout_final")
            vec[(name, split)] = r["vector"]
            acc[(name, split)] = r["accuracy"]
            tok[(name, split)] = (r["prompt_tokens"] + r["completion_tokens"]) / r["n"]

    n = ctx.splits["n_per_split"]
    results = {"n_per_split": n, "accuracy": {f"{k[0]}/{k[1]}": v for k, v in acc.items()},
               "tokens_per_task": {f"{k[0]}/{k[1]}": v for k, v in tok.items()}, "tests": {}, "transfer": {}}
    pairs = [("arm_A", "baseline"), ("arm_B", "baseline"), ("arm_B", "arm_A")]
    for new, base in pairs:
        for split in ("E", "H", "B"):
            results["tests"][f"{new}_vs_{base}/{split}"] = compare(vec[(base, split)], vec[(new, split)], seed=ctx.cfg["seed"])
    for a in ("arm_A", "arm_B"):
        gE = acc[(a, "E")] - acc[("baseline", "E")]
        results["transfer"][a] = {s: transfer_ratio(acc[(a, s)] - acc[("baseline", s)], gE, 2 / n) for s in ("H", "B")}
    (RUNS / "results.json").write_text(json.dumps(results, indent=1))

    lines = ["| Harness | E | H | B | tokens/task (H) |", "|---|---|---|---|---|"]
    for name in harnesses:
        lines.append(f"| {name} | {acc[(name,'E')]:.0%} | {acc[(name,'H')]:.0%} | {acc[(name,'B')]:.0%} | {tok[(name,'H')]:.0f} |")
    lines += ["", "| Comparison | Set | Delta | 95% CI | Improved/Regressed | McNemar p |", "|---|---|---|---|---|---|"]
    for key, c in results["tests"].items():
        cmp_name, split = key.split("/")
        lines.append(f"| {cmp_name.replace('_vs_', ' vs ')} | {split} | {c['delta']:+.0%} | "
                     f"[{c['ci95'][0]:+.0%}, {c['ci95'][1]:+.0%}] | {c['improved']}/{c['regressed']} | {fmt_p(c['p_mcnemar'])} |")
    lines += ["", "Transfer ratio (held-out gain / E gain; secondary, None when E gain < 2 tasks): "
              + "; ".join(f"{a}: H={v['H']}, B={v['B']}" for a, v in results["transfer"].items()),
              "", f"Exact McNemar with n={n}: 6/0 is the smallest all-one-way split with p < 0.05. "
              "Nine tests are reported without correction; read single p-values as weak evidence."]
    md = "\n".join(lines)
    (RUNS / "results.md").write_text(md + "\n")
    print(md)


if __name__ == "__main__":
    main()
