"""Keep student scoring deterministic when a large proposer shares the GPU (run 4).

Found while preparing run 4: when the 32B proposer is resident, Ollama loads the 1.5B
student partly on the CPU, and CPU/GPU placement changes its greedy outputs (the same
harness scored 36 and 39 of 100). Fix, across all processes of a run:
- a file lock: student calls hold it shared; proposer/critic calls hold it exclusive;
- big-model calls first unload the student and send keep_alive=0, then wait until the
  big model has left the GPU before releasing the lock;
- before each student call, check that the student is either not loaded (it will then
  load onto an empty GPU) or fully in VRAM; otherwise unload it under the exclusive lock.
Enabled by `gpu_lock: true` in frozen.yaml; runs 1-3 are unchanged.
"""
from __future__ import annotations

import fcntl
import json
import os
import time
import urllib.request
from contextlib import contextmanager

LOCK_PATH = os.environ.get("RSI_GPU_LOCK", "/tmp/rsi_gpu.lock")


@contextmanager
def gpu_lock(exclusive: bool):
    """Readers-writer lock across processes. A turnstile lock stops a stream of student
    calls (shared) from starving a waiting proposer call (exclusive)."""
    with open(LOCK_PATH + ".turnstile", "a+") as t, open(LOCK_PATH, "a+") as f:
        fcntl.flock(t, fcntl.LOCK_EX)
        if not exclusive:
            fcntl.flock(t, fcntl.LOCK_UN)
        fcntl.flock(f, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
            if exclusive:
                fcntl.flock(t, fcntl.LOCK_UN)


def _post(base_url: str, path: str, body: dict | None = None, timeout: float = 600) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base_url.rstrip("/") + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def loaded(base_url: str) -> dict[str, dict]:
    return {m["name"]: m for m in _post(base_url, "/api/ps").get("models", [])}


def unload(base_url: str, model: str, wait_s: float = 120) -> None:
    _post(base_url, "/api/generate", {"model": model, "keep_alive": 0})
    t0 = time.monotonic()
    while model in loaded(base_url):
        if time.monotonic() - t0 > wait_s:
            raise RuntimeError(f"{model} did not unload within {wait_s}s")
        time.sleep(0.2)


def student_ready(base_url: str, model: str) -> bool:
    """True if the student is not loaded or is loaded fully in VRAM."""
    m = loaded(base_url).get(model)
    return m is None or m.get("size_vram", 0) >= m.get("size", 1)


def fix_placement(base_url: str, model: str) -> None:
    with gpu_lock(exclusive=True):
        if not student_ready(base_url, model):
            for name in loaded(base_url):
                unload(base_url, name)


def student_call(base_url: str, model: str, call):
    """Run `call()` under the shared lock with the student on an otherwise empty GPU or fully
    in VRAM; if the student ended up partly on the CPU, discard the result and retry."""
    for _ in range(5):
        with gpu_lock(exclusive=False):
            if student_ready(base_url, model):
                out = call()
                if student_ready(base_url, model):
                    return out
        fix_placement(base_url, model)
    raise RuntimeError(f"could not keep {model} fully on the GPU")


def big_model_call(base_url: str, call):
    """Run `call()` (which must send keep_alive=0) under the exclusive lock, on an empty GPU,
    and wait until the model has left the GPU before releasing the lock."""
    with gpu_lock(exclusive=True):
        for name in loaded(base_url):
            unload(base_url, name)
        out = call()
        for name in loaded(base_url):
            unload(base_url, name)
        return out
