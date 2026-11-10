"""Run 7 (RUN7_DESIGN.md, PREDICTION_run7.md): judge noise and the winner's curse.

  python -m rsi.bank  build   --frozen frozen_v7.yaml --workers N [--deadline EPOCH]   the bank
  python -m rsi.run7  verdict [--workers N] [--deadline EPOCH]   regrade every harness, verdict judge
  python -m rsi.run7  repeat  [--workers N] [--deadline EPOCH]   ask the main judge again, fixed subset
  python -m rsi.run7  analyze                                    no model calls; run on the laptop

`verdict` and `repeat` read stored episodes and call only the judge. `analyze` computes the
registered quantities: the curse (mean replay noise) per selector, its ratio to the curse under
truth selection, the variance-component prediction of that ratio, and bootstrap intervals
(tasks resampled, edit catalog fixed: the registered one; tasks and edits: secondary).
"""
from __future__ import annotations

import argparse
import json
import random
import time
from statistics import fmean

from rsi import bank, goodhart, replay, stage0
from rsi.config import load_yaml, resolve

SELECTORS = ("truth", "p1", "p2", "p2v")     # p2 = main (recompute) judge, p2v = verdict judge


def variant(cfg: dict, name: str) -> dict:
    """The frozen config with the judge block changed; grades cache under a different key."""
    if name == "verdict":
        return {**cfg, "judge": {**cfg["judge"], **cfg["judge_verdict"]}}
    if name == "repeat":
        return {**cfg, "judge": {**cfg["judge"], "repeat": 1}}
    return cfg


def subset(cfg: dict, name: str) -> list[tuple[str, str, dict, int]]:
    """Harnesses a regrade covers: all of them, or the baselines plus the first edits in catalog order."""
    jobs = bank.jobs(cfg)
    if name != "repeat":
        return jobs
    base = [j for j in jobs if j[1] == "baseline"]
    return base + [j for j in jobs if j[1] != "baseline"][:cfg["repeat_edits"]]


def regrade(cfg, tasks, name: str, judge, workers: int, deadline: float | None = None) -> dict:
    v, done, spent, skipped, missing = variant(cfg, name), 0, [], 0, 0
    for _, _, h, rep in subset(cfg, name):
        if not bank._cached(cfg, h, tasks, rep):      # no episodes yet: the bank did not get this far
            missing += 1
            continue
        if bank._cached(v, h, tasks, rep):
            done += 1
            continue
        if deadline and spent and time.time() + 1.5 * max(spent) > deadline:
            skipped += 1
            continue
        t0 = time.time()
        stage0.evaluate(v, h, tasks, None, judge, rep, workers)
        spent.append(time.time() - t0)
        done += 1
    return {"variant": name, "graded": done, "skipped_for_deadline": skipped, "not_in_bank": missing,
            "seconds_per_harness": fmean(spent) if spent else None}


def rows(cfg, tasks) -> dict:
    """Per-task 0/1 rows for every edit and selector, cached grades only. An edit enters only if
    every available selector has graded it, so all selectors see the same edits."""
    (anchor, h0), = bank.anchors(cfg).items()
    cfgs = {"p2v": variant(cfg, "verdict")}
    reps = [r for r in range(cfg["baseline_repeats"]) if bank._cached(cfg, h0, tasks, r)]
    use_v = bool(reps) and all(bank._cached(cfgs["p2v"], h0, tasks, r) for r in reps)
    sels = [s for s in SELECTORS if s != "p2v" or use_v]

    def get(h, rep):
        main = stage0.evaluate(cfg, h, tasks, None, None, rep, 1)
        out = {s: stage0.rate(main, s) for s in ("truth", "p1", "p2")}
        if use_v:
            out["p2v"] = stage0.rate(stage0.evaluate(cfgs["p2v"], h, tasks, None, None, rep, 1), "p2")
        return out

    base = [get(h0, r) for r in reps]
    b = {s: [fmean(col) for col in zip(*(x[s] for x in base))] for s in sels}
    edits = []
    for item in bank.all_edits(cfg, anchor, h0):
        h = item["harness"]
        if bank._cached(cfg, h, tasks, 0) and (not use_v or bank._cached(cfgs["p2v"], h, tasks, 0)):
            edits.append({"id": item["id"], "source": item["source"], **get(h, 0)})
    return {"selectors": sels, "baseline": b, "edits": edits, "baseline_acc": [fmean(x["truth"]) for x in base]}


def curse_boot(t, P: dict, t0, P0: dict, k: int, m: int, rounds: int, rng: random.Random,
               weights: list[float] | None = None, edit_idx: list[int] | None = None) -> dict:
    """Greedy best-of-k replay for several selectors at once on shared splits and candidates.

    Same quantities as rsi.replay.replay (greedy), plus the random rule's bias, with task weights
    so a bootstrap resample of tasks keeps selection and fresh tasks disjoint: the split is over
    the original tasks and a resampled task carries its multiplicity as weight. `m` is the number
    of original tasks in the selection half. Returns, per selector, mean noise, bias, real, the
    bias of a random candidate, and the share of rounds that kept an edit.
    """
    n_tasks = len(t0)
    w = weights or [1.0] * n_tasks
    idx = edit_idx or list(range(len(t)))
    live = [j for j in range(n_tasks) if w[j] > 0]
    gt = {i: [w[j] * (t[i][j] - t0[j]) for j in range(n_tasks)] for i in set(idx)}
    gp = {s: {i: [w[j] * (P[s][i][j] - P0[s][j]) for j in range(n_tasks)] for i in set(idx)} for s in P}
    tot_t = {i: sum(gt[i]) for i in gt}
    tot_p = {s: {i: sum(gp[s][i]) for i in gp[s]} for s in P}
    w_all = sum(w)
    acc = {s: {"noise": 0.0, "bias": 0.0, "real": 0.0, "bias_random": 0.0, "kept": 0.0} for s in P}
    done = 0
    for _ in range(rounds):
        order = rng.sample(range(n_tasks), n_tasks)
        chosen = set(order[:m])
        sel = [j for j in live if j in chosen]
        w_sel = sum(w[j] for j in sel)
        w_fresh = w_all - w_sel
        if w_sel <= 0 or w_fresh <= 0:
            continue
        done += 1
        cands = [idx[c] for c in rng.sample(range(len(idx)), min(k, len(idx)))]
        for s in P:
            sel_p = {i: sum(gp[s][i][j] for j in sel) for i in set(cands)}
            first = cands[0]
            sel_t = sum(gt[first][j] for j in sel)
            acc[s]["bias_random"] += ((tot_p[s][first] - sel_p[first]) - (tot_t[first] - sel_t)) / w_fresh
            win = max(cands, key=lambda i: sel_p[i])
            if sel_p[win] <= 0:
                continue                                  # nothing kept: all terms are zero
            sel_t = sum(gt[win][j] for j in sel)
            fresh_p, fresh_t = (tot_p[s][win] - sel_p[win]) / w_fresh, (tot_t[win] - sel_t) / w_fresh
            acc[s]["noise"] += sel_p[win] / w_sel - fresh_p
            acc[s]["bias"] += fresh_p - fresh_t
            acc[s]["real"] += fresh_t
            acc[s]["kept"] += 1.0
    return {s: {key: v / max(done, 1) for key, v in a.items()} for s, a in acc.items()}


def _derived(stats: dict) -> dict:
    """Registered ratios and differences from one curse_boot result."""
    base = stats["truth"]["noise"]
    out = {}
    for s, a in stats.items():
        out[s] = {"curse": a["noise"], "multiplier": a["noise"] / base if base > 0 else None,
                  "bias_minus_random": a["bias"] - a["bias_random"], "real": a["real"]}
    return out


def _interval(values: list[float]) -> list[float] | None:
    v = sorted(x for x in values if x is not None)
    if len(v) < 20:
        return None
    return [v[int(0.025 * (len(v) - 1))], v[int(round(0.975 * (len(v) - 1)))]]


def bootstrap(t, P, t0, P0, k, m, boots, rounds, seed, resample_edits: bool = False) -> dict:
    """Percentile intervals over resampled tasks. The registered interval keeps the edit catalog
    fixed (the claim is about this set of edits); `resample_edits` also resamples the edits."""
    rng = random.Random(seed)
    n, n_tasks = len(t), len(t0)
    draws = []
    for _ in range(boots):
        w = [0.0] * n_tasks
        for _ in range(n_tasks):
            w[rng.randrange(n_tasks)] += 1.0
        edit_idx = [rng.randrange(n) for _ in range(n)] if resample_edits else None
        draws.append(_derived(curse_boot(t, P, t0, P0, k, m, rounds, rng, w, edit_idx)))
    return {s: {key: _interval([d[s][key] for d in draws]) for key in ("curse", "multiplier", "bias_minus_random",
                                                                         "real")} for s in P}


def repeat_stats(cfg, tasks) -> dict | None:
    """How often the main judge changes its verdict when asked again about the same episode."""
    v = variant(cfg, "repeat")
    flips = {"p1": [], "p2": []}
    wrong_flip, n_h = [], 0
    for _, _, h, rep in subset(cfg, "repeat"):
        if not (bank._cached(cfg, h, tasks, rep) and bank._cached(v, h, tasks, rep)):
            continue
        n_h += 1
        a, b = (stage0.evaluate(c, h, tasks, None, None, rep, 1) for c in (cfg, v))
        truth = stage0.rate(a, "truth")
        for px in flips:
            x, y = stage0.rate(a, px), stage0.rate(b, px)
            flips[px] += [float(i != j) for i, j in zip(x, y)]
            if px == "p2":
                wrong_flip += [float(i != j) for i, j, tr in zip(x, y, truth) if i != tr]
    if not n_h:
        return None
    return {"harnesses": n_h, "episodes": len(flips["p2"]), "p2_flip_rate": fmean(flips["p2"]),
            "p1_flip_rate": fmean(flips["p1"]),
            "p2_flip_rate_where_judge_disagreed_with_truth": fmean(wrong_flip) if wrong_flip else None}


def analyze(cfg, tasks) -> dict:
    d, a = rows(cfg, tasks), cfg["analysis"]
    sels, edits, b = d["selectors"], d["edits"], d["baseline"]
    t, t0 = [e["truth"] for e in edits], b["truth"]
    P, P0 = {s: [e[s] for e in edits] for s in sels}, {s: b[s] for s in sels}
    out = {"n_edits": len(edits), "n_tasks": len(tasks), "selectors": sels, "baseline_truth": d["baseline_acc"],
           "k": a["k"], "m": a["m"], "point": {}, "grid": {}}
    comp = {s: goodhart.components(t, P[s], t0, P0[s]) for s in sels}
    rep = {s: replay.replay(t, P[s], t0, P0[s], k=a["k"], m=a["m"], rule="greedy", rounds=a["rounds"],
                            seed=cfg["seed"]) for s in sels}
    rnd = {s: replay.replay(t, P[s], t0, P0[s], k=a["k"], m=a["m"], rule="random", rounds=a["rounds"],
                            seed=cfg["seed"]) for s in sels}
    for s in sels:
        agree = fmean(float(x == y) for e in edits for x, y in zip(e["truth"], e[s]))
        out["point"][s] = {
            "reported": rep[s]["reported"], "real": rep[s]["real"], "bias": rep[s]["bias"],
            "curse": rep[s]["noise"], "curse_true_part": rep[s]["noise_true"],
            "curse_judge_part": rep[s]["noise_bias"], "kept": rep[s]["kept"],
            "multiplier": rep[s]["noise"] / rep["truth"]["noise"] if rep["truth"]["noise"] > 0 else None,
            "multiplier_theory": (comp[s]["r_cc"] / comp["truth"]["r_cc"]) ** 0.5,
            "r_cc": comp[s]["r_cc"], "bias_random": rnd[s]["bias"],
            "bias_minus_random": rep[s]["bias"] - rnd[s]["bias"],
            "agreement_with_truth": agree, "approval_rate": fmean(fmean(e[s]) for e in edits)}
    out["interval95"] = bootstrap(t, P, t0, P0, a["k"], a["m"], a["boots"], a["boot_rounds"], cfg["seed"])
    out["interval95_tasks_and_edits"] = bootstrap(t, P, t0, P0, a["k"], a["m"], a["boots"], a["boot_rounds"],
                                                  cfg["seed"], resample_edits=True)
    rng = random.Random(cfg["seed"] + 1)
    for k in a["grid_k"]:
        for m in a["grid_m"]:
            g = _derived(curse_boot(t, P, t0, P0, min(k, len(edits)), m, a["rounds"], rng))
            out["grid"][f"k{k}_m{m}"] = {s: {"curse": g[s]["curse"], "multiplier": g[s]["multiplier"]} for s in sels}
    out["by_source"] = {}
    for src in sorted({e["source"] for e in edits}):
        sub = [e for e in edits if e["source"] == src]
        out["by_source"][src] = {"n": len(sub), **{f"mean_{s}_gain": fmean(fmean(e[s]) - fmean(b[s]) for e in sub)
                                                   for s in sels}}
    out["edits"] = {e["id"]: {s: fmean(e[s]) - fmean(b[s]) for s in sels} for e in edits}
    out["judge_repeat"] = repeat_stats(cfg, tasks)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["verdict", "repeat", "analyze"])
    ap.add_argument("--frozen", default="frozen_v7.yaml")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--deadline", type=float, help="unix time; no harness is started that cannot finish by then")
    args = ap.parse_args()
    cfg = load_yaml(resolve(args.frozen))
    tasks = stage0.sample_tasks(cfg)
    if args.command == "analyze":
        result = analyze(cfg, tasks)
    else:
        from rsi.llm import make_llm
        judge = make_llm(variant(cfg, args.command)["judge"])
        result = regrade(cfg, tasks, args.command, judge, args.workers, args.deadline)
    out_dir = resolve(cfg["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{args.command}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "edits"}, indent=2))


if __name__ == "__main__":
    main()
