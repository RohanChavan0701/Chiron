"""Edits that do not come from the LLM proposer (run 4).

1. Random search (Arm C, the selection control). Each candidate changes 1 to
   `max_fields` fields to a random allowed value. Text fields are drawn from fixed
   menus of generic text-to-SQL advice written before any run, so Arm C can never
   encode anything about the tuning set. Arm C uses the same keep rule as Arm A.
   If Arm C matches Arm A's tuning-set gain, the proposer's edits are no better than
   blind search plus best-of-N selection on the tuning set.

2. Placebo edits. Rewordings of the baseline system prompt that keep its meaning.
   Scoring them on E measures how much a harmless edit moves the E score; the keep
   threshold for Arm B is set from that spread (rsi.baseline), not from re-running
   the same harness (which, with a deterministic student, measures nothing).
"""
from __future__ import annotations

import math
import random

from rsi.config import HARNESS_KIND
from rsi.harness import EDITABLE_FIELDS, diff_fields, validate

PLACEBO_PROMPTS = [
    "You are an expert SQLite developer. Given a database schema and a question,\n"
    "write a single SQLite query that answers the question.\n"
    "Return only the SQL query inside a ```sql code block.\n",
    "You are a skilled SQLite developer. Given a question and a database schema,\n"
    "write one SQLite query that answers the question.\n"
    "Return only the SQL query inside a ```sql code block.\n",
    "You are an expert in SQLite. Using the database schema provided, write one SQLite query\n"
    "that answers the question.\n"
    "Return only the SQL query inside a ```sql code block.\n",
    "As an expert SQLite developer, read the database schema and the question, then\n"
    "write one SQLite query that answers it.\n"
    "Return only the SQL query inside a ```sql code block.\n",
    "You are an expert SQLite developer. You will get a database schema and a question.\n"
    "Write one SQLite query that answers the question.\n"
    "Return only the SQL query inside a ```sql code block.\n",
    "You are an experienced SQLite developer. Given a database schema and a question,\n"
    "write one SQLite query answering the question.\n"
    "Return only the SQL query, inside a ```sql code block.\n",
    "You are an expert SQLite developer. Given a database schema and a question,\n"
    "produce one SQLite query that answers the question.\n"
    "Output only the SQL query inside a ```sql code block.\n",
    "You write SQLite queries as an expert. Given a database schema and a question,\n"
    "write one SQLite query that answers the question.\n"
    "Return only the SQL query inside a ```sql code block.\n",
    "You are an expert SQLite developer. Given the schema of a database and a question about it,\n"
    "write one SQLite query that answers the question.\n"
    "Return only the SQL query inside a ```sql code block.\n",
    "You are an expert SQLite developer. Given a database schema and a natural-language question,\n"
    "write one SQLite query that answers the question.\n"
    "Return just the SQL query inside a ```sql code block.\n",
]

GENERIC_PROMPTS = [
    "You are an expert SQLite developer. Given a database schema and a question,\n"
    "write one SQLite query that answers the question.\n"
    "Return only the SQL query inside a ```sql code block.\n",
    "You are an expert SQLite developer. Read the schema carefully and use only tables and\n"
    "columns that exist. Write one SQLite query that answers the question.\n"
    "Return only the SQL query inside a ```sql code block.\n",
    "You are an expert SQLite developer. Think about which tables are needed and how they join\n"
    "through foreign keys, then write one SQLite query that answers the question.\n"
    "Return only the SQL query inside a ```sql code block.\n",
    "You are an expert SQLite developer. Select only the columns the question asks for, in the\n"
    "order it asks for them. Write one SQLite query that answers the question.\n"
    "Return only the SQL query inside a ```sql code block.\n",
    "You are an expert SQLite developer. Prefer simple queries: avoid unnecessary joins,\n"
    "subqueries and DISTINCT. Write one SQLite query that answers the question.\n"
    "Return only the SQL query inside a ```sql code block.\n",
    "You are an expert SQLite developer. For questions about the most, least, highest or lowest,\n"
    "use ORDER BY with LIMIT 1. Write one SQLite query that answers the question.\n"
    "Return only the SQL query inside a ```sql code block.\n",
    "You are an expert SQLite developer. Use GROUP BY for questions about each or per item, and\n"
    "HAVING for conditions on aggregates. Write one SQLite query that answers the question.\n"
    "Return only the SQL query inside a ```sql code block.\n",
    "You are an expert SQLite developer. Check that every column you use belongs to a table in\n"
    "the FROM clause and qualify column names when tables share them.\n"
    "Write one SQLite query that answers the question.\n"
    "Return only the SQL query inside a ```sql code block.\n",
]

GENERIC_SUFFIXES = [
    "",
    "Use only tables and columns that appear in the schema.",
    "Return only the columns the question asks for.",
    "Use table aliases and qualify every column name.",
    "If the question asks for a count, use COUNT.",
    "Use JOIN conditions from the foreign keys.",
    "Do not add ORDER BY unless the question asks for an ordering or a top result.",
    "Check the query for syntax errors before answering.",
]

TEXT_MENUS = {"system_prompt": GENERIC_PROMPTS, "instructions_suffix": GENERIC_SUFFIXES}

# Run 5 (agent harness). Generic menus written before any run-5 result.
AGENT_PROMPTS = [
    "You are an expert SQLite developer working as an agent. You answer a question about a\n"
    "database by exploring it with tools, then submitting one SQLite query.\n",
    "You are an expert SQLite developer working as an agent. First look at the tables you need,\n"
    "then test your query with run_sql, then submit one SQLite query.\n",
    "You are a careful SQL agent. Do not guess column names: describe a table before using it.\n"
    "Answer the question by submitting one SQLite query.\n",
    "You are an expert SQLite developer working as an agent. Keep queries simple, select only the\n"
    "columns the question asks for, and submit one SQLite query.\n",
    "You are an efficient SQL agent. Use as few tool calls as you need, and always submit a\n"
    "query before you run out of calls.\n",
]
AGENT_TOOL_GUIDES = [
    'Reply with exactly one JSON object per turn, and nothing else:\n'
    '{"tool": "list_tables"}                     list the tables\n'
    '{"tool": "describe", "arg": "TABLE"}        show a table\'s columns and keys\n'
    '{"tool": "run_sql", "arg": "SELECT ..."}    run a query and see its first rows\n'
    '{"tool": "submit", "arg": "SELECT ..."}     give your final answer (ends the task)\n',
    'One JSON object per turn, nothing else. Tools:\n'
    '- {"tool": "list_tables"}: table names\n'
    '- {"tool": "describe", "arg": "TABLE"}: columns, keys (use before writing joins)\n'
    '- {"tool": "run_sql", "arg": "SELECT ..."}: run a query to check it\n'
    '- {"tool": "submit", "arg": "SELECT ..."}: final answer\n'
    'A good order: describe the tables you need, run_sql your query, then submit it.\n',
    'Answer in JSON, one action per turn:\n'
    '{"tool": "describe", "arg": "TABLE"} | {"tool": "list_tables"} | {"tool": "run_sql", "arg": "SQL"} | '
    '{"tool": "submit", "arg": "SQL"}\n'
    'If run_sql returns an error, fix the query before submitting.\n',
]
AGENT_RULES = [
    "",
    "- Describe a table before using its columns.",
    "- Check join keys with describe before joining.\n- Select only the columns the question asks for.",
    "- If a query returns no rows, check the filter values with run_sql before submitting.",
    "- Use COUNT, MAX, MIN, AVG and GROUP BY for questions about totals, extremes and groups.",
    "- Submit before you run out of tool calls.\n- Do not add ORDER BY unless the question needs an order.",
]
AGENT_PLACEBO_PROMPTS = [
    "You are an expert SQLite developer acting as an agent. You answer a question about a\n"
    "database by exploring it with tools, then submitting one SQLite query.\n",
    "You are an expert SQLite developer working as an agent. You answer questions about a\n"
    "database by exploring it with tools and then submitting one SQLite query.\n",
    "You are a skilled SQLite developer working as an agent. You answer a question about a\n"
    "database by exploring it with tools, then submitting a single SQLite query.\n",
    "As an expert SQLite developer working as an agent, you answer a question about a\n"
    "database: explore it with tools, then submit one SQLite query.\n",
    "You are an expert SQLite developer and an agent. To answer a question about a database,\n"
    "you explore it with tools and then submit one SQLite query.\n",
    "You are an experienced SQLite developer working as an agent. You answer a question about a\n"
    "database by using tools to explore it, then submitting one SQLite query.\n",
    "You are an expert SQLite developer working as an agent. Your job is to answer a question about\n"
    "a database by exploring it with tools, then submitting one SQLite query.\n",
    "You work as an agent and are an expert SQLite developer. You answer a question about a\n"
    "database by exploring it with tools, then submitting one SQLite query.\n",
    "You are an expert SQLite developer working as an agent. You answer a question about a given\n"
    "database by exploring it with the tools, then submitting one SQLite query.\n",
    "You are an expert SQLite developer working as an agent. You answer a natural-language question\n"
    "about a database by exploring it with tools, then submitting one SQLite query.\n",
]


def placebo_prompts() -> list[str]:
    return AGENT_PLACEBO_PROMPTS if HARNESS_KIND == "agent" else PLACEBO_PROMPTS


AGENT_MENUS = {"system_prompt": AGENT_PROMPTS, "tool_guide": AGENT_TOOL_GUIDES, "rules": AGENT_RULES}
INT_RANGES = {"sample_rows": (0, 5), "fewshot_k": (0, 8), "max_retries": (0, 3),
              "describe_sample_rows": (0, 5), "result_preview_rows": (1, 20), "max_steps": (2, 12)}
CHOICES = {"schema_format": ["create_table", "compact"], "fewshot_rule": ["fixed", "lexical"],
           "schema_upfront": ["none", "tables", "full"]}


def _random_value(field: str, cur, rng: random.Random):
    typ = EDITABLE_FIELDS[field][0]
    menus = AGENT_MENUS if HARNESS_KIND == "agent" else TEXT_MENUS
    if field in menus:
        opts = [v for v in menus[field] if v != cur]
        return rng.choice(opts)
    if typ is bool:
        return not cur
    if field in CHOICES:
        return rng.choice([v for v in CHOICES[field] if v != cur])
    if field in INT_RANGES:
        lo, hi = INT_RANGES[field]
        return rng.choice([v for v in range(lo, hi + 1) if v != cur])
    raise ValueError(f"no random value rule for {field}")


def random_edit(cur: dict, rng: random.Random, max_fields: int) -> dict:
    """Return {field: new_value} changing 1..max_fields fields of `cur`."""
    k = rng.randint(1, max(1, max_fields))
    fields = rng.sample(sorted(EDITABLE_FIELDS), k)
    edits = {f: _random_value(f, cur[f], rng) for f in fields}
    validate({**cur, **edits})
    assert diff_fields(cur, {**cur, **edits}), "random edit changed nothing"
    return edits


def cosine_budget(gen: int, generations: int, b_max: int, b_min: int) -> int:
    """RRSI's annealed edit budget: b_max fields at generation 1, falling to b_min at the last."""
    if generations <= 1:
        return b_max
    frac = (gen - 1) / (generations - 1)
    return int(round(b_min + (b_max - b_min) * (1 + math.cos(math.pi * frac)) / 2))


def placebo_threshold(deltas: list[int], k: int, alpha: float, floor: int) -> int:
    """Smallest t >= floor such that the best of k placebo edits reaches a gain of t
    with probability <= alpha, using the empirical distribution of placebo deltas.
    P(max of k >= t) = 1 - F(t - 1)^k."""
    if not deltas:
        return floor
    n = len(deltas)
    t = floor
    while True:
        F = sum(1 for d in deltas if d <= t - 1) / n
        if 1 - F ** k <= alpha:
            return t
        t += 1
