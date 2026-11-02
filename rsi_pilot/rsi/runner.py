"""Evaluate a harness on a split. Results are cached per (harness, student config, task).

Held-out guard: H and B may be run with the baseline harness at any time (the
baseline is never tuned), but any other harness on H or B requires both arms'
final harnesses to exist, i.e. evolution is finished. Every H/B evaluation is
appended to runs/heldout_access.jsonl so leakage is auditable.

CLI: python -m rsi.runner --split E --harness harness.yaml [--no-cache] [--tag baseline_rep1]
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from rsi.config import RUNS, ROOT, append_jsonl, frozen, load_yaml, resolve, stable_hash
from rsi.data import Task, load_bird, load_spider, tasks_from_split
from rsi.fewshot import FewShotPool
from rsi.harness import harness_id, run_task, validate
from rsi.student import Completion, make_student

ARMS = ("A", "B")


@dataclass
class Context:
    cfg: dict
    splits: dict
    tasks: dict[str, list[Task]]           # split name -> tasks
    pool: FewShotPool
    student: Callable[[list[dict]], Completion]
    runs_dir: Path = RUNS
    workers: int = 1

    @property
    def student_key(self) -> str:
        return stable_hash(self.cfg["student"])


def pool_without(train: list[Task], forbidden: set[str]) -> list[Task]:
    """Spider train examples whose database is not used by any evaluation source."""
    return [t for t in train if t.db_id not in forbidden]


def load_context(splits_path: str | Path = ROOT / "splits.json", workers: int = 1) -> Context:
    cfg = frozen()
    sp = json.loads(Path(splits_path).read_text())
    dev = load_spider(resolve(cfg["data"]["spider_dir"]), "dev")
    train = load_spider(resolve(cfg["data"]["spider_dir"]), "train")
    bird = load_bird(resolve(cfg["data"]["bird_dir"]), cfg["data"].get("bird_json"))
    tasks = {"E": tasks_from_split(sp["E"], dev), "H": tasks_from_split(sp["H"], dev),
             "B": tasks_from_split(sp["B"], bird)}
    # Exclude every database from Spider dev and BIRD Mini-Dev, not only those in the
    # sampled splits. Spider train and BIRD Mini-Dev both contain `formula_1`, so its
    # 80 train examples are dropped from the few-shot pool.
    forbidden = {t.db_id for t in dev} | {t.db_id for t in bird}
    pool = FewShotPool(pool_without(train, forbidden), forbidden, cfg["seed"])
    return Context(cfg, sp, tasks, pool, make_student(cfg["student"]), workers=workers)


def _guard_heldout(ctx: Context, split: str, h: dict, purpose: str) -> None:
    if split not in ("H", "B"):
        return
    baseline = validate(load_yaml(ROOT / "harness.yaml"))
    is_baseline = harness_id(h) == harness_id(baseline)
    finals = [ctx.runs_dir / f"arm_{a}" / "final.yaml" for a in ARMS]
    if not is_baseline and not all(p.exists() for p in finals):
        raise PermissionError(
            f"Refusing to run a non-baseline harness on held-out split {split} before both arms "
            f"have final.yaml. This would leak held-out information into evolution.")
    append_jsonl(ctx.runs_dir / "heldout_access.jsonl",
                 {"time": time.time(), "split": split, "harness_id": harness_id(h),
                  "is_baseline": is_baseline, "purpose": purpose})


def evaluate(ctx: Context, h: dict, split: str, use_cache: bool = True, purpose: str = "") -> dict:
    validate(h)
    _guard_heldout(ctx, split, h, purpose)
    hid = harness_id(h)
    cache_dir = ctx.runs_dir / "cache" / ctx.student_key / hid
    cache_dir.mkdir(parents=True, exist_ok=True)
    tasks = ctx.tasks[split]

    def one(t: Task) -> dict:
        f = cache_dir / f"{t.task_id}.json"
        if use_cache and f.exists():
            return json.loads(f.read_text())
        rec = run_task(h, t, ctx.student, ctx.pool, ctx.cfg["eval"])
        f.write_text(json.dumps(rec))
        return rec

    if ctx.workers > 1:
        with ThreadPoolExecutor(ctx.workers) as ex:
            recs = list(ex.map(one, tasks))
    else:
        recs = [one(t) for t in tasks]
    return summarize(recs, split, hid)


def summarize(recs: list[dict], split: str, hid: str) -> dict:
    n = len(recs)
    passed = sum(r["pass"] for r in recs)
    return {
        "split": split,
        "harness_id": hid,
        "n": n,
        "passed": passed,
        "accuracy": passed / n if n else 0.0,
        "vector": {r["task_id"]: bool(r["pass"]) for r in recs},
        "prompt_tokens": sum(r["prompt_tokens"] for r in recs),
        "completion_tokens": sum(r["completion_tokens"] for r in recs),
        "student_seconds": round(sum(r["student_seconds"] for r in recs), 2),
        "records": recs,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", required=True, choices=["E", "H", "B"])
    ap.add_argument("--harness", default=str(ROOT / "harness.yaml"))
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--tag", default="")
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args()
    ctx = load_context(workers=args.workers)
    h = load_yaml(args.harness)
    res = evaluate(ctx, h, args.split, use_cache=not args.no_cache, purpose=args.tag or "cli")
    out = RUNS / "evals" / f"{args.tag or res['harness_id']}_{args.split}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1))
    print(f"{args.split}: {res['passed']}/{res['n']} = {res['accuracy']:.1%} | "
          f"{res['student_seconds'] / max(res['n'], 1):.2f}s/task | tokens {res['prompt_tokens']}+{res['completion_tokens']} -> {out}")


if __name__ == "__main__":
    main()
