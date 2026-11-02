"""Execute SQL read-only with a timeout, and compare result sets the way Spider does.

Comparison uses the vendored `result_eq` from Spider's official test-suite eval:
bag semantics, column permutations allowed, row order matters only when the
gold query contains ORDER BY. Its column-permutation search uses `random`, so we
seed a private RNG state around each call to keep scoring deterministic.

`verifier: agentwatch` in frozen.yaml switches to AgentWatch's own checker
(harness/evaluator.py), which lowercases and string-casts values, allows no
column permutation, and compares duplicate-sensitive sorted lists. Every score
also records the other checker's verdict for the audit.
"""
from __future__ import annotations

import random
import sqlite3
import time
from dataclasses import dataclass

from third_party.spider_eval.result_eq import result_eq


@dataclass
class ExecResult:
    ok: bool
    rows: list | None = None
    error: str = ""
    seconds: float = 0.0


def execute(db_path: str, sql: str, timeout_s: float = 30.0, max_rows: int = 100_000) -> ExecResult:
    t0 = time.monotonic()
    deadline = t0 + timeout_s
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
    except sqlite3.Error as e:
        return ExecResult(False, error=f"connect: {e}")
    conn.text_factory = lambda b: b.decode(errors="replace")
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    try:
        cur = conn.execute(sql)
        rows = cur.fetchmany(max_rows + 1)
        if len(rows) > max_rows:
            return ExecResult(False, error=f"result exceeds {max_rows} rows", seconds=time.monotonic() - t0)
        return ExecResult(True, rows=[tuple(r) for r in rows], seconds=time.monotonic() - t0)
    except sqlite3.OperationalError as e:
        msg = "timeout" if time.monotonic() > deadline else str(e)
        return ExecResult(False, error=msg, seconds=time.monotonic() - t0)
    except (sqlite3.Error, ValueError, OverflowError) as e:
        return ExecResult(False, error=f"{type(e).__name__}: {e}", seconds=time.monotonic() - t0)
    finally:
        conn.close()


def order_matters(gold_sql: str) -> bool:
    return "order by" in gold_sql.lower()


def compare_agentwatch(gold_rows: list, pred_rows: list, gold_sql: str) -> bool:
    """AgentWatch's checker (harness/evaluator.py in the parent repo), imported, not copied."""
    import sys
    from pathlib import Path
    root = str(Path(__file__).resolve().parents[2])
    if root not in sys.path:
        sys.path.append(root)
    from harness.evaluator import _has_order_by, _normalize_row
    g = [_normalize_row(r) for r in gold_rows]
    p = [_normalize_row(r) for r in pred_rows]
    return g == p if _has_order_by(gold_sql) else sorted(g) == sorted(p)


def compare_with(verifier: str, gold_rows: list, pred_rows: list, gold_sql: str) -> bool:
    if verifier == "spider_official":
        return compare(gold_rows, pred_rows, gold_sql)
    if verifier == "agentwatch":
        return compare_agentwatch(gold_rows, pred_rows, gold_sql)
    raise ValueError(f"unknown verifier {verifier}")


def compare(gold_rows: list, pred_rows: list, gold_sql: str, seed: int = 0) -> bool:
    state = random.getstate()
    random.seed(seed)
    try:
        return result_eq(gold_rows, pred_rows, order_matters=order_matters(gold_sql))
    finally:
        random.setstate(state)


def strip_distinct(sql: str) -> str:
    import re
    return re.sub(r"\bdistinct\b", " ", sql, flags=re.I)


def score(db_path: str, gold_sql: str, pred_sql: str, keep_distinct: bool = True,
          timeout_s: float = 30.0, max_rows: int = 100_000, verifier: str = "spider_official") -> dict:
    """Return {'pass', 'pass_other', 'pred_error', 'gold_empty'}. Raises if gold fails.

    'pass' uses `verifier`; 'pass_other' uses the other checker, so the audit can
    count disagreements between them."""
    g_sql, p_sql = (gold_sql, pred_sql) if keep_distinct else (strip_distinct(gold_sql), strip_distinct(pred_sql))
    g = execute(db_path, g_sql, timeout_s, max_rows)
    if not g.ok:
        raise RuntimeError(f"gold query failed on {db_path}: {g.error}\n{gold_sql}")
    p = execute(db_path, p_sql, timeout_s, max_rows)
    if not p.ok:
        return {"pass": False, "pass_other": False, "pred_error": p.error, "gold_empty": len(g.rows) == 0}
    other = "agentwatch" if verifier == "spider_official" else "spider_official"
    return {"pass": compare_with(verifier, g.rows, p.rows, gold_sql),
            "pass_other": compare_with(other, g.rows, p.rows, gold_sql),
            "pred_error": "", "gold_empty": len(g.rows) == 0}
