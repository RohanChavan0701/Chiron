"""Run 6 stage 1: edit bank at two anchors, then variance components and selection replay.

  python -m rsi.bank anchor   [--frozen F] [--workers N]    truth-only grid; picks the strong anchor
  python -m rsi.bank build    [--frozen F] [--workers N] [--deadline EPOCH]
  python -m rsi.bank propose  [--frozen F]      stage 2: LLM edits from sources s2, s3, s4 (then build again)
  python -m rsi.bank analyze  [--frozen F]

`build` evaluates every catalog edit (rsi/fin_edits.py) at the weak and the strong anchor,
interleaved so a run cut short by the deadline still covers both anchors evenly. Everything
is cached per harness (rsi/stage0.py), so `build` resumes and `analyze` reads whatever exists.
Stage 1 is exploratory: nothing here is pre-registered.
"""
from __future__ import annotations

import argparse
import json
import time
from statistics import fmean

from rsi import fin_edits, fin_propose, goodhart, replay, stage0
from rsi.config import dump_yaml, load_yaml, resolve, stable_hash
from rsi.domains import finqa

PROXIES = ("p1", "p2", "p3")


def anchors(cfg: dict) -> dict[str, dict]:
    out = {"weak": finqa.validate(dict(fin_edits.WEAK))}
    strong = resolve(cfg["out_dir"]) / "anchor_strong.yaml"
    if strong.exists():
        out["strong"] = finqa.validate(load_yaml(strong))
    return out


def find_anchor(cfg, tasks, student, workers) -> dict:
    """Strong anchor = best truth accuracy over the settings grid, baseline prompt, no rules.
    Truth-selected on purpose: the strong state should be good for real."""
    rows = []
    for h in fin_edits.anchor_grid(stage0.baseline()):
        recs = stage0.episodes(cfg, h, tasks, student, 0, workers)
        rows.append({"table_format": h["table_format"], "max_steps": h["max_steps"],
                     "verify_before_submit": h["verify_before_submit"],
                     "truth": fmean(float(r["pass"]) for r in recs), "harness": h})
    best = max(rows, key=lambda r: r["truth"])
    dump_yaml(best["harness"], resolve(cfg["out_dir"]) / "anchor_strong.yaml")
    weak = stage0.episodes(cfg, fin_edits.WEAK, tasks, student, 0, workers)
    return {"grid": [{k: v for k, v in r.items() if k != "harness"} for r in rows],
            "strong_truth": best["truth"], "weak_truth": fmean(float(r["pass"]) for r in weak)}


def all_edits(cfg: dict, anchor_name: str, h: dict) -> list[dict]:
    """Hand-written catalog plus any LLM proposals stored for this anchor (rsi/fin_propose.py)."""
    return fin_edits.catalog(h) + fin_propose.stored(cfg, anchor_name)


def propose_all(cfg, tasks, llm) -> dict:
    """Stage 2: ask the proposer for edits from each source at each anchor."""
    return {f"{a}/{src}": len(fin_propose.propose(cfg, a, h, tasks, src, llm))
            for a, h in anchors(cfg).items() for src in fin_propose.SOURCES}


def _cached(cfg: dict, h: dict, tasks, repeat: int) -> bool:
    key = stable_hash({"h": h, "tasks": [t.task_id for t in tasks], "repeat": repeat,
                       "student": cfg["student"], "judge": cfg["judge"]})
    return (resolve(cfg["out_dir"]) / f"gr_{key}.json").exists()


def jobs(cfg: dict) -> list[tuple[str, str, dict, int]]:
    """(anchor, edit id or 'baseline', harness, repeat), anchors interleaved."""
    anc = anchors(cfg)
    out = [(a, "baseline", h, r) for r in range(cfg["baseline_repeats"]) for a, h in anc.items()]
    cats = {a: all_edits(cfg, a, h) for a, h in anc.items()}
    for i in range(max(len(c) for c in cats.values())):
        out += [(a, c[i]["id"], c[i]["harness"], 0) for a, c in cats.items() if i < len(c)]
    return out


def build(cfg, tasks, student, judge, workers, deadline: float | None = None) -> dict:
    done, spent, skipped = 0, [], 0
    for anchor, eid, h, rep in jobs(cfg):
        if _cached(cfg, h, tasks, rep):
            done += 1
            continue
        if deadline and spent and time.time() + 1.5 * max(spent) > deadline:
            skipped += 1
            continue
        t0 = time.time()
        stage0.evaluate(cfg, h, tasks, student, judge, rep, workers)
        spent.append(time.time() - t0)
        done += 1
    return {"evaluated": done, "skipped_for_deadline": skipped,
            "seconds_per_harness": fmean(spent) if spent else None}


def load(cfg, tasks) -> dict:
    """Per anchor: baseline means and per-edit 0/1 rows for truth and each proxy, cached runs only."""
    out = {}
    for anchor, h0 in anchors(cfg).items():
        base = [stage0.evaluate(cfg, h0, tasks, None, None, r, 1) for r in range(cfg["baseline_repeats"])
                if _cached(cfg, h0, tasks, r)]
        if not base:
            continue
        b = {k: [fmean(col) for col in zip(*(stage0.rate(x, k) for x in base))] for k in ("truth",) + PROXIES}
        edits = []
        for item in all_edits(cfg, anchor, h0):
            if _cached(cfg, item["harness"], tasks, 0):
                recs = stage0.evaluate(cfg, item["harness"], tasks, None, None, 0, 1)
                edits.append({"id": item["id"], "source": item["source"],
                              **{k: stage0.rate(recs, k) for k in ("truth",) + PROXIES}})
        out[anchor] = {"baseline": b, "baseline_runs": [stage0.summarize(x) for x in base], "edits": edits}
    return out


def analyze(cfg, tasks) -> dict:
    data, out = load(cfg, tasks), {}
    n_tasks = len(tasks)
    for anchor, d in data.items():
        b, edits = d["baseline"], d["edits"]
        res = {"n_edits": len(edits), "n_tasks": n_tasks, "baseline_runs": d["baseline_runs"], "edits": {},
               "proxies": {}}
        for e in edits:
            res["edits"][e["id"]] = {k: fmean(e[k]) - fmean(b[k]) for k in ("truth",) + PROXIES}
        if len(edits) >= 3:
            t = [e["truth"] for e in edits]
            for px in PROXIES:
                p = [e[px] for e in edits]
                comp = goodhart.components(t, p, b["truth"], b[px])
                m_half = n_tasks // 2
                res["proxies"][px] = {
                    "components": comp,
                    "shares_model": {m: goodhart.shares(comp, m) for m in (25, 50, 100, 400)},
                    "replay": {rule: replay.replay(t, p, b["truth"], b[px], k=min(8, len(edits)), m=m_half,
                                                   rule=rule, rounds=1000, seed=cfg["seed"])
                               for rule in ("greedy", "random", "threshold:0.05", "audit:20")},
                    "replay_m25": replay.replay(t, p, b["truth"], b[px], k=min(8, len(edits)),
                                                m=min(25, n_tasks - 1), rounds=1000, seed=cfg["seed"])}
        res["by_source"] = {}
        for src in sorted({e["source"] for e in edits}):
            sub = [e for e in edits if e["source"] == src]
            row = {"n": len(sub), **{f"mean_{k}_gain": fmean(fmean(e[k]) - fmean(b[k]) for e in sub)
                                    for k in ("truth",) + PROXIES}}
            if len(sub) >= 3:
                comp = goodhart.components([e["truth"] for e in sub], [e["p2"] for e in sub], b["truth"], b["p2"])
                row.update({"p2_sd_true": max(comp["s_aa"], 0) ** 0.5, "p2_sd_bias": max(comp["s_bb"], 0) ** 0.5,
                            "p2_mean_bias": comp["mean_bias"]})
            res["by_source"][src] = row
        out[anchor] = res
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["anchor", "build", "propose", "analyze"])
    ap.add_argument("--frozen", default="frozen_v6_stage1.yaml")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--deadline", type=float, help="unix time; build starts no harness it cannot finish by then")
    args = ap.parse_args()
    cfg = load_yaml(resolve(args.frozen))
    tasks = stage0.sample_tasks(cfg)
    if args.command == "analyze":
        result = analyze(cfg, tasks)
    else:
        from rsi.llm import make_llm
        from rsi.student import make_student
        student = make_student(cfg["student"])
        if args.command == "anchor":
            result = find_anchor(cfg, tasks, student, args.workers)
        elif args.command == "propose":
            result = propose_all(cfg, tasks, make_llm(cfg["proposer"]))
        else:
            result = build(cfg, tasks, student, make_llm(cfg["judge"]), args.workers, args.deadline)
    out_dir = resolve(cfg["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{args.command}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result if args.command != "analyze" else {a: {k: v for k, v in r.items() if k != "edits"}
                                                                for a, r in result.items()}, indent=2))


if __name__ == "__main__":
    main()
