#!/usr/bin/env python3
"""Judge test–retest reliability on FinancePro-Bench (G0.2 LIVE).

1) Generate one qwen/qwen3-8b answer per stratified question (cache JSONL).
2) Grade each answer twice in fresh contexts.
3) Report Pearson r + MAD on normalized scores.

Gate: MAD ≤ 5 → single pass; 5–8 → JUDGE_PASSES=2; >8 → STOP (K1).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.finance import get_problem, load_manifest  # noqa: E402
from contracts.schemas import AgentConfig  # noqa: E402
from correction.judge import grade  # noqa: E402


ANSWERS_PATH = ROOT / "runs" / "judge_reliability_answers.jsonl"
GRADES_PATH = ROOT / "runs" / "judge_reliability_grades.jsonl"
SUMMARY_PATH = ROOT / "runs" / "judge_reliability_summary.json"


def stratified_sample(n: int, seed: int = 42) -> list[str]:
    m = load_manifest()
    # Prefer validation for reliability (not held-out).
    ids = list(m["validation_ids"])
    by_cat: dict[str, list[str]] = defaultdict(list)
    for qid in ids:
        by_cat[get_problem(qid)["category"]].append(qid)
    rng = random.Random(seed)
    for v in by_cat.values():
        rng.shuffle(v)
    picked: list[str] = []
    pools = sorted(by_cat.items(), key=lambda kv: len(kv[1]))
    while len(picked) < n and any(p for _, p in pools):
        for _, pool in pools:
            if pool and len(picked) < n:
                picked.append(pool.pop())
    return picked


def _load_done(path: Path, key: str) -> set[str]:
    done: set[str] = set()
    if not path.exists():
        return done
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        done.add(row[key])
    return done


def generate_answers(ids: list[str], model: str, resume: bool) -> None:
    from adapters.finance import generate_answer

    ANSWERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    done = _load_done(ANSWERS_PATH, "id") if resume else set()
    cfg = AgentConfig(config_id="judge-rel-student", model=model, few_shot_examples=[])
    with ANSWERS_PATH.open("a", encoding="utf-8") as out:
        for i, qid in enumerate(ids, 1):
            if qid in done:
                print(f"  [ans {i}/{len(ids)}] {qid} skip", flush=True)
                continue
            p = get_problem(qid)
            try:
                text, _ = generate_answer(p["question"], cfg, p["category"])
            except Exception as exc:
                print(
                    f"  [ans {i}/{len(ids)}] {qid} FAILED ({exc.__class__.__name__}: {exc}) — skip",
                    flush=True,
                )
                out.write(
                    json.dumps(
                        {
                            "id": qid,
                            "category": p["category"],
                            "answer": "",
                            "error": f"{exc.__class__.__name__}: {exc}",
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                out.flush()
                continue
            out.write(
                json.dumps(
                    {"id": qid, "category": p["category"], "answer": text},
                    ensure_ascii=False,
                )
                + "\n"
            )
            out.flush()
            print(f"  [ans {i}/{len(ids)}] {qid} chars={len(text)}", flush=True)


def _answers_by_id() -> dict[str, dict]:
    rows = {}
    for line in ANSWERS_PATH.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            rows[r["id"]] = r
    return rows


def grade_twice(ids: list[str], resume: bool) -> None:
    done_keys = set()
    if resume and GRADES_PATH.exists():
        for line in GRADES_PATH.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                done_keys.add((r["id"], r["pass_i"]))
    answers = _answers_by_id()
    GRADES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with GRADES_PATH.open("a", encoding="utf-8") as out:
        for i, qid in enumerate(ids, 1):
            p = get_problem(qid)
            row_a = answers.get(qid) or {}
            ans = row_a.get("answer") or ""
            if not ans or row_a.get("error"):
                print(
                    f"  [grade {i}/{len(ids)}] {qid} skip (no answer)",
                    flush=True,
                )
                continue
            for pass_i in (1, 2):
                if (qid, pass_i) in done_keys:
                    print(f"  [grade {i}/{len(ids)}] {qid} p{pass_i} skip", flush=True)
                    continue
                try:
                    result = grade(
                        question=p["question"],
                        rubric=p["rubric"],
                        answer=ans,
                        passes=1,  # single call per fresh context
                    )
                except Exception as exc:
                    print(
                        f"  [grade {i}/{len(ids)}] {qid} p{pass_i} FAILED ({exc})",
                        flush=True,
                    )
                    continue
                row = {
                    "id": qid,
                    "pass_i": pass_i,
                    "normalized": result["normalized"],
                    "total": result["total"],
                    "max": result["max"],
                    "traps_hit": result["traps_hit"],
                }
                out.write(json.dumps(row) + "\n")
                out.flush()
                print(
                    f"  [grade {i}/{len(ids)}] {qid} p{pass_i} "
                    f"norm={result['normalized']:.1f}",
                    flush=True,
                )


def pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return float("nan")
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denx = sum((x - mx) ** 2 for x in xs) ** 0.5
    deny = sum((y - my) ** 2 for y in ys) ** 0.5
    if denx == 0 or deny == 0:
        return float("nan")
    return num / (denx * deny)


def summarize() -> dict:
    by_id: dict[str, dict[int, float]] = defaultdict(dict)
    for line in GRADES_PATH.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        by_id[r["id"]][r["pass_i"]] = float(r["normalized"])
    pairs = [
        (v[1], v[2]) for v in by_id.values() if 1 in v and 2 in v
    ]
    if not pairs:
        raise SystemExit("no complete grade pairs")
    a = [p[0] for p in pairs]
    b = [p[1] for p in pairs]
    mad = sum(abs(x - y) for x, y in pairs) / len(pairs)
    r = pearson(a, b)
    if mad <= 5:
        gate = "PASS_SINGLE"
        passes = 1
    elif mad <= 8:
        gate = "DOUBLE_PASS"
        passes = 2
    else:
        gate = "STOP_K1"
        passes = None
    summary = {
        "n": len(pairs),
        "pearson_r": r,
        "mad": mad,
        "gate": gate,
        "JUDGE_PASSES": passes,
        "mean_pass1": sum(a) / len(a),
        "mean_pass2": sum(b) / len(b),
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def write_audit_sample(n: int = 15, seed: int = 42) -> Path:
    rng = random.Random(seed)
    answers = _answers_by_id()
    grades: dict[str, list[dict]] = defaultdict(list)
    for line in GRADES_PATH.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            grades[r["id"]].append(r)
    ids = [i for i in answers if i in grades]
    rng.shuffle(ids)
    ids = ids[:n]
    out = ROOT / "runs" / "judge_audit_sample.md"
    lines = ["# Judge hand-audit sample (15)\n", "Flag for Rohan review.\n"]
    for qid in ids:
        p = get_problem(qid)
        g = grades[qid]
        lines.append(f"## {qid} — {p['category']}\n")
        lines.append(f"**Norm scores:** " + ", ".join(f"p{x['pass_i']}={x['normalized']:.1f}" for x in g) + "\n")
        lines.append("### Question (truncated)\n")
        lines.append("```\n" + p["question"][:1500] + "\n```\n")
        lines.append("### Answer (truncated)\n")
        lines.append("```\n" + answers[qid]["answer"][:2000] + "\n```\n")
        lines.append("### Grade rows\n")
        lines.append("```json\n" + json.dumps(g, indent=2) + "\n```\n")
    out.write_text("\n".join(lines))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--student-model", default="qwen/qwen3-8b")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--answers-only", action="store_true")
    ap.add_argument("--grades-only", action="store_true")
    ap.add_argument("--summarize-only", action="store_true")
    args = ap.parse_args()

    os.environ.setdefault("AGENT_BASE_URL", "https://api.pinference.ai/api/v1")
    os.environ.setdefault("AGENT_TIMEOUT_S", "90")

    ids = stratified_sample(args.n, seed=args.seed)
    print(f"[rel] n={len(ids)} student={args.student_model}", flush=True)

    if args.summarize_only:
        s = summarize()
        print(json.dumps(s, indent=2))
        return

    if not args.grades_only:
        generate_answers(ids, args.student_model, resume=args.resume)
    if args.answers_only:
        return
    grade_twice(ids, resume=args.resume)
    s = summarize()
    audit = write_audit_sample()
    print("=== RELIABILITY ===")
    print(json.dumps(s, indent=2))
    print(f"audit sample → {audit}")
    if s["gate"] == "STOP_K1":
        print("GATE FAIL: MAD > 8 — stop and write Questions section (K1)")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
