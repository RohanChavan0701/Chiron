"""The editable harness: validation, prompt building, and the per-task attempt loop."""
from __future__ import annotations

import re
from typing import Callable

from rsi.config import HARNESS_KIND, stable_hash
from rsi.data import Task
from rsi.fewshot import FewShotPool
from rsi.schema import serialize
from rsi.sqlexec import execute, score
from rsi.student import Completion

# field -> (type, validator description, validator)
EDITABLE_FIELDS: dict[str, tuple[type, str, Callable]] = {
    "system_prompt": (str, "string, 1 to 4000 chars", lambda v: 0 < len(v) <= 4000),
    "schema_format": (str, "create_table | compact", lambda v: v in {"create_table", "compact"}),
    "sample_rows": (int, "integer 0 to 5", lambda v: 0 <= v <= 5),
    "include_foreign_keys": (bool, "true | false", lambda v: True),
    "fewshot_k": (int, "integer 0 to 8", lambda v: 0 <= v <= 8),
    "fewshot_rule": (str, "fixed | lexical", lambda v: v in {"fixed", "lexical"}),
    "max_retries": (int, "integer 0 to 3", lambda v: 0 <= v <= 3),
    "feed_execution_errors": (bool, "true | false", lambda v: True),
    "instructions_suffix": (str, "string, 0 to 2000 chars", lambda v: len(v) <= 2000),
}


class HarnessError(ValueError):
    pass


def validate(h: dict) -> dict:
    unknown = set(h) - set(EDITABLE_FIELDS)
    missing = set(EDITABLE_FIELDS) - set(h)
    if unknown or missing:
        raise HarnessError(f"unknown fields {sorted(unknown)}, missing fields {sorted(missing)}")
    for k, (typ, desc, ok) in EDITABLE_FIELDS.items():
        v = h[k]
        if typ is int and isinstance(v, bool):
            raise HarnessError(f"{k}: expected {desc}, got bool")
        if not isinstance(v, typ) or not ok(v):
            raise HarnessError(f"{k}: expected {desc}, got {v!r}")
    return h


def harness_id(h: dict) -> str:
    return stable_hash(h)


def diff_fields(a: dict, b: dict) -> list[str]:
    return [k for k in EDITABLE_FIELDS if a.get(k) != b.get(k)]


SQL_BLOCK = re.compile(r"```(?:sql|sqlite)?\s*(.*?)```", re.S | re.I)


def extract_sql(text: str) -> str:
    m = SQL_BLOCK.findall(text)
    sql = m[-1] if m else text
    sql = sql.strip().rstrip(";").strip()
    # if the model wrote prose before SELECT/WITH without a code block, cut it
    if not m:
        k = re.search(r"\b(with|select)\b", sql, re.I)
        if k:
            sql = sql[k.start():]
    return sql


def _user_message(h: dict, task: Task, frozen_eval: dict, shots: list[Task]) -> str:
    schema = serialize(task.db_path, h["schema_format"], h["sample_rows"], h["include_foreign_keys"])
    parts = []
    for s in shots:
        s_schema = serialize(s.db_path, h["schema_format"], 0, h["include_foreign_keys"])
        parts.append(f"### Example\nSchema:\n{s_schema}\n\nQuestion: {s.question}\n```sql\n{s.gold_sql}\n```")
    parts.append(f"### Task\nSchema:\n{schema}")
    if task.source == "bird" and frozen_eval["bird_include_evidence"] and task.evidence:
        parts.append(f"Hint: {task.evidence}")
    parts.append(f"Question: {task.question}")
    if h["instructions_suffix"]:
        parts.append(h["instructions_suffix"])
    return "\n\n".join(parts)


def run_task(h: dict, task: Task, student: Callable[[list[dict]], Completion],
             pool: FewShotPool | None, frozen_eval: dict) -> dict:
    shots = pool.select(task, h["fewshot_k"], h["fewshot_rule"]) if (pool and h["fewshot_k"]) else []
    messages = [{"role": "system", "content": h["system_prompt"]},
                {"role": "user", "content": _user_message(h, task, frozen_eval, shots)}]
    attempts, ptok, ctok, secs = [], 0, 0, 0.0
    sql = ""
    for attempt in range(1 + h["max_retries"]):
        c = student(messages)
        ptok += c.prompt_tokens; ctok += c.completion_tokens; secs += c.seconds
        sql = extract_sql(c.text)
        ex = execute(task.db_path, sql, frozen_eval["exec_timeout_s"], frozen_eval["max_result_rows"])
        attempts.append({"sql": sql, "error": ex.error})
        if ex.ok or attempt == h["max_retries"]:
            break
        messages.append({"role": "assistant", "content": c.text})
        fb = (f"That query failed with this SQLite error: {ex.error}\nFix it." if h["feed_execution_errors"]
              else "That query failed to execute. Write a corrected query.")
        messages.append({"role": "user", "content": fb})
    s = score(task.db_path, task.gold_sql, sql, frozen_eval["keep_distinct"],
              frozen_eval["exec_timeout_s"], frozen_eval["max_result_rows"], frozen_eval["verifier"])
    return {
        "task_id": task.task_id,
        "pass": s["pass"],
        "pass_other_verifier": s["pass_other"],
        "pred_sql": sql,
        "pred_error": s["pred_error"],
        "gold_empty": s["gold_empty"],
        "n_attempts": len(attempts),
        "attempts": attempts,
        "fewshot_ids": [x.task_id for x in shots],
        "prompt_tokens": ptok,
        "completion_tokens": ctok,
        "student_seconds": round(secs, 3),
    }


if HARNESS_KIND == "agent":
    # Run 5: same validation/ids/diffs, but over the agent's fields and its multi-step loop.
    from rsi.agent import AGENT_FIELDS as _AF, run_task as _agent_run_task
    EDITABLE_FIELDS = _AF
    run_task = _agent_run_task  # noqa: F811
