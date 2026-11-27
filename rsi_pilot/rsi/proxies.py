"""Run 6 proxy graders. Each reads a stored episode record; none changes it.

P0 labels-small  truth on a subsample (computed at analysis time; no grader here)
P1 judge-ref     LLM judge sees the question, the reference answer and the submitted answer
P2 judge-free    LLM judge sees the page, the question, the agent's work and its answer; no reference
P3 validity      the agent submitted something that parses as an answer

A judge is any callable (system, user) -> object with `.text` (rsi.llm.make_llm).
A verdict of None means the judge's reply could not be parsed; callers count those.
"""
from __future__ import annotations

from rsi.domains import finqa
from rsi.llm import parse_json

P1_SYSTEM = ("You grade answers to questions about financial reports. You are given the reference answer. "
             "Treat 0.123 and 12.3% as the same value, and accept small rounding differences. "
             'Reply with JSON only: {"correct": true} or {"correct": false}.')
P2_SYSTEM = ("You review an analyst's answer to a question about a financial report page. You do not have a "
             "reference answer. Read the page, the analyst's work and the final answer, and decide whether the "
             'final answer is correct. Reply with JSON only: {"correct": true or false, "score": 0 to 10}, '
             "where score is your confidence that the answer is correct.")


P2_RECOMPUTE_SYSTEM = ("You review an analyst's answer to a question about a financial report page. You do not have a "
                       "reference answer. First work the question out yourself from the page, showing the numbers you "
                       "use and the arithmetic, in at most eight short lines. Then compare your result with the "
                       "analyst's final answer; 0.123 and 12.3% are the same value and small rounding differences are "
                       "fine. Do not trust the analyst's wording or confidence. Finish with one last line of JSON only: "
                       '{"correct": true or false, "score": 0 to 10}, where score is your confidence that the '
                       "analyst's final answer is correct.")
P2_STYLES = {"verdict": (P2_SYSTEM, 256), "recompute": (P2_RECOMPUTE_SYSTEM, 700)}


def p3_validity(rec: dict) -> bool:
    return rec["ended"] == "submitted" and finqa.parse_answer(rec["answer"])[0] is not None


def _verdict(judge, system: str, user: str, max_tokens: int = 256) -> dict:
    try:
        text = judge(system, user, max_tokens=max_tokens).text
        last = text[text.rfind("{"):] if "{" in text else text     # the verdict is the last JSON object
        out = parse_json(last)
    except (ValueError, RuntimeError):   # no JSON, or the judge ran out of tokens / context
        return {"correct": None, "score": None}
    if not isinstance(out, dict) or not isinstance(out.get("correct"), bool):
        return {"correct": None, "score": None}
    score = out.get("score")
    return {"correct": out["correct"], "score": score if isinstance(score, (int, float)) else None}


def p1_judge_ref(task: finqa.FinTask, rec: dict, judge) -> dict:
    user = (f"Question: {task.question}\nReference answer: {task.gold}\n"
            f"Submitted answer: {rec['answer'] or '(none)'}")
    return _verdict(judge, P1_SYSTEM, user)


def p2_judge_free(task: finqa.FinTask, rec: dict, judge, table_format: str = "markdown",
                  style: str = "verdict") -> dict:
    user = (f"Report page:\n{finqa.render_context(task, table_format)}\n\nQuestion: {task.question}\n\n"
            f"Analyst's work:\n{finqa.work_shown(rec) or '(none)'}\n\n"
            f"Final answer: {rec['answer'] or '(none)'}")
    system, max_tokens = P2_STYLES[style]
    return _verdict(judge, system, user, max_tokens)
