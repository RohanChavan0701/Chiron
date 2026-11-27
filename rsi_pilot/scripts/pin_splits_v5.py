"""Write splits_v5_s<SEED>.json from run 5's own evaluation records, so a later session scores
exactly the tasks run 5 scored instead of regenerating the split.

Why: rsi.splits decides eligibility by running every gold query under the frozen 30 s
timeout. One BIRD Mini-Dev gold query (bird_518, card_games) takes about 90 s on a laptop
and over 30 s on Modal's CPUs but finished under 30 s on the Lambda A10 that ran run 5, so a
regenerated split there drops it, the seeded 200-task subsample shifts, and the ablation's
consistency check refuses to run. bird_518 is not in run 5's held-out set for any seed, so
pinning the ids reproduces run 5 exactly; nothing else changes.

Source of the ids: runs_v5/s<SEED>/evals/baseline_{E,E2,H,B}.json (task order kept). The
Spider database lists (E_dbs, H_dbs) are informational in the split file and are filled when
the Spider data is present (--spider-dir), otherwise left null.

  python scripts/pin_splits_v5.py [--seeds 20261211 ...] [--spider-dir data/spider] [--force]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rsi.config import load_yaml  # noqa: E402

SEEDS = (20261211, 20261212, 20261213, 20261214, 20261215, 20261216)


def pin_one(seed: int, spider_dir: Path | None, force: bool) -> Path:
    runs = ROOT / f"runs_v5/s{seed}"
    out = ROOT / f"splits_v5_s{seed}.json"
    if out.exists() and not force:
        raise SystemExit(f"{out.name} exists; pass --force to overwrite")
    cfg = load_yaml(ROOT / f"frozen_v5_s{seed}.yaml")
    ids = {}
    for split in ("E", "E2", "H", "B"):
        rec = json.loads((runs / "evals" / f"baseline_{split}.json").read_text())
        assert rec["split"] == split, (seed, split, rec["split"])
        ids[split] = [r["task_id"] for r in rec["records"]]
        assert len(ids[split]) == rec["n"] == len(set(ids[split])), (seed, split)
    sp_cfg = cfg["splits"]
    assert len(ids["E"]) == sp_cfg["n_e"] and len(ids["E2"]) == sp_cfg["n_e2"]
    assert len(ids["H"]) == sp_cfg["h_max"] and len(ids["B"]) == sp_cfg["b_max"]
    assert not set(ids["E"]) & set(ids["E2"])
    e_dbs = h_dbs = None
    if spider_dir is not None:
        from rsi.data import load_spider
        dev = {t.task_id: t.db_id for t in load_spider(spider_dir, "dev")}
        train = {t.task_id: t.db_id for t in load_spider(spider_dir, "train")}
        e_dbs = sorted({train[i] for i in ids["E"]})
        h_dbs = sorted({dev[i] for i in ids["H"]})
        assert not set(e_dbs) & set(h_dbs)
    sp = {
        "design": "v4",
        "seed": seed,
        "n_per_split": {k: len(v) for k, v in ids.items()},
        "bird_tiers": sp_cfg["b_difficulty"],
        "exclude_empty_gold": bool(sp_cfg.get("exclude_empty_gold")),
        "E_dbs": e_dbs,
        "H_dbs": h_dbs,
        "E": ids["E"], "E2": ids["E2"], "H": ids["H"], "B": ids["B"],
        "pinned_from": f"runs_v5/s{seed}/evals/baseline_{{E,E2,H,B}}.json (run 5 records), "
                       "scripts/pin_splits_v5.py",
    }
    out.write_text(json.dumps(sp, indent=1) + "\n")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="*", default=list(SEEDS))
    ap.add_argument("--spider-dir", type=Path, default=None)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    for s in a.seeds:
        p = pin_one(s, a.spider_dir, a.force)
        sp = json.loads(p.read_text())
        print(f"{p.name}: " + ", ".join(f"{k} {v}" for k, v in sp["n_per_split"].items()))
    # H and B are the same tasks for every seed by design; say so explicitly.
    sps = [json.loads((ROOT / f"splits_v5_s{s}.json").read_text()) for s in a.seeds]
    for split in ("H", "B"):
        same = all(sp[split] == sps[0][split] for sp in sps)
        print(f"{split} identical across seeds: {same}")
        if not same:
            raise SystemExit(f"{split} differs across seeds; run 5's held-out sets should be fixed")


if __name__ == "__main__":
    main()
