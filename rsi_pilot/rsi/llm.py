"""Proposer/critic LLM client.

anthropic: official SDK, beta endpoint so the server-side refusal fallback
  (`fallbacks="default"`) is on. Thinking is always on for claude-opus-5-5;
  depth is set with output_config.effort.
openai_compatible: for non-Claude models via an OpenAI-style endpoint
  (e.g. OpenRouter). Plain HTTP; set base_url and api_key_env in frozen.yaml.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class LLMReply:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


class AnthropicLLM:
    def __init__(self, cfg: dict):
        import anthropic
        self.anthropic = anthropic
        self.client = anthropic.Anthropic(max_retries=4, timeout=600)
        self.cfg = cfg

    def __call__(self, system: str, user: str, max_tokens: int = 16000) -> LLMReply:
        a = self.anthropic
        try:
            r = self.client.beta.messages.create(
                model=self.cfg["model"],
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": self.cfg.get("effort", "high")},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except a.BadRequestError as e:
            raise RuntimeError(f"proposer request rejected: {e.message}") from e
        except a.AuthenticationError as e:
            raise RuntimeError("proposer auth failed; set ANTHROPIC_API_KEY or run `ant auth login`") from e
        if r.stop_reason == "refusal":
            cat = getattr(r.stop_details, "category", None) if r.stop_details else None
            raise RuntimeError(f"proposer refused (category={cat})")
        if r.stop_reason == "max_tokens":
            raise RuntimeError("proposer hit max_tokens; raise max_tokens")
        text = "".join(b.text for b in r.content if b.type == "text")
        return LLMReply(text, r.usage.input_tokens, r.usage.output_tokens, r.model)


class OpenAICompatibleLLM:
    def __init__(self, cfg: dict):
        if not cfg.get("base_url") or not cfg.get("api_key_env"):
            raise ValueError("openai_compatible proposer needs base_url and api_key_env in frozen.yaml")
        key = os.environ.get(cfg["api_key_env"])
        if not key:
            raise RuntimeError(f"environment variable {cfg['api_key_env']} is not set")
        self.cfg, self.key = cfg, key

    def __call__(self, system: str, user: str, max_tokens: int = 16000) -> LLMReply:
        body = {"model": self.cfg["model"], "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        req = urllib.request.Request(
            self.cfg["base_url"].rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.key}"})
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=600) as r:
                    out = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                    time.sleep(2 ** (attempt + 1)); continue
                raise
        u = out.get("usage", {})
        return LLMReply(out["choices"][0]["message"]["content"], u.get("prompt_tokens", 0),
                        u.get("completion_tokens", 0), out.get("model", ""))


def make_llm(cfg: dict):
    if cfg["provider"] == "anthropic":
        return AnthropicLLM(cfg)
    if cfg["provider"] == "openai_compatible":
        return OpenAICompatibleLLM(cfg)
    raise ValueError(f"unknown proposer provider {cfg['provider']}")


def parse_json(text: str):
    """Pull the last JSON object or array out of a model reply."""
    import re
    fenced = re.findall(r"```(?:json)?\s*(.*?)```", text, re.S)
    for cand in reversed(fenced + [text]):
        cand = cand.strip()
        for opener, closer in (("[", "]"), ("{", "}")):
            i, j = cand.find(opener), cand.rfind(closer)
            if i != -1 and j > i:
                try:
                    return json.loads(cand[i:j + 1])
                except json.JSONDecodeError:
                    continue
    raise ValueError("no JSON found in reply")
