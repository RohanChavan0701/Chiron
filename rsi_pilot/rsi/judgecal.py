"""Run 6, stage 0b: judge calibration. How well does each reference-free judge tell right from wrong?

  python -m rsi.judgecal [--frozen frozen_v6_stage0.yaml] [--workers 6]

Re-grades the baseline transcripts that `rsi.stage0 headroom` stored. No student calls.
Each variant is (judge model, prompt style). Reported per variant: share of right and of
wrong answers approved, AUROC of the 0-10 score against truth, unparsed replies, seconds.
A judge with AUROC near 0.5 carries no information, and selecting on it is selecting on noise.

Stage 0 is allowed to look. The tasks used here must not be reused in a registered stage.
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor

from rsi import proxies, stage0
from rsi.config import load_yaml, resolve, stable_hash

VARIANTS = [("llama3.1:8b", "verdict"), ("llama3.1:8b", "recompute"),
            ("gemma2:27b", "verdict"), ("gemma2:27b", "recompute")]


def auroc(scores_right: list[float], scores_wrong: list[float]) -> float | None:
    if not scores_right or not scores_wrong:
        return None
    wins = sum((r > w) + 0.5 * (r == w) for r in scores_right for w in scores_wrong)
    return wins / (len(scores_right) * len(scores_wrong))


def summarize(recs: list[dict], verdicts: list[dict]) -> dict:
    ok = [bool(v["correct"]) for v in verdicts]
    score = [v["score"] if v["score"] is not None else (10.0 if v["correct"] else 0.0) for v in verdicts]
    right = [i for i, r in enumerate(recs) if r["pass"]]
    wrong = [i for i, r in enumerate(recs) if not r["pass"]]

    def share(idx):
        return sum(ok[i] for i in idx) / len(idx) if idx else None

    return {"n": len(recs), "truth": len(right) / len(recs), "approved": sum(ok) / len(recs),
            "approves_right": share(right), "approves_wrong": share(wrong),
            "agrees_with_truth": sum(ok[i] == recs[i]["pass"] for i in range(len(recs))) / len(recs),
            "auroc_score": auroc([score[i] for i in right], [score[i] for i in wrong]),
            "unparsed": sum(v["correct"] is None for v in verdicts) / len(recs)}


def grade_variant(cfg: dict, tasks, recs: list[dict], model: str, style: str, judge, workers: int) -> dict:
    key = stable_hash({"model": model, "style": style, "ids": [r["task_id"] for r in recs],
                       "answers": [r["answer"] for r in recs], "judge": {**cfg["judge"], "model": model}})
    path = resolve(cfg["out_dir"]) / f"jc_{key}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    fmt = stage0.baseline()["table_format"]
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        verdicts = list(ex.map(lambda tr: proxies.p2_judge_free(tr[0], tr[1], judge, fmt, style), zip(tasks, recs)))
    out = {"model": model, "style": style, **summarize(recs, verdicts),
           "seconds": round(time.monotonic() - t0, 1), "verdicts": verdicts}
    path.write_text(json.dumps(out), encoding="utf-8")
    return out


def run(cfg: dict, tasks, make_judge, workers: int, variants=VARIANTS) -> list[dict]:
    """`make_judge(judge_cfg)` builds a judge callable. Baseline episodes must already be cached."""
    reps = range(cfg["baseline_repeats"])
    recs = [r for rep in reps for r in stage0.episodes(cfg, stage0.baseline(), tasks, None, rep, workers)]
    all_tasks = [t for _ in reps for t in tasks]
    rows = []
    for model, style in variants:
        judge = make_judge({**cfg["judge"], "model": model, "num_predict": proxies.P2_STYLES[style][1]})
        row = grade_variant(cfg, all_tasks, recs, model, style, judge, workers)
        rows.append({k: v for k, v in row.items() if k != "verdicts"})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--frozen", default="frozen_v6_stage0.yaml")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--only", help="grade only variants of this judge model; others are read from cache")
    args = ap.parse_args()
    cfg = load_yaml(resolve(args.frozen))
    from rsi.llm import make_llm
    variants = [v for v in VARIANTS if not args.only or v[0] == args.only]
    rows = run(cfg, stage0.sample_tasks(cfg), make_llm, args.workers, variants)
    name = "judgecal.json" if not args.only else f"judgecal_{args.only.replace(':', '_')}.json"
    (resolve(cfg["out_dir"]) / name).write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
