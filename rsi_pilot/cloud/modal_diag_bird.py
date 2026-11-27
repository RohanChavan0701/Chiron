"""Diagnostic, CPU only: time every BIRD Mini-Dev gold query in the Modal container.

Why: the split consistency check stopped the first ablation sessions because the regenerated
BIRD list differed from run 5's. Split eligibility (rsi/splits.py gold_nonempty) runs each gold
query under the frozen 30 s timeout, so a gold query that is slow, empty or failing in this
environment changes the list. This prints which ones, and nothing about any harness.

  modal run cloud/modal_diag_bird.py [--where local|volume]
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

import modal

# Import the sibling module by file path: inside the container only this file is at /root,
# so a package import of `cloud` would fail. The image carries the repo under IMAGE_REPO.
import importlib.util
_here = Path(__file__).resolve().parent
_cand = [_here / "modal_ablation.py", Path("/opt/chiron/rsi_pilot/cloud/modal_ablation.py")]
_spec = importlib.util.spec_from_file_location("modal_ablation", next(p for p in _cand if p.exists()))
A = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(A)

app = modal.App("chiron-diag-bird")


@app.function(image=A.image, cpu=(4.0, 4.0), memory=(16384, 16384), timeout=45 * 60,
              volumes={A.DATA_MOUNT: A.data_vol.with_mount_options(read_only=True)})
def time_gold(where: str = "local") -> list[dict]:
    work = Path(A.WORK_ROOT) / "diag" / "rsi_pilot"
    if work.parent.exists():
        shutil.rmtree(work.parent)
    shutil.copytree(A.IMAGE_REPO, work, symlinks=True)
    shutil.copytree(A.IMAGE_HARNESS, work.parent / "harness")
    A.normalize_eol(work.parent)
    if where == "local":
        shutil.copytree(A.DATA_IN_VOLUME, work / "data")
    else:
        (work / "data").symlink_to(A.DATA_IN_VOLUME, target_is_directory=True)
    sys.path.insert(0, str(work))
    from rsi.config import load_yaml
    from rsi.data import load_bird
    from rsi.sqlexec import execute
    cfg = load_yaml(work / "frozen_v5_s20261211.yaml")
    ev = cfg["eval"]
    out = []
    for t in load_bird(work / cfg["data"]["bird_dir"], cfg["data"].get("bird_json")):
        if t.difficulty not in cfg["splits"]["b_difficulty"]:
            continue
        t0 = time.time()
        r = execute(t.db_path, t.gold_sql, ev["exec_timeout_s"], ev["max_result_rows"])
        out.append({"task_id": t.task_id, "db": t.db_id, "ok": bool(r.ok), "rows": len(r.rows or []),
                    "seconds": round(time.time() - t0, 2), "error": (r.error or "")[:160]})
    return out


@app.local_entrypoint()
def main(where: str = "local"):
    res = time_gold.remote(where)
    Path("runs_v5/ablation_logs").mkdir(parents=True, exist_ok=True)
    Path(f"runs_v5/ablation_logs/bird_gold_timing_{where}.json").write_text(json.dumps(res, indent=1))
    bad = [r for r in res if not (r["ok"] and r["rows"])]
    slow = sorted(res, key=lambda r: -r["seconds"])[:8]
    print(f"entries {len(res)}; not eligible here (failed, timed out or empty): {len(bad)}")
    for r in bad:
        print("  NOT ELIGIBLE", r)
    print("slowest:", [(r["task_id"], r["db"], r["seconds"]) for r in slow])
