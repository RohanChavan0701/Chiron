"""Make E / H / B splits with E and H drawn from disjoint Spider databases.

Spider dev has only 20 databases. A random task split would put the same
databases in E and H, so an edit that memorizes E's tables would also help H.
We assign whole databases to E or H, then sample tasks within each side.

Usage: python -m rsi.splits [--out splits.json] [--bird-fallback]
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict

from rsi.config import ROOT, SPLITS, frozen, resolve
from rsi.data import Task, load_bird, load_spider


def gold_nonempty(t: Task, cfg: dict) -> bool:
    """True if the gold query runs and returns at least one row on the task's database.

    An empty gold result lets any query that also returns nothing pass, which the
    run-1 test-suite audit found inflated E scores (5 to 9 of the E passes).
    """
    from rsi.sqlexec import execute
    r = execute(t.db_path, t.gold_sql, cfg["eval"]["exec_timeout_s"], cfg["eval"]["max_result_rows"])
    return r.ok and bool(r.rows)


def _assign_dbs(tasks_by_db: dict[str, list[Task]], e_ok, h_ok, n: int, rng: random.Random,
                cap: int | None = None):
    """Greedy assignment of whole databases to E or H so each side can reach n tasks."""
    dbs = sorted(tasks_by_db)
    rng.shuffle(dbs)
    e_dbs, h_dbs, e_cnt, h_cnt = [], [], 0, 0
    for db in dbs:
        ne = sum(1 for t in tasks_by_db[db] if e_ok(t))
        nh = sum(1 for t in tasks_by_db[db] if h_ok(t))
        if cap:
            ne, nh = min(ne, cap), min(nh, cap)
        # give the database to whichever side is further from its target, relative to what it adds
        need_e, need_h = max(0, n - e_cnt), max(0, n - h_cnt)
        if need_e == 0 and need_h == 0:
            break
        if (need_e > 0 and ne > 0) and (need_e >= need_h or nh == 0):
            e_dbs.append(db); e_cnt += ne
        elif need_h > 0 and nh > 0:
            h_dbs.append(db); h_cnt += nh
        elif need_e > 0 and ne > 0:
            e_dbs.append(db); e_cnt += ne
    return e_dbs, h_dbs, e_cnt, h_cnt


def make_splits(spider_dev: list[Task], bird: list[Task], cfg: dict, bird_fallback: bool = False) -> dict:
    s = cfg["splits"]
    n = s["n_per_split"]
    rng = random.Random(cfg["seed"])
    cap = s.get("max_tasks_per_db")
    if s.get("exclude_empty_gold"):
        keep = lambda t: gold_nonempty(t, cfg)
    else:
        keep = lambda t: True
    e_ok = lambda t: t.difficulty in s["e_hardness"]
    h_ok = lambda t: t.difficulty in s["h_hardness"]
    if s.get("exclude_empty_gold"):
        spider_dev = [t for t in spider_dev if not (e_ok(t) or h_ok(t)) or keep(t)]

    by_db = defaultdict(list)
    for t in spider_dev:
        by_db[t.db_id].append(t)
    e_dbs, h_dbs, e_cnt, h_cnt = _assign_dbs(by_db, e_ok, h_ok, n, rng, cap)
    if e_cnt < n or h_cnt < n:
        raise RuntimeError(f"Cannot reach n={n} with disjoint databases (E has {e_cnt}, H has {h_cnt}). "
                           "Lower n_per_split or widen hardness tiers, and record that.")
    def capped(dbs, ok):
        out = []
        for db in dbs:
            ts = [t for t in by_db[db] if ok(t)]
            out += rng.sample(ts, min(cap, len(ts))) if cap else ts
        return out
    e_pool = capped(e_dbs, e_ok)
    h_pool = capped(h_dbs, h_ok)
    E = sorted(rng.sample(e_pool, n), key=lambda t: t.task_id)
    H = sorted(rng.sample(h_pool, n), key=lambda t: t.task_id)

    tiers = s["b_fallback_difficulty"] if bird_fallback else s["b_difficulty"]
    b_pool = [t for t in bird if t.difficulty in tiers and keep(t)]
    if len(b_pool) < n:
        raise RuntimeError(f"Only {len(b_pool)} BIRD tasks in tiers {tiers}")
    B = sorted(rng.sample(b_pool, n), key=lambda t: t.task_id)

    assert not ({t.db_id for t in E} & {t.db_id for t in H}), "E/H database overlap"
    return {
        "seed": cfg["seed"],
        "n_per_split": n,
        "bird_tiers": tiers,
        "bird_fallback_used": bird_fallback,
        **({"max_tasks_per_db": cap} if cap else {}),
        **({"exclude_empty_gold": True} if s.get("exclude_empty_gold") else {}),
        "E_dbs": sorted({t.db_id for t in E}),
        "H_dbs": sorted({t.db_id for t in H}),
        "E": [t.task_id for t in E],
        "H": [t.task_id for t in H],
        "B": [t.task_id for t in B],
    }


def make_splits_v4(spider_dev: list[Task], spider_train: list[Task], bird: list[Task], cfg: dict) -> dict:
    """Run-4 design (fixes from the multi-reviewer critique).

    E and E2 come from Spider TRAIN databases, so H can be every eligible Spider dev task
    (one fixed, large held-out set shared by all seeds). E2 holds fresh tasks from E's
    databases: it measures in-distribution gain without the selection on E.
    B is every eligible BIRD Mini-Dev task in the listed tiers (fixed across seeds).
    Only the E/E2 draw depends on the seed. E, E2 and H use the same hardness tiers.
    """
    s = cfg["splits"]
    rng = random.Random(cfg["seed"])
    keep = (lambda t: gold_nonempty(t, cfg)) if s.get("exclude_empty_gold") else (lambda t: True)
    tiers = set(s["e_hardness"])
    if set(s["h_hardness"]) != tiers:
        raise ValueError("v4 design: E and H must use the same hardness tiers")
    bird_dbs = {t.db_id for t in bird}
    dev_dbs = {t.db_id for t in spider_dev}

    H = sorted((t for t in spider_dev if t.difficulty in tiers and keep(t)), key=lambda t: t.task_id)
    B = sorted((t for t in bird if t.difficulty in s["b_difficulty"] and keep(t)), key=lambda t: t.task_id)
    # Run 5 (slower agent): optional fixed subsamples of H and B. The RNG does not depend on
    # the seed, so every seed still gets the same held-out tasks.
    if s.get("h_max") and len(H) > s["h_max"]:
        H = sorted(random.Random("heldout-H").sample(H, s["h_max"]), key=lambda t: t.task_id)
    if s.get("b_max") and len(B) > s["b_max"]:
        B = sorted(random.Random("heldout-B").sample(B, s["b_max"]), key=lambda t: t.task_id)

    by_db = defaultdict(list)
    for t in spider_train:
        if t.difficulty in tiers and t.db_id not in bird_dbs and t.db_id not in dev_dbs:
            by_db[t.db_id].append(t)
    n_e, n_e2, cap = s["n_e"], s["n_e2"], s["max_tasks_per_db"]
    dbs = sorted(by_db)
    rng.shuffle(dbs)
    E, E2, used = [], [], []
    for db in dbs:
        if len(E) >= n_e and len(E2) >= n_e2:
            break
        ts = [t for t in sorted(by_db[db], key=lambda t: t.task_id) if keep(t)]
        rng.shuffle(ts)
        if len(ts) < 2:
            continue
        take_e = min(cap, n_e - len(E), len(ts) // 2)
        take_e2 = min(cap, n_e2 - len(E2), len(ts) - take_e)
        if take_e <= 0 and take_e2 <= 0:
            continue
        E += ts[:take_e]
        E2 += ts[take_e:take_e + take_e2]
        used.append(db)
    if len(E) < n_e or len(E2) < n_e2:
        raise RuntimeError(f"v4 split: E {len(E)}/{n_e}, E2 {len(E2)}/{n_e2}")
    E = sorted(E, key=lambda t: t.task_id)
    E2 = sorted(E2, key=lambda t: t.task_id)
    assert not ({t.task_id for t in E} & {t.task_id for t in E2})
    assert not ({t.db_id for t in E} & {t.db_id for t in H})
    return {
        "design": "v4",
        "seed": cfg["seed"],
        "n_per_split": {"E": len(E), "E2": len(E2), "H": len(H), "B": len(B)},
        "bird_tiers": s["b_difficulty"],
        "exclude_empty_gold": bool(s.get("exclude_empty_gold")),
        "E_dbs": sorted({t.db_id for t in E}),
        "H_dbs": sorted({t.db_id for t in H}),
        "E": [t.task_id for t in E],
        "E2": [t.task_id for t in E2],
        "H": [t.task_id for t in H],
        "B": [t.task_id for t in B],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(SPLITS))
    ap.add_argument("--bird-fallback", action="store_true",
                    help="resample B from simple/moderate only (use only if B baseline < 5%%; record it)")
    args = ap.parse_args()
    cfg = frozen()
    dev = load_spider(resolve(cfg["data"]["spider_dir"]), "dev")
    bird = load_bird(resolve(cfg["data"]["bird_dir"]), cfg["data"].get("bird_json"))
    if cfg["splits"].get("design") == "v4":
        train = load_spider(resolve(cfg["data"]["spider_dir"]), "train")
        sp = make_splits_v4(dev, train, bird, cfg)
    else:
        sp = make_splits(dev, bird, cfg, args.bird_fallback)
    with open(args.out, "w") as f:
        json.dump(sp, f, indent=1)
    print(f"E: {len(sp['E'])} tasks on {len(sp['E_dbs'])} dbs | H: {len(sp['H'])} on {len(sp['H_dbs'])} dbs "
          f"| B: {len(sp['B'])} ({sp['bird_tiers']})"
          + (f" | E2: {len(sp['E2'])}" if "E2" in sp else "") + f" -> {args.out}")


if __name__ == "__main__":
    main()
