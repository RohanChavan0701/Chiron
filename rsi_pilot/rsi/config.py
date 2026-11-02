"""Paths and loading for frozen settings and harness files."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _env_path(var: str, default: Path) -> Path:
    """Path from an environment variable (relative to ROOT), else the default.

    Lets a second run (e.g. run 2) use its own frozen settings, splits and output
    directory without touching run 1's files:
    RSI_FROZEN=frozen_v2.yaml RSI_SPLITS=splits_v2.json RSI_RUNS=runs_v2
    """
    v = os.environ.get(var)
    if not v:
        return default
    p = Path(v)
    return p if p.is_absolute() else ROOT / p


RUNS = _env_path("RSI_RUNS", ROOT / "runs")
FROZEN = _env_path("RSI_FROZEN", ROOT / "frozen.yaml")
SPLITS = _env_path("RSI_SPLITS", ROOT / "splits.json")


def load_yaml(path: str | Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def dump_yaml(obj: dict, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump(obj, f, sort_keys=False, allow_unicode=True)


def frozen(path: str | Path | None = None) -> dict:
    return load_yaml(path or FROZEN)


def resolve(p: str | Path) -> Path:
    p = Path(p)
    return p if p.is_absolute() else ROOT / p


def stable_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:16]


def append_jsonl(path: str | Path, rec: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def read_jsonl(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
