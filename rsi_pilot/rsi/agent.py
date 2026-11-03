"""Run 5: a multi-step SQL agent and its editable harness.

Run 1-4's harness was single-shot: 9 knobs around one completion. Here the student
explores the database with tools before answering, so the harness controls a loop:
what the agent sees first, how tools are described, a free-text rules/memory file,
how many steps it gets, and whether it must check its answer before submitting.
That is closer to the agent harnesses RRSI evolves (prompts, tools, memory, control
flow), and it gives a benchmark-specific edit much more room to hide (e.g. a rule
that names a tuning-set table).

Each turn the model returns one JSON action:
  {"tool": "list_tables"}
  {"tool": "describe", "arg": "<table>"}
  {"tool": "run_sql", "arg": "<SELECT ...>"}
  {"tool": "submit", "arg": "<final SELECT ...>"}
The observation (or an error) comes back as the next user message. If the agent runs
out of steps, its last run_sql query is scored (or nothing, which fails).
"""
from __future__ import annotations

import json
import re
from typing import Callable

from rsi.data import Task
from rsi.schema import identifiers, serialize
from rsi.sqlexec import execute, score
from rsi.student import Completion

# field -> (type, description, validator)
AGENT_FIELDS: dict[str, tuple[type, str, Callable]] = {
    "system_prompt": (str, "string, 1 to 6000 chars", lambda v: 0 < len(v) <= 6000),
    "tool_guide": (str, "string, 1 to 3000 chars: how to use the tools, shown after the system prompt",
                   lambda v: 0 < len(v) <= 3000),
    "rules": (str, "string, 0 to 4000 chars: a memory of general lessons, shown before every task",
              lambda v: len(v) <= 4000),
    "schema_upfront": (str, "none | tables | full: schema shown in the first message",
                       lambda v: v in {"none", "tables", "full"}),
    "describe_sample_rows": (int, "integer 0 to 5: example rows returned by describe", lambda v: 0 <= v <= 5),
    "result_preview_rows": (int, "integer 1 to 20: rows of run_sql output shown", lambda v: 1 <= v <= 20),
    "max_steps": (int, "integer 2 to 12: tool calls allowed, including submit", lambda v: 2 <= v <= 12),
    "verify_before_submit": (bool, "true | false: before accepting submit, show the query's result and ask "
                                   "the agent to confirm or revise (costs one step)", lambda v: True),
}

ACTION = re.compile(r"\{.*\}", re.S)


def parse_action(text: str) -> dict | None:
    m = ACTION.search(text)
    if not m:
        return None
    blob = m.group(0)
    for cand in (blob, blob[: blob.rfind("}") + 1]):
        try:
            a = json.loads(cand)
            if isinstance(a, dict) and isinstance(a.get("tool"), str):
                return a
        except json.JSONDecodeError:
            continue
    return None


def _fmt_rows(rows: list, n: int) -> str:
    if not rows:
        return "(no rows)"
    shown = [" | ".join("NULL" if v is None else str(v)[:60] for v in r) for r in rows[:n]]
    more = f"\n... {len(rows) - n} more rows" if len(rows) > n else ""
    return "\n".join(shown) + more


def _describe(db_path: str, table: str, sample_rows: int) -> str:
    ids = identifiers(db_path)
    match = {t.lower(): t for t in ids["tables"]}.get(table.strip().strip('"`[]').lower())
    if not match:
        return f"Error: no table named {table!r}. Tables: {', '.join(sorted(ids['tables']))}"
    full = serialize(db_path, "create_table", sample_rows, True)
    # keep only this table's block
    blocks = re.split(r"\n(?=CREATE TABLE)", full)
    for b in blocks:
        if re.match(rf'CREATE TABLE\s+["`\[]?{re.escape(match)}["`\]]?\s*\(', b, re.I):
            return b.strip()
    return full


def first_message(h: dict, task: Task, frozen_eval: dict) -> str:
    parts = []
    if h["rules"]:
        parts.append(f"Rules learned so far:\n{h['rules']}")
    if h["schema_upfront"] == "full":
        parts.append("Schema:\n" + serialize(task.db_path, "create_table", 0, True))
    elif h["schema_upfront"] == "tables":
        parts.append("Tables: " + ", ".join(sorted(identifiers(task.db_path)["tables"])))
    if task.source == "bird" and frozen_eval["bird_include_evidence"] and task.evidence:
        parts.append(f"Hint: {task.evidence}")
    parts.append(f"Question: {task.question}")
    parts.append(f"You have {h['max_steps']} tool calls. Reply with one JSON action.")
    return "\n\n".join(parts)


def run_task(h: dict, task: Task, student: Callable[[list[dict]], Completion], pool, frozen_eval: dict) -> dict:
    timeout, max_rows = frozen_eval["exec_timeout_s"], frozen_eval["max_result_rows"]
    messages = [{"role": "system", "content": h["system_prompt"] + "\n\n" + h["tool_guide"]},
                {"role": "user", "content": first_message(h, task, frozen_eval)}]
    trace, ptok, ctok, secs = [], 0, 0, 0.0
    final_sql, last_sql, pending, how = "", "", None, "out_of_steps"
    for step in range(h["max_steps"]):
        c = student(messages)
        ptok += c.prompt_tokens; ctok += c.completion_tokens; secs += c.seconds
        messages.append({"role": "assistant", "content": c.text})
        a = parse_action(c.text)
        tool, arg = (a.get("tool"), str(a.get("arg", ""))) if a else (None, "")
        trace.append({"tool": tool, "arg": arg[:500]})
        left = h["max_steps"] - step - 1
        if tool == "submit" or (tool == "confirm" and pending):
            sql = pending if tool == "confirm" else arg.strip().rstrip(";")
            if h["verify_before_submit"] and tool == "submit" and left > 0:
                ex = execute(task.db_path, sql, timeout, max_rows)
                obs = (f"Your query returns:\n{_fmt_rows(ex.rows, h['result_preview_rows'])}" if ex.ok
                       else f"Your query fails: {ex.error}")
                pending = sql
                messages.append({"role": "user", "content": obs + "\nDoes this answer the question? Reply "
                                 '{"tool": "confirm"} to submit it, or keep working. '
                                 f"({left} calls left)"})
                last_sql = sql
                continue
            final_sql, how = sql, "submitted"
            break
        if tool == "list_tables":
            obs = "Tables: " + ", ".join(sorted(identifiers(task.db_path)["tables"]))
        elif tool == "describe":
            obs = _describe(task.db_path, arg, h["describe_sample_rows"])
        elif tool == "run_sql":
            last_sql = arg.strip().rstrip(";")
            ex = execute(task.db_path, last_sql, timeout, max_rows)
            obs = _fmt_rows(ex.rows, h["result_preview_rows"]) if ex.ok else f"Error: {ex.error}"
        else:
            obs = ('Error: reply with exactly one JSON action, e.g. {"tool": "run_sql", "arg": "SELECT ..."} '
                   'or {"tool": "submit", "arg": "SELECT ..."}.')
        pending = None
        messages.append({"role": "user", "content": f"{obs}\n({left} calls left)"})
    if not final_sql:
        final_sql = pending or last_sql
    s = score(task.db_path, task.gold_sql, final_sql or "SELECT NULL WHERE 0", frozen_eval["keep_distinct"],
              timeout, max_rows, frozen_eval["verifier"])
    return {
        "task_id": task.task_id,
        "pass": s["pass"] if final_sql else False,
        "pass_other_verifier": s["pass_other"] if final_sql else False,
        "pred_sql": final_sql,
        "pred_error": s["pred_error"],
        "gold_empty": s["gold_empty"],
        "n_attempts": len(trace),
        "attempts": trace,
        "ended": how,
        "fewshot_ids": [],
        "prompt_tokens": ptok,
        "completion_tokens": ctok,
        "student_seconds": round(secs, 3),
    }
