"""Verifier audit on the final harnesses' passes.

1. Spider passes (E and H): re-score against Spider's distilled test-suite
   databases (Zhong et al. 2020). A pass that fails there returned the right rows
   for the wrong reason: a false positive of single-database execution matching.
   Needs --testsuite-dir pointing at the test-suite `database/` folder.
2. All tasks: count where AgentWatch's checker and Spider's official comparison
   disagree. All passes: count passes whose gold result is empty (any query returning
   nothing passes) and passes whose gold uses ORDER BY or LIMIT.
3. BIRD passes: writes up to 20 (seeded sample) to a CSV for hand labeling,
   since BIRD has no test suite.

CLI: python -m rsi.audit [--testsuite-dir path/to/test-suite/database]
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
from pathlib import Path

from rsi.config import RUNS, ROOT, load_yaml
from rsi.runner import arms_of, evaluate, load_context
from rsi.sqlexec import compare_with, execute, strip_distinct


def testsuite_pass(ts_dir: Path, db_id: str, gold: str, pred: str, keep_distinct: bool, timeout: float,
                   verifier: str = "spider_official") -> bool | None:
    """True/False from the test-suite databases, or None if nothing could be checked
    (no test databases, or the gold query failed on every one of them).

    Uses the same checker (`verifier`) that scored the run, so a disagreement between
    checkers is not counted as a test-suite false positive."""
    dbs = sorted((ts_dir / db_id).glob("*.sqlite"))
    if not keep_distinct:
        gold, pred = strip_distinct(gold), strip_distinct(pred)
    checked = 0
    for db in dbs:
        g, p = execute(str(db), gold, timeout), execute(str(db), pred, timeout)
        if not g.ok:
            continue  # gold fails on this test db; skip it rather than penalize the prediction
        checked += 1
        if not p.ok or not compare_with(verifier, g.rows, p.rows, gold):
            return False
    return True if checked else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--testsuite-dir", default=None)
    ap.add_argument("--n-label", type=int, default=20)
    args = ap.parse_args()
    ctx = load_context()
    ev = ctx.cfg["eval"]
    harnesses = {"baseline": load_yaml(ROOT / "harness.yaml")}
    for a in arms_of(ctx.cfg):
        p = RUNS / f"arm_{a}" / "final.yaml"
        if p.exists():
            harnesses[f"arm_{a}"] = load_yaml(p)
    tasks = {t.task_id: t for ts in ctx.tasks.values() for t in ts}
    ts_dir = Path(args.testsuite_dir) if args.testsuite_dir else None

    report, label_rows = {}, []
    rng = random.Random(ctx.cfg["seed"])
    for name, h in harnesses.items():
        for split in ctx.tasks:
            res = evaluate(ctx, h, split, purpose="audit")
            passes = [r for r in res["records"] if r["pass"]]
            rep = {"passes": len(passes),
                   "gold_empty_passes": sum(r["gold_empty"] for r in passes),
                   "verifier_disagreements": sum(r["pass"] != r.get("pass_other_verifier", r["pass"]) for r in res["records"]),
                   "order_by_or_limit_passes": sum(bool(re.search(r"\b(order\s+by|limit)\b", tasks[r["task_id"]].gold_sql, re.I)) for r in passes)}
            if split in ("E", "E2", "H") and ts_dir:
                verdicts = [testsuite_pass(ts_dir, tasks[r["task_id"]].db_id, tasks[r["task_id"]].gold_sql,
                                           r["pred_sql"], ev["keep_distinct"], ev["exec_timeout_s"], ev["verifier"])
                            for r in passes]
                checked = [v for v in verdicts if v is not None]
                rep["testsuite_checked"] = len(checked)
                rep["testsuite_false_positives"] = sum(1 for v in checked if v is False)
                rep["testsuite_false_positive_ids"] = [r["task_id"] for r, v in zip(passes, verdicts) if v is False]
            if split == "B" and name != "baseline":
                for r in passes:
                    t = tasks[r["task_id"]]
                    label_rows.append({"harness": name, "task_id": t.task_id, "difficulty": t.difficulty,
                                       "question": t.question, "evidence": t.evidence, "gold_sql": t.gold_sql,
                                       "pred_sql": r["pred_sql"], "label (correct|wrong_reason)": "", "notes": ""})
            report[f"{name}/{split}"] = rep

    if label_rows:
        label_rows = rng.sample(label_rows, min(args.n_label, len(label_rows)))
        out = RUNS / "audit_bird_labels.csv"
        with open(out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(label_rows[0]))
            w.writeheader(); w.writerows(label_rows)
        report["bird_label_csv"] = str(out)
    if not ts_dir:
        report["note"] = "No --testsuite-dir given; Spider test-suite re-scoring skipped."
    (RUNS / "audit.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
