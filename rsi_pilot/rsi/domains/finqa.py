"""Run 6, D-fin: multi-step numeric reasoning over a financial report page (FinQA).

The agent reads the page (text, table, text), may call a calculator, and submits one
answer. Truth is programmatic: the submitted number against FinQA's `exe_ans`.
Each record keeps the full transcript so any number of proxy graders (rsi/proxies.py)
can read the same episode later.

Each turn the model returns one JSON action:
  {"tool": "calc", "arg": "(120.5 - 98.2) / 98.2"}
  {"tool": "submit", "arg": "22.7%"}
"""
from __future__ import annotations

import ast
import json
import operator
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from rsi.student import Completion

FIN_FIELDS: dict[str, tuple[type, str, Callable]] = {
    "system_prompt": (str, "string, 1 to 6000 chars", lambda v: 0 < len(v) <= 6000),
    "tool_guide": (str, "string, 1 to 3000 chars: how to use the tools", lambda v: 0 < len(v) <= 3000),
    "rules": (str, "string, 0 to 4000 chars: general lessons, shown before every task", lambda v: len(v) <= 4000),
    "table_format": (str, "markdown | rows: how the table is rendered", lambda v: v in {"markdown", "rows"}),
    "max_steps": (int, "integer 1 to 10: tool calls allowed, including submit", lambda v: 1 <= v <= 10),
    "verify_before_submit": (bool, "true | false: echo the answer and ask the agent to confirm (costs one step)",
                             lambda v: True),
}

REL_TOL, ABS_TOL = 0.01, 1e-3
ACTION = re.compile(r"\{.*\}", re.S)
NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:e-?\d+)?")
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}


@dataclass(frozen=True)
class FinTask:
    task_id: str
    question: str
    pre_text: tuple[str, ...]
    table: tuple[tuple[str, ...], ...]
    post_text: tuple[str, ...]
    gold: float | str          # a number, or "yes" / "no"


def validate(h: dict) -> dict:
    if set(h) != set(FIN_FIELDS):
        raise ValueError(f"harness fields {sorted(h)} != {sorted(FIN_FIELDS)}")
    for k, (typ, desc, ok) in FIN_FIELDS.items():
        if type(h[k]) is not typ or not ok(h[k]):
            raise ValueError(f"{k}={h[k]!r} is not {desc}")
    return h


def load_finqa(path: str | Path) -> list[FinTask]:
    """Load one FinQA split file (train.json / dev.json / test.json)."""
    tasks = []
    for e in json.loads(Path(path).read_text(encoding="utf-8")):
        g = e["qa"]["exe_ans"]
        gold = g.strip().lower() if isinstance(g, str) else float(g)
        tasks.append(FinTask(e["id"], e["qa"]["question"], tuple(e["pre_text"]),
                             tuple(tuple(str(c) for c in row) for row in e["table"]),
                             tuple(e["post_text"]), gold))
    return tasks


def render_table(table, fmt: str) -> str:
    if not table:
        return "(no table)"
    if fmt == "markdown":
        head, *rows = table
        lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
        return "\n".join(lines + ["| " + " | ".join(r) + " |" for r in rows])
    head, *rows = table
    return "\n".join("; ".join(f"{h or 'item'}: {c}" for h, c in zip(head, r)) for r in rows)


def render_context(task: FinTask, fmt: str) -> str:
    return "\n\n".join(p for p in (" ".join(task.pre_text), render_table(task.table, fmt),
                                   " ".join(task.post_text)) if p)


def safe_calc(expr: str) -> float:
    """Arithmetic only: numbers, + - * / **, parentheses. Anything else raises ValueError."""
    def ev(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in OPS:
            return OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in OPS:
            return OPS[type(n.op)](ev(n.operand))
        raise ValueError("only numbers and + - * / ** ( ) are allowed")
    cleaned = expr.replace(",", "").replace("$", "").replace("%", "/100")
    try:
        return float(ev(ast.parse(cleaned, mode="eval").body))
    except (SyntaxError, ZeroDivisionError, OverflowError, TypeError) as e:
        raise ValueError(str(e)) from e


def parse_answer(text: str) -> tuple[float | str | None, bool]:
    """Return (value, has_percent_sign). value is a float, 'yes'/'no', or None if unparseable."""
    s = str(text).strip().lower().replace(",", "").replace("$", "")
    if re.match(r"^(yes|no)\b", s):
        return s[:3].strip(), False
    m = NUMBER.search(s)
    if not m:
        return None, False
    return float(m.group()), "%" in s[m.end():m.end() + 3]


def _close(p: float, g: float) -> bool:
    return abs(p - g) <= max(REL_TOL * abs(g), ABS_TOL)


def grade(gold: float | str, answer: str) -> dict:
    """Truth. `pass` forgives a factor of 100 either way (0.123 vs 12.3), because FinQA's
    exe_ans mixes fractions and percentages. `pass_strict` forgives it only when the
    answer carries a percent sign. Both are recorded on every episode."""
    val, pct = parse_answer(answer)
    if val is None:
        return {"pass": False, "pass_strict": False, "parsed": None}
    if isinstance(gold, str) or isinstance(val, str):
        ok = isinstance(gold, str) and isinstance(val, str) and gold == val
        return {"pass": ok, "pass_strict": ok, "parsed": val}
    strict = _close(val, gold) or (pct and _close(val / 100, gold))
    lenient = strict or _close(val / 100, gold) or _close(val * 100, gold)
    return {"pass": lenient, "pass_strict": strict, "parsed": val}


def parse_action(text: str) -> dict | None:
    m = ACTION.search(text)
    if not m:
        return None
    try:
        a = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return a if isinstance(a, dict) and isinstance(a.get("tool"), str) else None


def first_message(h: dict, task: FinTask) -> str:
    parts = [f"Rules learned so far:\n{h['rules']}"] if h["rules"] else []
    parts += [f"Report page:\n{render_context(task, h['table_format'])}", f"Question: {task.question}",
              f"You have {h['max_steps']} tool calls. Reply with one JSON action."]
    return "\n\n".join(parts)


def run_task(h: dict, task: FinTask, student: Callable[[list[dict]], Completion]) -> dict:
    messages = [{"role": "system", "content": h["system_prompt"] + "\n\n" + h["tool_guide"]},
                {"role": "user", "content": first_message(h, task)}]
    trace, ptok, ctok, secs = [], 0, 0, 0.0
    answer, last_calc, pending, how = "", "", None, "out_of_steps"
    for step in range(h["max_steps"]):
        c = student(messages)
        ptok += c.prompt_tokens; ctok += c.completion_tokens; secs += c.seconds
        messages.append({"role": "assistant", "content": c.text})
        a = parse_action(c.text)
        tool, arg = (a.get("tool"), str(a.get("arg", ""))) if a else (None, "")
        left = h["max_steps"] - step - 1
        if tool == "submit" or (tool == "confirm" and pending is not None):
            ans = pending if tool == "confirm" else arg.strip()
            if h["verify_before_submit"] and tool == "submit" and left > 0:
                pending = ans
                obs = (f"You are about to submit: {ans}\nCheck the sign, the units and whether a percentage is "
                       f'asked for. Reply {{"tool": "confirm"}} to submit it, or keep working.')
                trace.append({"tool": tool, "arg": arg[:300], "obs": obs, "said": c.text[:1500]})
                messages.append({"role": "user", "content": f"{obs}\n({left} calls left)"})
                continue
            answer, how = ans, "submitted"
            trace.append({"tool": tool, "arg": arg[:300], "obs": "", "said": c.text[:1500]})
            break
        if tool == "calc":
            try:
                last_calc = f"{safe_calc(arg):.6g}"
                obs = last_calc
            except ValueError as e:
                obs = f"Error: {e}"
        else:
            obs = ('Error: reply with exactly one JSON action, e.g. {"tool": "calc", "arg": "(12.5 - 10) / 10"} '
                   'or {"tool": "submit", "arg": "25%"}.')
        pending = None
        trace.append({"tool": tool, "arg": arg[:300], "obs": obs, "said": c.text[:1500]})
        messages.append({"role": "user", "content": f"{obs}\n({left} calls left)"})
    if how != "submitted":
        answer = pending or last_calc
    g = grade(task.gold, answer) if answer else {"pass": False, "pass_strict": False, "parsed": None}
    return {"task_id": task.task_id, "pass": g["pass"], "pass_strict": g["pass_strict"], "answer": answer,
            "parsed": g["parsed"], "ended": how, "n_steps": len(trace), "trace": trace,
            "prompt_tokens": ptok, "completion_tokens": ctok, "student_seconds": round(secs, 3)}


def work_shown(rec: dict) -> str:
    """The agent's own words and tool calls, as a reference-free judge would see them."""
    lines = []
    for i, s in enumerate(rec["trace"], 1):
        lines.append(f"Step {i}: {s['said']}")
        if s["obs"]:
            lines.append(f"Result: {s['obs']}")
    return "\n".join(lines)
