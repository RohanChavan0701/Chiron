"""Few-shot pool drawn from Spider TRAIN only.

Spider train and dev use disjoint databases. We still assert the pool shares no
database with any evaluation split, so no selection rule can pull E, H or B
examples into a prompt.
"""
from __future__ import annotations

import random
import re

from rsi.data import Task

_TOK = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "of", "in", "and", "or", "for", "to", "is", "are", "what", "which", "how",
         "show", "list", "find", "give", "return", "all", "each", "that", "with", "by", "on", "me", "do", "does"}


def _toks(s: str) -> set[str]:
    return {t for t in _TOK.findall(s.lower()) if t not in _STOP}


class FewShotPool:
    def __init__(self, pool: list[Task], forbidden_db_ids: set[str], seed: int):
        overlap = {t.db_id for t in pool} & forbidden_db_ids
        if overlap:
            raise ValueError(f"few-shot pool shares databases with eval splits: {sorted(overlap)[:5]}")
        if any(not t.source.endswith("train") for t in pool):
            raise ValueError("few-shot pool must come from a train split")
        self.pool = pool
        self._fixed = random.Random(seed).sample(pool, min(8, len(pool)))
        self._toks = [_toks(t.question) for t in pool]

    def select(self, task: Task, k: int, rule: str) -> list[Task]:
        if k <= 0:
            return []
        if rule == "fixed":
            return self._fixed[:k]
        if rule == "lexical":
            q = _toks(task.question)
            scored = sorted(range(len(self.pool)),
                            key=lambda i: (-len(q & self._toks[i]), self.pool[i].task_id))
            return [self.pool[i] for i in scored[:k]]
        raise ValueError(f"unknown fewshot_rule {rule}")
