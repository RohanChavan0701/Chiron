"""Fixed-harness ablation for run 5: the baseline harness with exactly one field changed.

Each variant in ablations_v5.yaml (name -> {field: value}) is the baseline harness
(config.BASELINE) with ONE field overridden. For one run-5 seed, the baseline and every
variant are scored fresh (no cache) on H and B in the same session, against the same
student server. Run it with run 5's environment for that seed (scripts/run_ablation.sh):
RSI_HARNESS_KIND=agent RSI_FROZEN=frozen_v5_s<SEED>.yaml RSI_SPLITS=splits_v5_s<SEED>.json
RSI_RUNS=runs_v5/s<SEED>. The held-out guard in rsi/runner.py is used unmodified: it lets a
non-baseline harness on H/B only because every arm's final.yaml is already in that runs
dir, and it appends each access to heldout_access.jsonl with purpose ablation_<name>.

The student seed is fixed and H/B are the same tasks for every seed, so for a fixed
harness the six "seeds" are replicate evaluations: their spread is server nondeterminism
(8 parallel slots), not a new search or a new test set.

Outputs in <RSI_RUNS>/ablation/: <name>_<split>.json (the full evaluate() result, records
included, compact JSON) and ablation.json (summary, vectors, harnesses, order, settings).

CLI: python -m rsi.ablate [--variants ablations_v5.yaml] [--splits H B] [--workers N] [--force]
     python -m rsi.ablate check            # splits consistency check only
     python -m rsi.ablate report runs_v5/s* [--out runs_v5/ablation_seed_level.md]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from dataclasses import fields
from pathlib import Path
from statistics import fmean, stdev

from rsi.config import BASELINE, ROOT, RUNS, SPLITS, load_yaml
from rsi.harness import HarnessError, diff_fields, harness_id, validate
from rsi.pool import wilcoxon_exact
from rsi.runner import Context, evaluate, load_context

VARIANTS = ROOT / "ablations_v5.yaml"
NAME = re.compile(r"^[a-z][a-z0-9_]*$")
ENV_VARS = ("RSI_HARNESS_KIND", "RSI_FROZEN", "RSI_SPLITS", "RSI_RUNS", "RSI_OLLAMA_SERVERS")


class SplitsMismatch(RuntimeError):
    pass


def load_variants(path: str | Path, baseline: dict) -> dict[str, dict]:
    """name -> full harness. Each variant must change exactly one baseline field to a valid value."""
    raw = load_yaml(path) or {}
    if not isinstance(raw, dict) or not raw:
        raise HarnessError(f"{path}: expected a non-empty mapping name -> {{field: value}}")
    out, seen = {}, {harness_id(baseline): "baseline"}
    for name, ov in raw.items():
        if not isinstance(name, str) or not NAME.match(name) or name == "baseline":
            raise HarnessError(f"variant name {name!r}: use lowercase letters, digits, _ (not 'baseline')")
        if not isinstance(ov, dict) or len(ov) != 1:
            raise HarnessError(f"variant {name}: must override exactly one field, got {ov!r}")
        h = validate({**baseline, **ov})
        changed = diff_fields(baseline, h)
        if changed != list(ov):
            raise HarnessError(f"variant {name}: changes {changed} from the baseline, must change exactly {list(ov)}")
        hid = harness_id(h)
        if hid in seen:
            raise HarnessError(f"variant {name} is the same harness as {seen[hid]}")
        seen[hid] = name
        out[name] = h
    return out


def eval_order(seed: int, names: list[str]) -> list[str]:
    """Even seed: baseline first; odd seed: variants first. Warm-up or drift then does not
    always fall on the same harness."""
    return ["baseline", *names] if seed % 2 == 0 else [*names, "baseline"]


def check_splits(sp: dict, cfg: dict, runs_dir: Path) -> None:
    """The regenerated splits must be run 5's: H/B sizes from the frozen file, every H task the
    run-5 test-suite audit flagged is in H, and (when the uncommitted run-5 baseline evals are
    present) the task ids equal those that run 5 scored."""
    s, errs = cfg["splits"], []
    for split, key in (("H", "h_max"), ("B", "b_max")):
        if s.get(key) and len(sp.get(split, [])) != s[key]:
            errs.append(f"{split} has {len(sp.get(split, []))} tasks, run 5 had {s[key]}")
    audit = runs_dir / "audit.json"
    if not audit.exists():
        errs.append(f"{audit} not found; cannot check H against run 5")
    else:
        a = json.loads(audit.read_text())
        flagged = {i for k, v in a.items() if k.endswith("/H") for i in v.get("testsuite_false_positive_ids", [])}
        missing = sorted(flagged - set(sp.get("H", [])))
        if missing:
            errs.append(f"{len(missing)} task ids from {audit.name} */H are not in the regenerated H, "
                        f"e.g. {missing[:5]}")
    for split in ("H", "B"):
        ev = runs_dir / "evals" / f"baseline_{split}.json"
        if ev.exists() and set(json.loads(ev.read_text())["vector"]) != set(sp.get(split, [])):
            errs.append(f"{split} task ids differ from {ev}")
    if errs:
        raise SplitsMismatch("Regenerated splits do not match run 5 (wrong data version or frozen file?):\n  "
                             + "\n  ".join(errs) + "\nNothing was evaluated.")


class _AblationContext(Context):
    """Same context, separate cache directory: the fresh ablation records must not overwrite
    run 5's cached records (seed 20261214's arm B final IS the schema_only harness)."""

    @property
    def cache_key(self) -> str:
        return "ablation_" + Context.cache_key.fget(self)


def run_seed(ctx: Context, variants: dict[str, dict], splits: list[str], baseline: dict,
             out_dir: Path, force: bool = False) -> dict:
    out_dir = Path(out_dir)
    if (out_dir / "ablation.json").exists() and not force:
        raise FileExistsError(f"{out_dir / 'ablation.json'} exists; pass --force to add another replicate "
                              "session (it overwrites the files and logs new held-out accesses)")
    ctx = _AblationContext(**{f.name: getattr(ctx, f.name) for f in fields(Context)})
    seed = ctx.cfg["seed"]
    harnesses = {"baseline": baseline, **variants}
    order = eval_order(seed, list(variants))
    out_dir.mkdir(parents=True, exist_ok=True)
    results, done = {}, []
    for name in order:
        for split in splits:
            t0 = time.time()
            r = evaluate(ctx, harnesses[name], split, use_cache=False, purpose=f"ablation_{name}")
            wall = round(time.time() - t0, 1)
            (out_dir / f"{name}_{split}.json").write_text(json.dumps(r, separators=(",", ":")))
            results.setdefault(name, {})[split] = {
                "passed": r["passed"], "n": r["n"], "accuracy": r["accuracy"],
                "tokens_per_task": (r["prompt_tokens"] + r["completion_tokens"]) / max(r["n"], 1),
                "prompt_tokens": r["prompt_tokens"], "completion_tokens": r["completion_tokens"],
                "student_seconds": r["student_seconds"], "wall_seconds": wall, "vector": r["vector"]}
            done.append(f"{name}/{split}")
            print(f"{name} {split}: {r['passed']}/{r['n']} = {r['accuracy']:.1%} | {wall:.0f}s wall", flush=True)
    summary = {
        "seed": seed, "splits": splits, "order": done,
        "note": "seeds replicate the evaluation of fixed harnesses; they are not separate searches",
        "harnesses": harnesses, "harness_ids": {k: harness_id(h) for k, h in harnesses.items()},
        "changed_field": {k: diff_fields(baseline, h)[0] for k, h in variants.items()},
        "results": results, "student": ctx.cfg["student"], "eval": ctx.cfg["eval"], "workers": ctx.workers,
        "env": {k: os.environ.get(k, "") for k in ENV_VARS}}
    (out_dir / "ablation.json").write_text(json.dumps(summary, indent=1, sort_keys=True))
    return summary


# ---------------- report ----------------

def _sd(xs: list[float]) -> float:
    return stdev(xs) if len(xs) > 1 else 0.0


def _arm_reference(summary_csv: Path) -> list[str]:
    if not summary_csv.exists():
        return [f"({summary_csv} not found; no run-5 reference)"]
    rows = list(csv.DictReader(summary_csv.open()))
    lines = ["**Reference from run 5, different session, not a paired comparison.** Run 5 final harnesses",
             "and baseline, mean over its 6 seeds (`runs_v5/summary.csv`):", "",
             "| Run 5 harness | H mean | H gain vs run-5 baseline | B mean | B gain vs run-5 baseline |",
             "|---|---|---|---|---|"]
    mean = {}
    for hname in ("baseline", "arm_A", "arm_B", "arm_C"):
        rs = [r for r in rows if r["harness"] == hname]
        if rs:
            mean[hname] = {s: fmean(100 * int(r[s]) / int(r[f"n_{s}"]) for r in rs) for s in ("H", "B")}
    for hname, m in mean.items():
        g = {s: m[s] - mean["baseline"][s] for s in m}
        lines.append(f"| {hname} | {m['H']:.1f}% | {g['H']:+.1f} pp | {m['B']:.1f}% | {g['B']:+.1f} pp |")
    arms = [k for k in mean if k != "baseline"]
    if arms and "baseline" in mean:
        for s in ("H", "B"):
            lines.append(f"\nArms' mean {s} gain over the run-5 baseline: "
                         f"{fmean(mean[a][s] for a in arms) - mean['baseline'][s]:+.1f} pp.")
    return lines


def report(run_dirs: list[Path], summary_csv: Path) -> str:
    abl = sorted((json.loads((d / "ablation" / "ablation.json").read_text()) for d in run_dirs
                  if (d / "ablation" / "ablation.json").exists()), key=lambda a: a["seed"])
    if not abl:
        raise SystemExit("no ablation/ablation.json in the given runs dirs")
    names = ["baseline"] + sorted({n for a in abl for n in a["results"] if n != "baseline"})
    splits = [s for s in ("H", "B", "E2") if any(s in a["splits"] for a in abl)]
    lines = [f"# Fixed-harness ablation, seed level ({len(abl)} replicate sessions)", "",
             "Each session scores the run-5 baseline harness and each single-field variant fresh (no cache),",
             "in the same session on the same server. H and B are the same tasks for every seed and the",
             "student seed is fixed, so the seeds replicate the evaluation (server nondeterminism), not a search.",
             "", "Variants: " + "; ".join(f"`{n}` = baseline with `{f}: {json.dumps(abl[0]['harnesses'][n][f])}`"
                                         for n, f in sorted(abl[0]["changed_field"].items())), "",
             "## Per seed", "",
             "| Seed | Harness | Order | " + " | ".join(f"{s} passed | {s} tokens/task" for s in splits) + " |",
             "|---|---|---|" + "---|---|" * len(splits)]
    for a in abl:
        for n in names:
            if n not in a["results"]:
                continue
            pos = min(i for i, k in enumerate(a["order"]) if k.startswith(n + "/")) + 1
            cells = []
            for s in splits:
                r = a["results"][n].get(s)
                cells += [f"{r['passed']}/{r['n']}", f"{r['tokens_per_task']:.0f}"] if r else ["-", "-"]
            lines.append(f"| {a['seed']} | {n} | {pos} | " + " | ".join(cells) + " |")
    lines += ["", "## Per harness, across seeds (percent of the set; SD is the sample SD across seeds)", "",
              "| Harness | Set | Seeds | Mean | SD | Tokens/task mean |", "|---|---|---|---|---|---|"]
    for n in names:
        for s in splits:
            rs = [a["results"][n][s] for a in abl if s in a["results"].get(n, {})]
            if rs:
                acc = [100 * r["accuracy"] for r in rs]
                lines.append(f"| {n} | {s} | {len(rs)} | {fmean(acc):.1f}% | {_sd(acc):.1f} | "
                             f"{fmean(r['tokens_per_task'] for r in rs):.0f} |")
    lines += ["", "## Paired: variant minus same-session baseline", "",
              "Net tasks = variant passed - baseline passed (= improved - regressed). Exact two-sided Wilcoxon",
              "signed-rank across seeds (`rsi.pool.wilcoxon_exact`); with 6 seeds the smallest possible p is 0.031.", "",
              "| Variant | Set | Per-seed net tasks | Per-seed pp | Mean pp | SD pp | Improved/regressed (summed) | "
              "Positive/negative seeds | Tokens/task ratio (mean) | Wilcoxon p |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for n in names[1:]:
        for s in splits:
            pairs = [(a["results"]["baseline"][s], a["results"][n][s]) for a in abl
                     if s in a["results"].get(n, {}) and s in a["results"].get("baseline", {})]
            if not pairs:
                continue
            net = [v["passed"] - b["passed"] for b, v in pairs]
            pp = [100 * (v["accuracy"] - b["accuracy"]) for b, v in pairs]
            imp = sum(v["vector"][k] and not b["vector"][k] for b, v in pairs for k in b["vector"])
            reg = sum(b["vector"][k] and not v["vector"][k] for b, v in pairs for k in b["vector"])
            ratio = fmean(v["tokens_per_task"] / b["tokens_per_task"] for b, v in pairs if b["tokens_per_task"])
            lines.append(f"| {n} | {s} | {', '.join(f'{x:+d}' for x in net)} | {', '.join(f'{x:+.1f}' for x in pp)} | "
                         f"{fmean(pp):+.1f} | {_sd(pp):.1f} | {imp}/{reg} | {sum(x > 0 for x in net)}/"
                         f"{sum(x < 0 for x in net)} | {ratio:.2f} | {wilcoxon_exact(net):.3f} |")
    lines += ["", "## Reference (unpaired)", ""] + _arm_reference(summary_csv)
    lines += ["", "Variant means above against these arm means compare different sessions; if the server, GPU",
              "or Ollama version differs from run 5, only the paired table is a valid comparison."]
    return "\n".join(lines)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        ap = argparse.ArgumentParser(prog="rsi.ablate report")
        ap.add_argument("runs", nargs="+")
        ap.add_argument("--out", default=None)
        ap.add_argument("--summary", default=None, help="run-5 summary.csv (default: next to the runs dirs)")
        args = ap.parse_args(sys.argv[2:])
        dirs = [Path(r) if Path(r).is_absolute() else ROOT / r for r in args.runs]
        parent = dirs[0].parent
        md = report(dirs, Path(args.summary) if args.summary else parent / "summary.csv")
        out = Path(args.out) if args.out else parent / "ablation_seed_level.md"
        out.write_text(md + "\n")
        print(md)
        return
    check_only = len(sys.argv) > 1 and sys.argv[1] == "check"
    ap = argparse.ArgumentParser(prog="rsi.ablate")
    ap.add_argument("--variants", default=str(VARIANTS))
    ap.add_argument("--splits", nargs="+", default=["H", "B"], choices=["H", "B"])
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--force", action="store_true", help="run again although ablation.json exists")
    args = ap.parse_args(sys.argv[2:] if check_only else sys.argv[1:])
    from rsi.config import frozen
    try:
        check_splits(json.loads(SPLITS.read_text()), frozen(), RUNS)
    except SplitsMismatch as e:
        raise SystemExit(str(e))
    if check_only:
        print(f"splits consistent with run 5: {SPLITS.name} vs {RUNS}")
        return
    baseline = validate(load_yaml(BASELINE))
    variants = load_variants(args.variants, baseline)
    ctx = load_context(workers=args.workers)
    run_seed(ctx, variants, args.splits, baseline, RUNS / "ablation", force=args.force)


if __name__ == "__main__":
    main()
