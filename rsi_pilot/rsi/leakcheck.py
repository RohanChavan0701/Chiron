"""Deterministic check that a harness edit is not benchmark-specific.

Rejects edits whose new text values mention an evolve-set database id, table
name, or distinctive column name, or that copy a run of 6+ tokens from any
evolve-set gold query. Runs before the LLM critic in Arm B. Arm A logs the
result but does not act on it, so we can report how often Arm A leaks.
"""
from __future__ import annotations

import re

from rsi.data import Task
from rsi.schema import identifiers

_WORD = re.compile(r"[A-Za-z0-9_]+")
# common words that appear as Spider table/column names but are not benchmark-specific
GENERIC = {"id", "name", "names", "age", "year", "type", "date", "title", "country", "city", "state",
           "address", "price", "count", "number", "code", "description", "value", "status", "order",
           "student", "students", "people", "person", "time", "level", "rank", "score", "color"}


def _ngrams(tokens: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def _sql_tokens(s: str) -> list[str]:
    return [t.lower() for t in _WORD.findall(s)]


class LeakChecker:
    def __init__(self, evolve_tasks: list[Task], ngram: int = 6):
        names: set[str] = set()
        for db_path, db_id in {(t.db_path, t.db_id) for t in evolve_tasks}:
            names.add(db_id.lower())
            ids = identifiers(db_path)
            names |= {x.lower() for x in ids["tables"]}
            names |= {c.lower() for c in ids["columns"] if "_" in c or len(c) >= 10}
        self.names = {n for n in names if n not in GENERIC and len(n) >= 3}
        self.ngram = ngram
        self.gold_ngrams: set[tuple[str, ...]] = set()
        for t in evolve_tasks:
            self.gold_ngrams |= _ngrams(_sql_tokens(t.gold_sql), ngram)

    def check(self, old: dict, new: dict) -> list[str]:
        problems = []
        for k, v in new.items():
            if not isinstance(v, str) or v == old.get(k):
                continue
            words = {w.lower() for w in _WORD.findall(v)}
            old_words = {w.lower() for w in _WORD.findall(str(old.get(k, "")))}
            hits = sorted((words - old_words) & self.names)
            if hits:
                problems.append(f"{k}: names evolve-set identifiers {hits[:8]}")
            grams = _ngrams(_sql_tokens(v), self.ngram) - _ngrams(_sql_tokens(str(old.get(k, ""))), self.ngram)
            if grams & self.gold_ngrams:
                problems.append(f"{k}: copies a {self.ngram}-token span from an evolve-set gold query")
        return problems
