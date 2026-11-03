"""Run 5 agent harness: plumbing tests with a scripted fake student."""
import json
import os
import subprocess
import sys
from pathlib import Path

from rsi.agent import AGENT_FIELDS, parse_action, run_task
from rsi.config import ROOT, load_yaml
from rsi.student import Completion

EVAL = {"exec_timeout_s": 5, "max_result_rows": 1000, "keep_distinct": True,
        "verifier": "spider_official", "bird_include_evidence": True}


def base():
    h = load_yaml(ROOT / "harness_agent.yaml")
    assert set(h) == set(AGENT_FIELDS)
    return h


class Script:
    def __init__(self, actions):
        self.actions = list(actions)
        self.seen = []

    def __call__(self, messages):
        self.seen.append(messages[-1]["content"])
        a = self.actions.pop(0)
        return Completion(a if isinstance(a, str) else json.dumps(a), 10, 5, 0.01)


def test_parse_action():
    assert parse_action('ok {"tool": "describe", "arg": "t"} done') == {"tool": "describe", "arg": "t"}
    assert parse_action("no json here") is None


def test_agent_explores_then_submits(tasks):
    t = tasks["E"][0]  # count task: SELECT count(*) FROM evo_band
    s = Script([{"tool": "list_tables"}, {"tool": "describe", "arg": "evo_band"},
                {"tool": "run_sql", "arg": "SELECT count(*) FROM evo_band"},
                {"tool": "submit", "arg": "SELECT count(*) FROM evo_band;"}])
    r = run_task(base(), t, s, None, EVAL)
    assert r["pass"] and r["ended"] == "submitted" and r["n_attempts"] == 4
    assert "evo_album" in s.seen[1] and "CREATE TABLE" in s.seen[2] and "3" in s.seen[3]


def test_agent_out_of_steps_scores_last_query(tasks):
    t = tasks["E"][0]
    h = {**base(), "max_steps": 2}
    s = Script(["thinking...", {"tool": "run_sql", "arg": "SELECT count(*) FROM evo_band"}])
    r = run_task(h, t, s, None, EVAL)
    assert r["ended"] == "out_of_steps" and r["pass"] and "Error: reply with exactly one JSON" in s.seen[1]


def test_agent_verify_before_submit(tasks):
    t = tasks["E"][0]
    h = {**base(), "verify_before_submit": True}
    s = Script([{"tool": "submit", "arg": "SELECT 1"}, {"tool": "submit", "arg": "SELECT count(*) FROM evo_band"},
                {"tool": "confirm"}])
    r = run_task(h, t, s, None, EVAL)
    assert r["pass"] and r["pred_sql"] == "SELECT count(*) FROM evo_band" and "Does this answer" in s.seen[1]


def test_agent_kind_switch_and_random_edits():
    code = ("import random; from rsi.config import load_yaml, BASELINE; from rsi.harness import validate, "
            "EDITABLE_FIELDS, run_task, diff_fields; from rsi.edits import random_edit, placebo_prompts; "
            "h = validate(load_yaml(BASELINE)); assert 'tool_guide' in EDITABLE_FIELDS; "
            "assert run_task.__module__ == 'rsi.agent'; rng = random.Random(0); "
            "[validate({**h, **random_edit(h, rng, 3)}) for _ in range(300)]; "
            "assert all(p != h['system_prompt'] for p in placebo_prompts()); print('ok')")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                         env={**os.environ, "RSI_HARNESS_KIND": "agent"})
    assert out.stdout.strip() == "ok", out.stderr
