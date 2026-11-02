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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(SPLITS))
    ap.add_argument("--bird-fallback", action="store_true",
                    help="resample B from simple/moderate only (use only if B baseline < 5%%; record it)")
    args = ap.parse_args()
    cfg = frozen()
    dev = load_spider(resolve(cfg["data"]["spider_dir"]), "dev")
    bird = load_bird(resolve(cfg["data"]["bird_dir"]), cfg["data"].get("bird_json"))
    sp = make_splits(dev, bird, cfg, args.bird_fallback)
    with open(args.out, "w") as f:
        json.dump(sp, f, indent=1)
    print(f"E: {len(sp['E'])} tasks on {len(sp['E_dbs'])} dbs | H: {len(sp['H'])} on {len(sp['H_dbs'])} dbs "
          f"| B: {len(sp['B'])} ({sp['bird_tiers']}) -> {args.out}")


if __name__ == "__main__":
    main()
