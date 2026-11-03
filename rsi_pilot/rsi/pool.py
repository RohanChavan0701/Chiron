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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    dirs = [Path(r) if Path(r).is_absolute() else ROOT / r for r in args.runs]
    md = pool(dirs)
    print(md)
    if args.out:
        Path(args.out).write_text(md + "\n")


if __name__ == "__main__":
    main()
