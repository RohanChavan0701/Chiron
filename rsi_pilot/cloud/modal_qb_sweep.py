"""Run the QualityBench concurrent-serving sweep on one Modal GPU (runbook: cloud/QB_LOAD_SWEEP.md).

Approved by the author on 2026-11-27 ("go ahead launch item 2, cap it at 5"), moved from Lambda
(no credits) to Modal the same day. Patterned on cloud/modal_ablation.py: a local entrypoint
that refuses a dirty tree, prints the cost guard and spawns one GPU function; with
`modal run --detach` the laptop may then sleep.

What runs in the container (`run_sweep`): clone qualitybench main, apply the sweep commit shipped
as cloud/qb_load_sweep.patch (built into the image, so the launch runs exactly the committed
patch), point the sweep's expected venv at the image's vLLM, smoke (2 levels x 8 prompts), full
sweep (4 levels x 3 repeats x 2 prompt sets), results table. Results are copied to the out
volume every few minutes and at the end, so a timeout loses at most a few minutes of work.
The function's hard timeout is the cost watchdog; there is no retry.

Secrets: the model is gated, so the function reads HF_TOKEN from the Modal Secret named
HF_SECRET_NAME (create it once: `modal secret create huggingface HF_TOKEN=...`). The token
never passes through this file or the laptop's shell history beyond that command.

Offline helper (no Modal contact): python cloud/modal_qb_sweep.py plan
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import modal

# ---------------- constants (owner-editable) ----------------

APP_NAME = "chiron-qb-sweep"
# Pins the 40 GB A100 (https://modal.com/docs/guide/gpu, read 2026-11-27: plain "A100" may be
# upgraded to 80 GB). 40 GB matches the committed QualityBench matrix (Lambda A100-SXM4-40GB).
GPU = "A100-40GB"
EXPECTED_GPU = {"A100-40GB": ("A100", 39000)}      # nvidia-smi name substring, min memory.total MiB

PRICE_SOURCE = "https://modal.com/pricing (read 2026-11-27)"
GPU_PRICE_PER_S = {"A100-40GB": 0.000583, "A10": 0.000306}   # re-check before launch
CPU_CORE_PRICE_PER_S = 0.0000131
MEM_GIB_PRICE_PER_S = 0.00000222

BUDGET_USD = 5.0                  # author, 2026-11-27 chat
MAX_MINUTES = 100                 # hard timeout of run_sweep; about 2x the expected 50 min
STARTUP_MINUTES = 5               # startup_timeout; billed, so in the worst case
CPU = 4.0                         # physical cores, request = limit
MEM_MIB = 16384
COPY_EVERY_S = 300                # periodic copy of results to the out volume

VLLM_VERSION = "0.34.0"           # latest stable on PyPI, 2026-11-27; same pin as setup_vllm_serve.sh
QB_REPO = "https://github.com/RohanChavan0701/qualitybench.git"
QB_BASE = "main"
HF_SECRET_NAME = "huggingface"    # Modal Secret holding HF_TOKEN

LOCAL_REPO = Path(__file__).resolve().parents[1]              # rsi_pilot/ on the laptop
PATCH_LOCAL = LOCAL_REPO / "cloud" / "qb_load_sweep.patch"
PATCH_IMAGE = "/opt/chiron/qb_load_sweep.patch"
WORK = "/tmp/qb"
HF_MOUNT = "/vol/hf"
OUT_MOUNT = "/vol/out"
OUT_SUBDIR = "qb_load_sweep"                                   # out volume: qb_load_sweep/<run id>/
USED_PATTERNS = ["cloud/modal_qb_sweep.py", "cloud/qb_load_sweep.patch"]
RESULT_DIRS = ("results/load_sweep_smoke", "results/load_sweep")


class CostGuardError(RuntimeError):
    pass


class DirtyTreeError(RuntimeError):
    pass


# ---------------- pure helpers (tested offline) ----------------

def rate_per_s(gpu: str = GPU) -> float:
    if gpu not in GPU_PRICE_PER_S:
        raise CostGuardError(f"no price for GPU {gpu!r}; add it to GPU_PRICE_PER_S")
    return GPU_PRICE_PER_S[gpu] + CPU * CPU_CORE_PRICE_PER_S + MEM_MIB / 1024 * MEM_GIB_PRICE_PER_S


def worst_case_usd(minutes: float = MAX_MINUTES, gpu: str = GPU) -> float:
    """The one attempt running into its hard timeout, startup included."""
    return (minutes + STARTUP_MINUTES) * 60 * rate_per_s(gpu)


def check_budget(minutes: float = MAX_MINUTES, gpu: str = GPU, budget: float = BUDGET_USD) -> dict:
    worst = worst_case_usd(minutes, gpu)
    if worst > budget + 1e-9:
        raise CostGuardError(f"worst case {worst:.2f} USD ({minutes} min + {STARTUP_MINUTES} min startup on "
                             f"{gpu}) exceeds the budget {budget:.2f} USD; refusing to launch")
    return {"gpu": gpu, "price_source": PRICE_SOURCE, "rate_usd_per_hour": rate_per_s(gpu) * 3600,
            "minutes": minutes, "worst_case": worst, "budget": budget}


def format_plan(p: dict) -> str:
    return "\n".join([
        f"cost guard: one {p['gpu']} container at {p['rate_usd_per_hour']:.4f} USD/h "
        f"(GPU + {CPU:g} cores + {MEM_MIB // 1024} GiB), prices from {p['price_source']}",
        f"  worst case ({p['minutes']} min + {STARTUP_MINUTES} min startup): {p['worst_case']:.2f} USD "
        f"(budget {p['budget']:.2f} USD); no retries, a timeout ends the run",
    ])


def run_id(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y%m%dT%H%M%SZ")


def _porcelain_paths(line: str) -> list[str]:
    body = line[3:] if len(line) > 3 else ""
    parts = body.split(" -> ") if " -> " in body else [body]
    out = []
    for p in parts:
        p = p.strip()
        if len(p) >= 2 and p[0] == p[-1] == '"':
            p = p[1:-1]
        if p:
            out.append(p)
    return out


def dirty_used_files(porcelain: str, prefix: str = "rsi_pilot/", patterns=USED_PATTERNS) -> list[str]:
    bad = []
    for line in porcelain.splitlines():
        if not line.strip():
            continue
        for p in _porcelain_paths(line):
            if not p.startswith(prefix):
                continue
            rel = p[len(prefix):]
            if any(fnmatch.fnmatchcase(rel, pat) for pat in patterns):
                bad.append(line.rstrip())
                break
    return bad


def git_state(repo: Path = LOCAL_REPO) -> tuple[str, list[str]]:
    def g(*a):
        return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True).stdout
    commit = g("rev-parse", "HEAD").strip()
    prefix = g("rev-parse", "--show-prefix").strip()
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    return commit, dirty_used_files(g("status", "--porcelain=v1", "--untracked-files=all"), prefix)


def require_clean_tree(repo: Path = LOCAL_REPO) -> str:
    commit, bad = git_state(repo)
    if bad:
        raise DirtyTreeError("uncommitted changes in files the run uses (commit them first, the image is "
                             "built from the working tree):\n  " + "\n  ".join(bad))
    return commit


def gpu_ok(smi_csv: str, gpu: str = GPU) -> bool:
    """`nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits` -> matches EXPECTED_GPU."""
    name_sub, min_mib = EXPECTED_GPU[gpu]
    for line in smi_csv.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and name_sub in parts[0]:
            try:
                return int(float(parts[1])) >= min_mib
            except ValueError:
                return False
    return False


def summary_lines(res: dict) -> list[str]:
    """What the laptop prints. Carries no benchmark numbers (the table is in the volume)."""
    return [f"run {res.get('run_id', '?')}: {'ok' if res.get('ok') else 'FAILED'} in {res.get('duration_s', 0)} s"
            + (f"; error: {res['error']}" if res.get("error") else ""),
            f"results in volume chiron-qb-out under {OUT_SUBDIR}/{res.get('run_id', '?')}/"]


# ---------------- Modal definitions ----------------

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "curl", "ca-certificates", "procps")
    .pip_install(f"vllm[bench]=={VLLM_VERSION}", "pyyaml")
    .env({"PYTHONUNBUFFERED": "1", "HF_HOME": f"{HF_MOUNT}/hf_home"})
    .add_local_file(str(PATCH_LOCAL), PATCH_IMAGE)
)

hf_vol = modal.Volume.from_name("chiron-hf-cache", create_if_missing=True, version=2)
out_vol = modal.Volume.from_name("chiron-qb-out", create_if_missing=True, version=2)

app = modal.App(APP_NAME, image=image)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(cmd: list[str], cwd: str | None = None, env: dict | None = None, check: bool = True) -> str:
    r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed ({r.returncode}): {(r.stdout + r.stderr)[-2000:]}")
    return r.stdout + r.stderr


def _copy_results(work: Path, dest: Path) -> None:
    for rel in RESULT_DIRS:
        src = work / rel
        if src.is_dir():
            dst = dest / rel
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
    log = work / "qb_sweep.log"
    if log.is_file():
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(log, dest / "qb_sweep.log")
    out_vol.commit()


@app.function(gpu=GPU, cpu=(CPU, CPU), memory=(MEM_MIB, MEM_MIB),
              timeout=MAX_MINUTES * 60, startup_timeout=STARTUP_MINUTES * 60,
              max_containers=1, single_use_containers=True,
              secrets=[modal.Secret.from_name(HF_SECRET_NAME)],
              volumes={HF_MOUNT: hf_vol, OUT_MOUNT: out_vol})
def run_sweep(git_commit: str) -> dict:
    """One sweep. Returns {run_id, ok, duration_s, error}; never a throughput or latency number."""
    t0 = time.time()
    rid = run_id()
    res = {"run_id": rid, "ok": False, "duration_s": 0, "error": ""}
    dest = Path(OUT_MOUNT) / OUT_SUBDIR / rid
    dest.mkdir(parents=True, exist_ok=True)
    work = Path(WORK) / "qualitybench"
    stop = threading.Event()
    log_path = Path(WORK) / "qualitybench" / "qb_sweep.log"

    def copier():
        while not stop.wait(COPY_EVERY_S):
            try:
                _copy_results(work, dest)
            except Exception as e:  # noqa: BLE001
                print(f"periodic copy failed: {e}", flush=True)

    th = threading.Thread(target=copier, daemon=True)
    try:
        if not os.environ.get("HF_TOKEN"):
            raise RuntimeError(f"HF_TOKEN missing: create the Modal Secret {HF_SECRET_NAME!r} with HF_TOKEN")
        smi = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
        (dest / "nvidia_smi.txt").write_text(_run(["nvidia-smi"]) + "\n" + smi)
        if not gpu_ok(smi):
            raise RuntimeError(f"GPU does not match {GPU}: {smi.strip()}")
        Path(WORK).mkdir(parents=True, exist_ok=True)
        if work.exists():
            shutil.rmtree(work)
        _run(["git", "clone", "-q", "--branch", QB_BASE, QB_REPO, str(work)])
        base_commit = _run(["git", "rev-parse", "HEAD"], cwd=str(work)).strip()
        _run(["git", "-c", "user.name=qb-sweep", "-c", "user.email=qb-sweep@localhost", "am", "-q", PATCH_IMAGE],
             cwd=str(work))
        # The sweep expects .venv-vllm-serve/bin/{vllm,python,pip}; point them at the image's install
        # instead of running setup_vllm_serve.sh (same pinned vLLM, no second download).
        vb = work / ".venv-vllm-serve" / "bin"
        vb.mkdir(parents=True)
        for name in ("vllm", "python", "pip"):
            exe = shutil.which(name) or shutil.which(name + "3")
            if not exe:
                raise RuntimeError(f"{name} not on PATH in the image")
            (vb / name).symlink_to(exe)
        (dest / "run_record.json").write_text(json.dumps({
            "time": _now(), "chiron_commit": git_commit, "qualitybench_base": base_commit,
            "sweep_commit": _run(["git", "rev-parse", "HEAD"], cwd=str(work)).strip(),
            "gpu_requested": GPU, "platform": "modal", "vllm": _run([str(vb / "vllm"), "--version"], check=False).strip(),
            "image_python": sys.version}, indent=1))
        out_vol.commit()
        th.start()
        env = dict(os.environ)
        with open(log_path, "ab") as log:
            def sh(*args):
                p = subprocess.run(["bash", *args], cwd=str(work), env=env, stdout=log, stderr=subprocess.STDOUT)
                return p.returncode
            log.write(f"start {_now()}\n".encode())
            rc = sh("scripts/run_load_sweep.sh", "--out", "results/load_sweep_smoke", "--repeats", "1",
                    "--concurrency", "1 4", "--num-prompts", "8")
            if rc != 0:
                raise RuntimeError(f"smoke sweep exit {rc} (see qb_sweep.log and results/load_sweep_smoke/logs)")
            _run([str(vb / "python"), "analysis/load_sweep_table.py", "--results-dir", "results/load_sweep_smoke"],
                 cwd=str(work))
            log.write(f"smoke done {_now()}\n".encode())
            _copy_results(work, dest)
            rc = sh("scripts/run_load_sweep.sh", "--out", "results/load_sweep", "--repeats", "3")
            log.write(f"full sweep exit {rc} {_now()}\n".encode())
            table = _run([str(vb / "python"), "analysis/load_sweep_table.py", "--results-dir", "results/load_sweep"],
                         cwd=str(work), check=False)
            (work / "results" / "load_sweep" / "TABLE.md").write_text(table)
            if rc != 0:
                raise RuntimeError(f"full sweep exit {rc}; partial results and FAILURES.txt are in the volume")
        stop.set()
        _copy_results(work, dest)
        (dest / "DONE").write_text(f"{_now()} duration_s {int(time.time() - t0)}\n")
        out_vol.commit()
        res.update(ok=True)
    except Exception as e:  # noqa: BLE001  (error text carries no benchmark numbers)
        res["error"] = f"{type(e).__name__}: {e}"[:600]
        try:
            stop.set()
            _copy_results(work, dest)
            (dest / "FAILED").write_text(res["error"] + "\n")
            out_vol.commit()
        except Exception:  # noqa: BLE001
            pass
    finally:
        stop.set()
        res["duration_s"] = int(time.time() - t0)
    return res


@app.local_entrypoint()
def main():
    commit = require_clean_tree()
    plan = check_budget()
    print(format_plan(plan))
    print(f"git commit {commit}; GPU {GPU}; timeout {MAX_MINUTES} min; secret {HF_SECRET_NAME!r} must hold HF_TOKEN")
    call = run_sweep.spawn(commit)
    print(f"run_sweep call {call.object_id} (runs server side; with --detach the laptop may sleep)", flush=True)
    for line in summary_lines(call.get()):
        print(line)


def _cli(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="cloud/modal_qb_sweep.py", description="offline helpers, no Modal contact")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan", help="print the cost guard and check the tree")
    ap.parse_args(argv)
    print(format_plan(check_budget()))
    commit, bad = git_state()
    print(f"git commit {commit}")
    print("tree: clean for the run" if not bad else "tree: DIRTY, launch would be refused:\n  " + "\n  ".join(bad))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
