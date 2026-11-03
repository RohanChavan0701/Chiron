"""Pool results across replicate runs (each a runs dir with results.json).

For each comparison and set, sums improved/regressed task counts across runs and
applies an exact two-sided sign test to the pooled discordant pairs. Caveat: runs
share models and draw from the same Spider dev / BIRD pools, so tasks can repeat
across runs and the runs are not fully independent; read the pooled p as a summary,
not an exact error rate.

CLI: python -m rsi.pool runs_v2 runs_v3_s20261103 ... [--out pooled.md]
"""
from __future__ import annotations

import argparse
import json
from math import comb
from pathlib import Path

from rsi.config import ROOT

COMPARISONS = ["arm_A_vs_baseline", "arm_B_vs_baseline", "arm_B_vs_arm_A"]
SETS = ["E", "H", "B"]


def sign_test(improved: int, regressed: int) -> float:
    n = improved + regressed
    if n == 0:
        return 1.0
    k = min(improved, regressed)
    p = 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, p)


def pool(run_dirs: list[Path]) -> str:
    res = {d.name: json.loads((d / "results.json").read_text()) for d in run_dirs}
    lines = ["Per-run held-out deltas (percentage points; improved/regressed):", "",
             "| Run | " + " | ".join(f"{c.replace('_vs_', ' vs ')} {s}" for c in COMPARISONS for s in ("H", "B")) + " |",
             "|---|" + "---|" * (len(COMPARISONS) * 2)]
    for name, r in res.items():
        cells = []
        for c in COMPARISONS:
            for s in ("H", "B"):
                t = r["tests"][f"{c}/{s}"]
                cells.append(f"{t['delta'] * 100:+.0f} ({t['improved']}/{t['regressed']})")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += ["", "Pooled across runs (exact sign test on summed discordant tasks):", "",
              "| Comparison | Set | Improved | Regressed | Net tasks | p |", "|---|---|---|---|---|---|"]
    for c in COMPARISONS:
        for s in SETS:
            imp = sum(r["tests"][f"{c}/{s}"]["improved"] for r in res.values())
            reg = sum(r["tests"][f"{c}/{s}"]["regressed"] for r in res.values())
            lines.append(f"| {c.replace('_vs_', ' vs ')} | {s} | {imp} | {reg} | {imp - reg:+d} | {sign_test(imp, reg):.3f} |")
    lines += ["", f"Runs: {', '.join(res)}. Runs share models and task pools, so they are not fully "
              "independent; nine pooled tests, uncorrected."]
    return "\n".join(lines)


def wilcoxon_exact(diffs: list[float]) -> float:
    """Two-sided exact Wilcoxon signed-rank p-value. Zeros dropped; ties get average ranks;
    the null distribution is enumerated over all sign assignments (fine for <= 16 seeds)."""
    d = [x for x in diffs if x != 0]
    n = len(d)
    if n == 0:
        return 1.0
    order = sorted(range(n), key=lambda i: abs(d[i]))
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(d[order[j + 1]]) == abs(d[order[i]]):
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    w_plus = sum(r for r, x in zip(ranks, d) if x > 0)
    total = sum(ranks)
    obs = abs(w_plus - total / 2)
    hits = 0
    for mask in range(2 ** n):
        w = sum(ranks[k] for k in range(n) if mask >> k & 1)
        if abs(w - total / 2) >= obs - 1e-9:
            hits += 1
    return hits / 2 ** n


def holm(pvals: dict[str, float]) -> dict[str, float]:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m, out, running = len(items), {}, 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = running
    return out


def seed_ci(xs: list[float], iters: int = 10_000, seed: int = 0) -> tuple[float, float]:
    import random
    rng = random.Random(seed)
    n = len(xs)
    m = sorted(sum(xs[rng.randrange(n)] for _ in range(n)) / n for _ in range(iters))
    return m[int(0.025 * iters)], m[int(0.975 * iters) - 1]


# Run 4 pre-registered analysis (see PREDICTION.md). The seed is the unit of replication.
PRIMARY = ("arm_B_vs_arm_A", "H")
SECONDARY = [("arm_A_vs_baseline", "H"), ("arm_B_vs_baseline", "H"), ("arm_A_vs_arm_C", "E"),
             ("arm_A_vs_arm_C", "H"), ("arm_B_vs_arm_A", "B"), ("gap_A", "E-E2"), ("gap_B", "E-E2"),
             ("gap_C", "E-E2")]


def net(r: dict, comp: str, split: str) -> int:
    t = r["tests"][f"{comp}/{split}"]
    return t["improved"] - t["regressed"]


def gap(r: dict, arm: str) -> float:
    """Selection gap in percentage points: arm's gain on E minus its gain on fresh E2 tasks."""
    a = r["accuracy"]
    return 100 * ((a[f"arm_{arm}/E"] - a["baseline/E"]) - (a[f"arm_{arm}/E2"] - a["baseline/E2"]))


def seed_level(run_dirs: list[Path]) -> str:
    res = {d.name: json.loads((d / "results.json").read_text()) for d in run_dirs}
    names = list(res)
    rows = {}
    for comp, split in [PRIMARY] + SECONDARY:
        if comp.startswith("gap_"):
            xs = [gap(r, comp[-1]) for r in res.values()]
            unit = "pp"
        else:
            xs = [net(r, comp, split) for r in res.values()]
            unit = "tasks"
        rows[(comp, split)] = (xs, unit)
    p_raw = {f"{c}/{s}": wilcoxon_exact(rows[(c, s)][0]) for c, s in SECONDARY}
    p_holm = holm(p_raw)
    lines = [f"Seed-level analysis over {len(names)} seeds ({', '.join(names)}).",
             "Unit = seed. Per seed: net tasks (improved - regressed) for comparisons; for gap_X, the arm's",
             "E gain minus its E2 gain in percentage points. Exact two-sided Wilcoxon signed-rank across seeds;",
             "secondary p-values Holm-corrected.", "",
             "| Endpoint | Set | Per-seed values | Mean | 95% CI (seeds) | Positive/negative seeds | p | p (Holm) |",
             "|---|---|---|---|---|---|---|---|"]
    for (c, s), (xs, unit) in rows.items():
        mean = sum(xs) / len(xs)
        lo, hi = seed_ci(xs)
        pos, neg = sum(x > 0 for x in xs), sum(x < 0 for x in xs)
        p = wilcoxon_exact(xs)
        tag = "**primary** " if (c, s) == PRIMARY else ""
        ph = "-" if (c, s) == PRIMARY else f"{p_holm[f'{c}/{s}']:.3f}"
        lines.append(f"| {tag}{c.replace('_vs_', ' vs ')} | {s} | {', '.join(f'{x:+.0f}' for x in xs)} | "
                     f"{mean:+.1f} {unit} | [{lo:+.1f}, {hi:+.1f}] | {pos}/{neg} | {p:.3f} | {ph} |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--out", default=None)
    ap.add_argument("--seed-level", action="store_true", help="run-4 pre-registered analysis (seed = unit)")
    args = ap.parse_args()
    dirs = [Path(r) if Path(r).is_absolute() else ROOT / r for r in args.runs]
    md = seed_level(dirs) if args.seed_level else pool(dirs)
    print(md)
    if args.out:
        Path(args.out).write_text(md + "\n")


if __name__ == "__main__":
    main()
