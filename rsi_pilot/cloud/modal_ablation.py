"""Run the registered run-5 single-field ablation (PREDICTION_schema_only.md) on Modal GPUs.

Runbook: CLOUD_RUN_MODAL.md. Ported from cloud/ablation_remote.sh (the VM version): same
Ollama pin and settings, the same "100% GPU or stop" rule, the same SEED_DONE marker, and no
accuracy numbers anywhere in Modal's logs or return values (no peeking before all seeds are in).

Layout of one launch:
  local entrypoint `main`  -> refuses a dirty tree, prints the cost guard, spawns `orchestrate`
  `orchestrate` (CPU, server side, nonpreemptible) -> `prepare`, then `run_seed` for every seed
      concurrently, then one budget-guarded retry round for failed seeds (same seed, once)
  `prepare` (CPU) -> extracts the data archive into the data volume, pulls the student model
      into the models volume, runs the ablation unit tests
  `run_seed(seed)` (one GPU container per seed, all of the same GPU type) -> one session:
      `bash scripts/run_ablation.sh SEED 8` against one Ollama server on that GPU. The baseline
      and all variants of a seed run in that one container, which keeps the registered pairing.

Offline helpers (no Modal contact, no credentials):
  python cloud/modal_ablation.py plan          # cost guard and dirty-tree check
  python cloud/modal_ablation.py merge STAGE   # copy fetched results into the repo, never deleting

Importing this module needs the `modal` package but no token: nothing here contacts Modal
until `modal run` hydrates the app.
"""
from __future__ import annotations

import fnmatch
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import modal

# ---------------- constants (owner-editable) ----------------

APP_NAME = "chiron-ablation"
SEEDS = (20261211, 20261212, 20261213, 20261214, 20261215, 20261216)
WORKERS = 8                       # OLLAMA_NUM_PARALLEL and run_ablation.sh WORKERS, as in run 5

# One GPU type for every seed container. Modal's exact name for the 80 GB A100
# (https://modal.com/docs/guide/gpu, checked 2026-11-27; plain "A100" may also land on 40 GB).
GPU = "A100-80GB"
# What nvidia-smi must show for GPU: (name substring, minimum memory.total in MiB).
EXPECTED_GPU = {"A100-80GB": ("A100", 79000)}

# Prices in USD per second from https://modal.com/pricing, read 2026-11-27. RE-CHECK BEFORE LAUNCH.
PRICE_SOURCE = "https://modal.com/pricing (read 2026-11-27)"
GPU_PRICE_PER_S = {"A100-80GB": 0.000694}     # re-check before launch
CPU_CORE_PRICE_PER_S = 0.0000131              # per physical core (2 vCPU); re-check before launch
MEM_GIB_PRICE_PER_S = 0.00000222              # re-check before launch
NONPREEMPTIBLE_CPU_MEM_MULT = 3.0             # https://modal.com/docs/guide/preemption

BUDGET_USD = 30.0                 # set by the owner on 2026-11-27
MAX_SEED_MINUTES = 75             # per-attempt hard timeout of run_seed (see cost guard below)
STARTUP_MINUTES = 5               # run_seed startup_timeout; billed, so it is in the worst case
MAX_CONTAINERS = 6
MAX_STARTS_PER_SEED = 2           # first attempt + one rerun; preemption restarts count too
SOFT_MARGIN_S = 180               # stop the seed this long before the hard timeout to save logs

SEED_CPU = 8.0                    # physical cores, request = limit (16 vCPU)
SEED_MEM_MIB = 32768              # request = limit
PREP_CPU, PREP_MEM_MIB, PREP_MINUTES = 2.0, 8192, 60
ORCH_CPU, ORCH_MEM_MIB = 0.25, 1024
# orchestrate waits for prepare and two rounds of seeds (queueing included)
ORCH_MINUTES = PREP_MINUTES + 2 * (MAX_SEED_MINUTES + STARTUP_MINUTES + 15) + 30

OLLAMA_VERSION = "0.40.13"        # same as runs 4 to 7
OLLAMA_PORT = 11435               # run 5's student server; frozen_v5*.yaml points at this port
MODEL = "qwen2.5:7b-instruct"
GPU_LOAD_WAIT_S = 20 * 60         # the model must be loaded (and 100% GPU) within this time
GPU_RECHECK_S = 300

# ---------------- paths ----------------

LOCAL_REPO = Path(__file__).resolve().parents[1]      # rsi_pilot/ on the laptop
IMAGE_REPO = "/opt/chiron/rsi_pilot"                  # rsi_pilot/ inside the image (pristine)
# rsi/sqlexec.py imports the parent repo's checker (harness/evaluator.py) from the directory
# above rsi_pilot, for the second-verifier verdict recorded on every task.
IMAGE_HARNESS = "/opt/chiron/harness"
HARNESS_FILES = ("__init__.py", "evaluator.py")
WORK_ROOT = "/tmp/chiron_work"
DATA_MOUNT = "/vol/data"
MODELS_MOUNT = "/vol/ollama"
OUT_MOUNT = "/vol/out"
ARCHIVE_NAME = "chiron_data_slim.tar.gz"
ARCHIVE_PREFIX = "Chiron/rsi_pilot/data/"
DATA_SUBDIRS = ("spider", "bird_minidev")
DATA_IN_VOLUME = f"{DATA_MOUNT}/Chiron/rsi_pilot/data"
MODELS_IN_VOLUME = f"{MODELS_MOUNT}/models"

# Not uploaded with the repo (dockerignore-style, relative to rsi_pilot/; checked against
# modal.FilePatternMatcher in tests). data/ comes from the data volume instead.
IGNORE = ["data", ".venv", "**/cache", "**/__pycache__", "**/.pytest_cache",
          "runs_v6", "runs_v7", "figures"]

# Files the run uses; a launch is refused while any of them is modified or untracked.
USED_PATTERNS = ["rsi/*", "scripts/*", "cloud/modal_ablation.py", "ablations_v5.yaml",
                 "frozen_v5*.yaml", "harness_agent.yaml", "requirements.txt",
                 "runs_v5/s*/arm_*/final.yaml", "runs_v5/s*/audit.json",
                 "runs_v5/s*/heldout_access.jsonl",
                 "tests/conftest.py", "tests/test_ablate.py", "tests/test_agent.py"]

EVAL_FILE = re.compile(r"^[a-z][a-z0-9_]*_(H|B)\.json$")
N_EVALS = 10                      # baseline + 4 variants, on H and B


class CostGuardError(RuntimeError):
    pass


class DirtyTreeError(RuntimeError):
    pass


# ---------------- pure helpers (tested offline) ----------------

def parse_seeds(arg: str) -> list[int]:
    """'all' or a comma list of run-5 seeds, e.g. '20261211,20261214'. Sorted, no duplicates."""
    arg = (arg or "").strip()
    if arg == "all":
        return list(SEEDS)
    out = []
    for part in arg.split(","):
        part = part.strip()
        if not part.isdigit() or int(part) not in SEEDS:
            raise ValueError(f"seed {part!r}: must be one of {', '.join(map(str, SEEDS))} or 'all'")
        out.append(int(part))
    if not out:
        raise ValueError("no seeds given")
    return sorted(set(out))


def seed_rate_per_s(gpu: str = GPU) -> float:
    if gpu not in GPU_PRICE_PER_S:
        raise CostGuardError(f"no price for GPU {gpu!r}; add it to GPU_PRICE_PER_S")
    return GPU_PRICE_PER_S[gpu] + SEED_CPU * CPU_CORE_PRICE_PER_S + SEED_MEM_MIB / 1024 * MEM_GIB_PRICE_PER_S


def attempt_worst_usd(minutes: float = MAX_SEED_MINUTES, gpu: str = GPU) -> float:
    """One run_seed attempt that runs into the hard timeout, startup included."""
    return (minutes + STARTUP_MINUTES) * 60 * seed_rate_per_s(gpu)


def overhead_worst_usd() -> float:
    """prepare and orchestrate at their timeouts (orchestrate is nonpreemptible: 3x CPU/memory)."""
    prep = PREP_MINUTES * 60 * (PREP_CPU * CPU_CORE_PRICE_PER_S + PREP_MEM_MIB / 1024 * MEM_GIB_PRICE_PER_S)
    orch = ORCH_MINUTES * 60 * NONPREEMPTIBLE_CPU_MEM_MULT * (
        max(ORCH_CPU, 0.125) * CPU_CORE_PRICE_PER_S + max(ORCH_MEM_MIB, 128) / 1024 * MEM_GIB_PRICE_PER_S)
    return prep + orch


def cost_plan(n_seeds: int, minutes: float = MAX_SEED_MINUTES, gpu: str = GPU,
              budget: float = BUDGET_USD) -> dict:
    per = attempt_worst_usd(minutes, gpu)
    over = overhead_worst_usd()
    first = n_seeds * per
    return {"gpu": gpu, "price_source": PRICE_SOURCE, "rate_usd_per_hour": seed_rate_per_s(gpu) * 3600,
            "minutes": minutes, "per_attempt_worst": per, "overhead_worst": over,
            "first_round_worst": first + over,
            "all_twice_worst": 2 * first + over,
            "guaranteed_retries": max(0, math.floor((budget - first - over) / per + 1e-9)),
            "budget": budget}


def check_budget(n_seeds: int, minutes: float = MAX_SEED_MINUTES, gpu: str = GPU,
                 budget: float = BUDGET_USD) -> dict:
    """Refuse a launch whose first round alone could pass the budget. Retries are admitted
    later only while they fit (retries_allowed)."""
    p = cost_plan(n_seeds, minutes, gpu, budget)
    if p["first_round_worst"] > budget + 1e-9:
        raise CostGuardError(f"worst case {p['first_round_worst']:.2f} USD for {n_seeds} seeds x "
                             f"{minutes} min exceeds the budget {budget:.2f} USD; refusing to launch")
    return p


def billed_estimate_usd(duration_s: float | None, minutes: float = MAX_SEED_MINUTES, gpu: str = GPU) -> float:
    """Conservative cost of a finished attempt: its duration plus the startup allowance, capped at
    the worst case. None (timeout, crash, unknown) counts as the worst case."""
    worst = attempt_worst_usd(minutes, gpu)
    if duration_s is None:
        return worst
    return min(worst, (duration_s + STARTUP_MINUTES * 60) * seed_rate_per_s(gpu))


def retries_allowed(spent_usd: float, n_failed: int, minutes: float = MAX_SEED_MINUTES,
                    gpu: str = GPU, budget: float = BUDGET_USD) -> int:
    """How many failed seeds may be rerun so that spent + overhead + reruns at worst case <= budget."""
    room = budget - overhead_worst_usd() - spent_usd
    k = math.floor(room / attempt_worst_usd(minutes, gpu) + 1e-9)
    return max(0, min(n_failed, k))


def format_plan(p: dict, n_seeds: int) -> str:
    return "\n".join([
        f"cost guard: {n_seeds} seeds on {p['gpu']}, {p['rate_usd_per_hour']:.4f} USD/h per seed container "
        f"(GPU + {SEED_CPU:g} cores + {SEED_MEM_MIB // 1024} GiB), prices from {p['price_source']}",
        f"  per attempt worst case ({p['minutes']} min + {STARTUP_MINUTES} min startup): {p['per_attempt_worst']:.2f} USD",
        f"  prepare + orchestrate worst case: {p['overhead_worst']:.2f} USD",
        f"  first round worst case: {p['first_round_worst']:.2f} USD (budget {p['budget']:.2f} USD)",
        f"  every seed twice at the timeout would be {p['all_twice_worst']:.2f} USD: not allowed; reruns are "
        f"admitted only while they fit, at least {p['guaranteed_retries']} even if every first attempt times out",
        f"  (the original sizing, {n_seeds} seeds x 2 attempts x 90 min, would be "
        f"{cost_plan(n_seeds, 90, p['gpu'], p['budget'])['all_twice_worst']:.2f} USD)",
    ])


def out_seed_dir(seed: int) -> str:
    return f"s{seed}"


def repo_result_paths(seed: int) -> list[str]:
    """rsi_pilot-relative paths a finished session produced (copied to the out volume)."""
    return [f"runs_v5/s{seed}/ablation", f"runs_v5/s{seed}/heldout_access.jsonl",
            f"runs_v5/s{seed}/logs", f"splits_v5_s{seed}.json"]


def out_repo_path(seed: int, rel: str) -> str:
    """Out-volume path of an rsi_pilot-relative path: s<SEED>/rsi_pilot/<rel>."""
    return str(PurePosixPath(out_seed_dir(seed)) / "rsi_pilot" / rel)


def modal_extras_rel(seed: int) -> str:
    """Where the container's own records (nvidia-smi, ollama ps, serve log, stdout) go."""
    return f"runs_v5/s{seed}/ablation_modal"


def seed_done_rel(seed: int) -> str:
    return f"runs_v5/s{seed}/ablation/SEED_DONE"


def seed_done_text(duration_s: int, now: datetime | None = None) -> str:
    """Same format as ablation_remote.sh: '<UTC time> duration_s <N>'."""
    now = now or datetime.now(timezone.utc)
    return f"{now.strftime('%Y-%m-%dT%H:%M:%SZ')} duration_s {int(duration_s)}\n"


def is_seed_done(out_root: Path, seed: int) -> bool:
    base = Path(out_root) / out_seed_dir(seed) / "rsi_pilot"
    return (base / seed_done_rel(seed)).is_file() and (base / f"runs_v5/s{seed}/ablation/ablation.json").is_file()


_PLACEMENT = re.compile(r"(\d+%(?:/\d+%)?\s+(?:CPU/GPU|GPU/CPU|GPU|CPU))")


def ollama_placement(ps_text: str, model: str = MODEL) -> str | None:
    """The PROCESSOR column of `ollama ps` for model, e.g. '100% GPU' or '23%/77% CPU/GPU';
    None when the model is not loaded."""
    for line in ps_text.splitlines():
        cols = line.split()
        if cols and cols[0] == model:
            m = _PLACEMENT.search(line)
            return " ".join(m.group(1).split()) if m else "unknown"
    return None


def fully_on_gpu(ps_text: str, model: str = MODEL) -> bool | None:
    """True if 100% GPU, False if any CPU share (or unparseable), None if not loaded yet."""
    p = ollama_placement(ps_text, model)
    if p is None:
        return None
    return p == "100% GPU"


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
    """Lines of `git status --porcelain=v1 --untracked-files=all` (paths relative to the repo root)
    that touch a file the run uses. prefix is `git rev-parse --show-prefix` of rsi_pilot."""
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
    """(HEAD commit, dirty used files). Runs git locally."""
    def g(*a):
        return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True).stdout
    commit = g("rev-parse", "HEAD").strip()
    prefix = g("rev-parse", "--show-prefix").strip()
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    porcelain = g("status", "--porcelain=v1", "--untracked-files=all")
    return commit, dirty_used_files(porcelain, prefix)


def require_clean_tree(repo: Path = LOCAL_REPO) -> str:
    commit, bad = git_state(repo)
    if bad:
        raise DirtyTreeError("uncommitted changes in files the run uses (commit them first, the image "
                             "is built from the working tree):\n  " + "\n  ".join(bad))
    return commit


def merge_plan(stage: Path, repo: Path) -> tuple[list[tuple[Path, Path]], list[str]]:
    """Files to copy from a fetched stage dir (STAGE/s<SEED>/rsi_pilot/...) into rsi_pilot/, and
    conflicts. A local file may be replaced only by an identical file or by one that extends it
    (heldout_access.jsonl, logs). Seeds without SEED_DONE and ablation.json are skipped."""
    copies, conflicts = [], []
    for seed in SEEDS:
        base = Path(stage) / out_seed_dir(seed) / "rsi_pilot"
        if not base.is_dir():
            continue
        if not is_seed_done(stage, seed):
            conflicts.append(f"s{seed}: no SEED_DONE + ablation.json in the stage, not merged")
            continue
        for src in sorted(p for p in base.rglob("*") if p.is_file()):
            dst = Path(repo) / src.relative_to(base)
            if dst.exists():
                a, b = dst.read_bytes(), src.read_bytes()
                if a == b:
                    continue
                if not b.startswith(a):
                    conflicts.append(f"{dst.relative_to(repo).as_posix()}: local file differs and is not "
                                     "a prefix of the fetched one")
                    continue
            copies.append((src, dst))
    return copies, conflicts


def merge(stage: Path, repo: Path = LOCAL_REPO) -> list[Path]:
    """Copy only after the whole plan is conflict-free. Never deletes anything."""
    copies, conflicts = merge_plan(stage, repo)
    hard = [c for c in conflicts if "not merged" not in c]
    if hard:
        raise RuntimeError("merge refused, nothing copied:\n  " + "\n  ".join(conflicts))
    for src, dst in copies:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    for c in conflicts:
        print("note:", c)
    return [d for _, d in copies]


# ---------------- Modal definitions ----------------

image = (
    modal.Image.debian_slim(python_version="3.12")
    # curl + ca-certificates + zstd: the Ollama install script's prerequisites (zstd for .tar.zst).
    # No pciutils/lshw on purpose: without them the script stops after installing the binary
    # and never tries to install NVIDIA drivers (Modal provides the driver).
    .apt_install("bash", "curl", "ca-certificates", "zstd", "sqlite3", "procps")
    .pip_install_from_requirements(str(LOCAL_REPO / "requirements.txt"))
    .run_commands(
        f"curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION={OLLAMA_VERSION} sh",
        f"ollama --version 2>&1 | grep -q '{OLLAMA_VERSION}'",
    )
    .env({"PYTHONUNBUFFERED": "1"})
    .add_local_dir(str(LOCAL_REPO), remote_path=IMAGE_REPO, ignore=IGNORE)
    .add_local_file(str(LOCAL_REPO.parent / "harness" / HARNESS_FILES[0]), f"{IMAGE_HARNESS}/{HARNESS_FILES[0]}")
    .add_local_file(str(LOCAL_REPO.parent / "harness" / HARNESS_FILES[1]), f"{IMAGE_HARNESS}/{HARNESS_FILES[1]}")
)

data_vol = modal.Volume.from_name("chiron-data", create_if_missing=True, version=2)
models_vol = modal.Volume.from_name("chiron-ollama", create_if_missing=True, version=2)
out_vol = modal.Volume.from_name("chiron-ablation-out", create_if_missing=True, version=2)

app = modal.App(APP_NAME, image=image)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ollama_env(models_dir: str) -> dict:
    env = dict(os.environ)
    env.pop("OLLAMA_FLASH_ATTENTION", None)          # run 5 did not set it
    env.update({"OLLAMA_HOST": f"127.0.0.1:{OLLAMA_PORT}", "OLLAMA_NUM_PARALLEL": str(WORKERS),
                "OLLAMA_KEEP_ALIVE": "-1", "OLLAMA_MODELS": models_dir})
    return env


def _start_ollama(models_dir: str, log_path: Path) -> subprocess.Popen:
    import urllib.request
    log = open(log_path, "ab")
    proc = subprocess.Popen(["ollama", "serve"], env=_ollama_env(models_dir), stdout=log,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{OLLAMA_PORT}/api/version", timeout=2) as r:
                ver = json.loads(r.read()).get("version", "")
            if ver != OLLAMA_VERSION:
                _kill_group(proc)
                raise RuntimeError(f"ollama server version {ver!r}, expected {OLLAMA_VERSION}")
            return proc
        except RuntimeError:
            raise
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError("ollama serve exited at startup")
            time.sleep(1)
    _kill_group(proc)
    raise RuntimeError("ollama serve did not answer /api/version within 60 s")


def _kill_group(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=20)
    except Exception:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            pass


def _run(cmd: list[str], env: dict | None = None, cwd: str | None = None) -> str:
    r = subprocess.run(cmd, env=env, cwd=cwd, capture_output=True, text=True)
    return r.stdout + r.stderr


def _copy_into(src: Path, dst: Path) -> None:
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    elif src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


TEXT_SUFFIXES = {".py", ".sh", ".yaml", ".yml", ".json", ".jsonl", ".md", ".txt", ".csv", ".toml", ".cfg", ".ini"}


def normalize_eol(root: Path) -> int:
    """Rewrite CRLF as LF in text files under root; returns the number of files changed.

    The image is built from the laptop's working copy. On Windows with core.autocrlf that copy
    has CRLF where the committed blobs have LF, and the seed-line grep in run_ablation.sh
    then fails. Normalizing reproduces the committed content."""
    crlf, lf = bytes([13, 10]), bytes([10])
    n = 0
    for p in Path(root).rglob("*"):
        if p.is_file() and not p.is_symlink() and p.suffix.lower() in TEXT_SUFFIXES:
            b = p.read_bytes()
            if crlf in b:
                p.write_bytes(b.replace(crlf, lf))
                n += 1
    return n


def _sqlite_wal_files(root: Path) -> list[str]:
    """SQLite header byte 18 is 2 for WAL databases; those cannot be read on a read-only mount."""
    bad = []
    for p in root.rglob("*.sqlite"):
        with open(p, "rb") as f:
            head = f.read(20)
        if head.startswith(b"SQLite format 3\x00") and len(head) >= 20 and head[18] == 2:
            bad.append(str(p))
    return bad


@app.function(cpu=(PREP_CPU, PREP_CPU), memory=(PREP_MEM_MIB, PREP_MEM_MIB), timeout=PREP_MINUTES * 60,
              volumes={DATA_MOUNT: data_vol, MODELS_MOUNT: models_vol, OUT_MOUNT: out_vol})
def prepare() -> dict:
    """Idempotent. Fails loudly (raises) on any problem."""
    import hashlib
    import tarfile
    rec_dir = Path(OUT_MOUNT) / "prepare"
    rec_dir.mkdir(parents=True, exist_ok=True)
    rec = {"time": _now()}
    # a. data
    data = Path(DATA_IN_VOLUME)
    marker = Path(DATA_MOUNT) / "EXTRACTED.json"
    if not (marker.is_file() and all((data / d).is_dir() for d in DATA_SUBDIRS)):
        arc = Path(DATA_MOUNT) / ARCHIVE_NAME
        if not arc.is_file():
            raise RuntimeError(f"{ARCHIVE_NAME} not in volume chiron-data; upload it first (CLOUD_RUN_MODAL.md)")
        h = hashlib.sha256()
        with open(arc, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        tmp = Path(DATA_MOUNT) / "_extract_tmp"
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir()
        with tarfile.open(arc, "r:gz") as t:
            members = t.getmembers()
            bad = [m.name for m in members if not (m.name + "/").startswith(ARCHIVE_PREFIX)
                   and m.name.rstrip("/") not in ("Chiron", "Chiron/rsi_pilot", "Chiron/rsi_pilot/data")]
            if bad:
                raise RuntimeError(f"unexpected archive members, e.g. {bad[:3]}")
            t.extractall(tmp, filter="data")
        if (Path(DATA_MOUNT) / "Chiron").exists():
            shutil.rmtree(Path(DATA_MOUNT) / "Chiron")
        (tmp / "Chiron").rename(Path(DATA_MOUNT) / "Chiron")
        tmp.rmdir()
        marker.write_text(json.dumps({"time": _now(), "archive_sha256": h.hexdigest(),
                                      "members": len(members)}, indent=1))
    for d in DATA_SUBDIRS:
        if not (data / d).is_dir():
            raise RuntimeError(f"data/{d} missing after extraction")
    wal = _sqlite_wal_files(data)
    if wal:
        # A WAL-mode database cannot be opened on the seeds' read-only mount. Switch the journal
        # mode here, where the volume is writable. This changes the header's journal flag and
        # checkpoints any pending WAL; rows and schema are untouched. The list is recorded.
        import sqlite3
        for p in wal:
            c = sqlite3.connect(p)
            mode = c.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            c.close()
            if mode.lower() != "delete":
                raise RuntimeError(f"could not switch {p} out of WAL mode (got {mode})")
        (rec_dir / "wal_converted.json").write_text(json.dumps(sorted(wal), indent=1))
        rec["wal_converted"] = len(wal)
        left = _sqlite_wal_files(data)
        if left:
            raise RuntimeError(f"still WAL after conversion: {left[:5]}")
    rec["data"] = json.loads(marker.read_text())
    data_vol.commit()
    # b. model
    Path(MODELS_IN_VOLUME).mkdir(parents=True, exist_ok=True)
    srv = _start_ollama(MODELS_IN_VOLUME, rec_dir / "ollama_serve.log")
    try:
        env = _ollama_env(MODELS_IN_VOLUME)
        pull = subprocess.run(["ollama", "pull", MODEL], env=env, capture_output=True, text=True)
        (rec_dir / "pull_student.log").write_text(pull.stdout + pull.stderr)
        if pull.returncode != 0:
            raise RuntimeError("ollama pull failed (prepare/pull_student.log in chiron-ablation-out)")
        (rec_dir / "ollama_version.txt").write_text(_run(["ollama", "--version"], env=env))
        listing = _run(["ollama", "list"], env=env)
        (rec_dir / "ollama_list.txt").write_text(listing)
        if MODEL not in listing:
            raise RuntimeError(f"{MODEL} not in ollama list after pull")
    finally:
        _kill_group(srv)
    models_vol.commit()
    # c. tests, on a writable copy of the repo
    work = Path(WORK_ROOT) / "prepare" / "rsi_pilot"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(IMAGE_REPO, work, symlinks=True)
    shutil.copytree(IMAGE_HARNESS, work.parent / "harness", dirs_exist_ok=True)
    normalize_eol(work.parent)
    t = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        "tests/test_ablate.py", "tests/test_agent.py"], cwd=work, capture_output=True, text=True)
    (rec_dir / "pytest.log").write_text(t.stdout + t.stderr)
    rec["pytest_rc"] = t.returncode
    (rec_dir / "prepare.json").write_text(json.dumps(rec, indent=1))
    out_vol.commit()
    if t.returncode != 0:
        raise RuntimeError("pytest failed in prepare (prepare/pytest.log in chiron-ablation-out)")
    return {"ok": True}


@app.function(gpu=GPU, cpu=(SEED_CPU, SEED_CPU), memory=(SEED_MEM_MIB, SEED_MEM_MIB),
              timeout=MAX_SEED_MINUTES * 60, startup_timeout=STARTUP_MINUTES * 60,
              max_containers=MAX_CONTAINERS, single_use_containers=True,
              volumes={DATA_MOUNT: data_vol.with_mount_options(read_only=True),
                       MODELS_MOUNT: models_vol.with_mount_options(read_only=True), OUT_MOUNT: out_vol})
def run_seed(seed: int) -> dict:
    """One session for one seed. Returns {seed, ok, duration_s, error, attempt, skipped};
    never an accuracy or a pass count."""
    t0 = time.time()
    res = {"seed": seed, "ok": False, "duration_s": 0, "error": "", "attempt": 0, "skipped": False}
    out_root = Path(OUT_MOUNT)
    sdir = out_root / out_seed_dir(seed)
    if is_seed_done(out_root, seed):
        res.update(ok=True, skipped=True)
        return res
    starts = sdir / "starts"
    starts.mkdir(parents=True, exist_ok=True)
    n_prev = len(list(starts.glob("*.json")))
    if n_prev >= MAX_STARTS_PER_SEED:
        res["error"] = f"start cap reached ({n_prev} starts recorded)"
        return res
    k = n_prev + 1
    res["attempt"] = k
    (starts / f"{k:02d}.json").write_text(json.dumps(
        {"time": _now(), "attempt": k, "task": os.environ.get("MODAL_TASK_ID", "")}))
    att = sdir / "attempts" / f"{k:02d}"
    att.mkdir(parents=True, exist_ok=True)
    out_vol.commit()
    print(f"seed {seed} attempt {k} start", flush=True)

    srv = proc = None
    work = None
    try:
        # GPU
        smi = _run(["nvidia-smi"])
        (att / "nvidia_smi.txt").write_text(smi)
        q = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]).strip()
        (att / "nvidia_smi_query.txt").write_text(q)
        want_name, want_mib = EXPECTED_GPU[GPU]
        first = q.splitlines()[0] if q else ""
        try:
            name, mem = [x.strip() for x in first.split(",")[:2]]
            ok_gpu = want_name in name and int(float(mem)) >= want_mib
        except ValueError:
            ok_gpu = False
        if not ok_gpu:
            raise RuntimeError(f"nvidia-smi shows {first!r}, expected {want_name} with >= {want_mib} MiB")
        # writable repo copy: the image copy stays pristine, so every attempt starts from the commit
        work = Path(WORK_ROOT) / f"s{seed}_a{k}" / "rsi_pilot"
        if work.parent.exists():
            shutil.rmtree(work.parent)
        shutil.copytree(IMAGE_REPO, work, symlinks=True)
        shutil.copytree(IMAGE_HARNESS, work.parent / "harness")
        normalize_eol(work.parent)
        if (work / f"runs_v5/s{seed}/ablation").exists():
            raise RuntimeError("the uploaded repo already has an ablation dir for this seed")
        # Copy the data to the container's local disk instead of reading it through the volume
        # mount. Gold and predicted queries run under a 30 s timeout (frozen eval settings); on
        # the network mount some BIRD gold queries exceeded it, which changed which tasks count
        # as eligible when the splits are regenerated (first smoke attempt, 2026-11-27).
        shutil.copytree(DATA_IN_VOLUME, work / "data")
        for d in DATA_SUBDIRS:
            if not (work / "data" / d).is_dir():
                raise RuntimeError(f"data/{d} missing in volume chiron-data (run prepare)")
        # model on local disk: the shared volume stays read-only for all six containers
        free_gb = shutil.disk_usage("/tmp").free / 1e9
        if free_gb < 15:
            raise RuntimeError(f"only {free_gb:.0f} GB free on /tmp")
        models = Path("/tmp/ollama_models")
        if models.exists():
            shutil.rmtree(models)
        shutil.copytree(MODELS_IN_VOLUME, models)
        srv = _start_ollama(str(models), att / "ollama_serve.log")
        env_o = _ollama_env(str(models))
        (att / "ollama_version.txt").write_text(_run(["ollama", "--version"], env=env_o))
        (att / "ollama_list.txt").write_text(_run(["ollama", "list"], env=env_o))
        # the session; its stdout goes to the out volume only
        env = dict(os.environ)
        env.pop("OLLAMA_FLASH_ATTENTION", None)
        env.update({"PY": sys.executable, "RSI_OLLAMA_SERVERS": f"http://localhost:{OLLAMA_PORT}"})
        stdout = open(att / "seed_stdout.log", "ab")
        proc = subprocess.Popen(["bash", "scripts/run_ablation.sh", str(seed), str(WORKERS)], cwd=work,
                                env=env, stdout=stdout, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True)
        gpu_ok = None
        last_check = last_beat = 0.0
        abl = work / f"runs_v5/s{seed}/ablation"
        while proc.poll() is None:
            now = time.time()
            el = now - t0
            if gpu_ok is None or now - last_check >= GPU_RECHECK_S:
                ps = _run(["ollama", "ps"], env=env_o)
                state = fully_on_gpu(ps, MODEL)
                if state is not None:
                    with open(att / "ollama_ps.txt", "a") as f:
                        f.write(f"--- {_now()}\n{ps}")
                    last_check = now
                    if state is False:
                        raise RuntimeError(f"model not 100% on GPU ({ollama_placement(ps, MODEL)}); "
                                           "partial CPU placement changed outputs in run 4")
                    gpu_ok = True
                elif gpu_ok is None and el > GPU_LOAD_WAIT_S:
                    raise RuntimeError(f"model not loaded after {GPU_LOAD_WAIT_S // 60} min")
            if now - last_beat >= 60:
                done = sorted(p.name for p in abl.glob("*.json") if EVAL_FILE.match(p.name)) if abl.is_dir() else []
                (sdir / "PROGRESS").write_text(json.dumps({
                    "time": _now(), "attempt": k, "elapsed_min": round(el / 60, 1),
                    "evals_done": f"{len(done)}/{N_EVALS}", "gpu_verified": bool(gpu_ok)}) + "\n")
                last_beat = now
            if el > MAX_SEED_MINUTES * 60 - SOFT_MARGIN_S:
                raise RuntimeError(f"soft deadline: {MAX_SEED_MINUTES} min timeout is near")
            time.sleep(5)
        rc = proc.returncode
        stdout.close()
        if rc != 0 or not (abl / "ablation.json").is_file():
            raise RuntimeError(f"scripts/run_ablation.sh exit code {rc}"
                               + ("" if (abl / "ablation.json").is_file() else ", no ablation.json"))
        if not gpu_ok:
            raise RuntimeError("the model was never seen in `ollama ps`; placement unverified")
        # success: results at their rsi_pilot-relative paths
        dur = int(time.time() - t0)
        base = sdir / "rsi_pilot"
        if base.exists():
            shutil.rmtree(base)
        for rel in repo_result_paths(seed):
            _copy_into(work / rel, base / rel)
        _copy_into(att, base / modal_extras_rel(seed))
        (base / seed_done_rel(seed)).write_text(seed_done_text(dur))
        out_vol.commit()
        res.update(ok=True, duration_s=dur)
        print(f"seed {seed} attempt {k} done in {dur} s", flush=True)
    except Exception as e:  # noqa: BLE001  (error text carries no result numbers)
        res["error"] = f"{type(e).__name__}: {e}"[:500]
        res["duration_s"] = int(time.time() - t0)
        print(f"seed {seed} attempt {k} failed: {res['error']}", flush=True)
        _kill_group(proc)
        if work is not None and (work / f"runs_v5/s{seed}/logs").is_dir():
            _copy_into(work / f"runs_v5/s{seed}/logs", att / "logs")
        (att / "FAILED").write_text(res["error"] + "\n")
        out_vol.commit()
    finally:
        _kill_group(proc)
        _kill_group(srv)
    return res


@app.function(cpu=(ORCH_CPU, ORCH_CPU), memory=(ORCH_MEM_MIB, ORCH_MEM_MIB), timeout=ORCH_MINUTES * 60,
              nonpreemptible=True, volumes={OUT_MOUNT: out_vol})
def orchestrate(seeds: list[int], git_commit: str) -> list[dict]:
    """Server side, so the laptop may sleep: prepare, all seeds at once, then one rerun round for
    failed seeds, admitted only while the budget holds. Writes ABLATION_DONE (no numbers)."""
    run_dir = Path(OUT_MOUNT) / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    plan = check_budget(len(seeds))
    (run_dir / f"launch_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json").write_text(
        json.dumps({"time": _now(), "git_commit": git_commit, "seeds": seeds, "gpu": GPU,
                    "plan": plan, "max_seed_minutes": MAX_SEED_MINUTES}, indent=1))
    (run_dir / "git_commit.txt").write_text(git_commit + "\n")
    out_vol.commit()
    prepare.remote()

    def round_(ss: list[int]) -> dict[int, dict]:
        calls = {s: run_seed.spawn(s) for s in ss}
        got = {}
        for s, c in calls.items():
            try:
                got[s] = c.get()
            except Exception as e:  # noqa: BLE001  (timeout, crash, preemption limit)
                got[s] = {"seed": s, "ok": False, "duration_s": None, "error": f"{type(e).__name__}: {e}"[:500],
                          "attempt": 0, "skipped": False}
        return got

    results = round_(seeds)
    spent = sum(0.0 if r.get("skipped") else billed_estimate_usd(r.get("duration_s")) for r in results.values())
    failed = [s for s in seeds if not results[s]["ok"]]
    k = retries_allowed(spent, len(failed))
    rerun, held = failed[:k], failed[k:]
    for s in held:
        results[s]["error"] += " | no rerun: budget"
    if rerun:
        again = round_(rerun)
        for s, r in again.items():
            r["error"] = (r["error"] + f" | first attempt: {results[s]['error']}") if not r["ok"] else r["error"]
            results[s] = r
    ok = [s for s in seeds if results[s]["ok"]]
    bad = [s for s in seeds if not results[s]["ok"]]
    (Path(OUT_MOUNT) / "ABLATION_DONE").write_text(
        f"finished: {' '.join(map(str, ok)) or 'none'}\nfailed: {' '.join(map(str, bad)) or 'none'}\n"
        f"time: {_now()}\ngit_commit: {git_commit}\n")
    (run_dir / "results.json").write_text(json.dumps([results[s] for s in seeds], indent=1))
    out_vol.commit()
    return [results[s] for s in seeds]


def summary_lines(results: list[dict]) -> list[str]:
    lines = []
    for r in results:
        mins = "-" if r.get("duration_s") is None else f"{r['duration_s'] / 60:.1f}"
        lines.append(f"seed {r['seed']} ok={r['ok']} minutes={mins}"
                     + (" (already done)" if r.get("skipped") else "")
                     + (f" error={r['error']}" if r.get("error") else ""))
    ok = [str(r["seed"]) for r in results if r["ok"]]
    bad = [str(r["seed"]) for r in results if not r["ok"]]
    lines.append(f"ABLATION_DONE finished: {' '.join(ok) or 'none'} failed: {' '.join(bad) or 'none'}")
    return lines


@app.local_entrypoint()
def main(seeds: str = "all"):
    ss = parse_seeds(seeds)
    commit = require_clean_tree()
    plan = check_budget(len(ss))
    print(format_plan(plan, len(ss)))
    print(f"git commit {commit}; seeds {' '.join(map(str, ss))}; GPU {GPU}; timeout {MAX_SEED_MINUTES} min")
    call = orchestrate.spawn(ss, commit)
    print(f"orchestrate call {call.object_id} (runs server side; with --detach the laptop may sleep)", flush=True)
    for line in summary_lines(call.get()):
        print(line)


# ---------------- offline CLI ----------------

def _cli(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="cloud/modal_ablation.py", description="offline helpers, no Modal contact")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="print the cost guard and check the tree")
    p.add_argument("--seeds", default="all")
    m = sub.add_parser("merge", help="copy fetched results (STAGE/s<SEED>/rsi_pilot/...) into rsi_pilot/")
    m.add_argument("stage")
    a = ap.parse_args(argv)
    if a.cmd == "plan":
        ss = parse_seeds(a.seeds)
        print(format_plan(check_budget(len(ss)), len(ss)))
        commit, bad = git_state()
        print(f"git commit {commit}")
        print("tree: clean for the run" if not bad else "tree: DIRTY, launch would be refused:\n  " + "\n  ".join(bad))
        return 0 if not bad else 1
    files = merge(Path(a.stage))
    print(f"merged {len(files)} files into {LOCAL_REPO}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
