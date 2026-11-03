"""Student model client (Ollama chat API). Deterministic settings come from frozen.yaml."""
from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass
class Completion:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0


class Student(Protocol):
    def __call__(self, messages: list[dict]) -> Completion: ...


class OllamaStudent:
    def __init__(self, cfg: dict):
        self.cfg = cfg

    def __call__(self, messages: list[dict]) -> Completion:
        c = self.cfg
        body = {
            "model": c["model"],
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": c["temperature"],
                "seed": c["seed"],
                "num_ctx": c["num_ctx"],
                "num_predict": c["num_predict"],
            },
        }
        req = urllib.request.Request(
            c["base_url"].rstrip("/") + "/api/chat",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        t0 = time.monotonic()

        def call():
            with urllib.request.urlopen(req, timeout=c["request_timeout_s"]) as r:
                return json.loads(r.read())

        if c.get("gpu_lock"):
            from rsi.gpu import student_call
            out = student_call(c["base_url"], c["model"], call)
        else:
            out = call()
        return Completion(
            text=out["message"]["content"],
            prompt_tokens=out.get("prompt_eval_count", 0),
            completion_tokens=out.get("eval_count", 0),
            seconds=time.monotonic() - t0,
        )


def make_student(cfg: dict) -> Callable[[list[dict]], Completion]:
    if cfg["provider"] == "ollama":
        return OllamaStudent(cfg)
    raise ValueError(f"unknown student provider {cfg['provider']}")
