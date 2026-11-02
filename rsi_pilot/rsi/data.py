"""Load Spider and BIRD Mini-Dev into one Task shape.

Spider: dev.json / train_spider.json entries carry a parsed `sql` dict, which the
official hardness classifier (vendored) reads directly.
BIRD Mini-Dev: entries carry `difficulty`, `evidence`, `SQL`, `db_id`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

from third_party.spider_eval.hardness import eval_hardness


@dataclass(frozen=True)
class Task:
    task_id: str
    source: str          # spider_dev | spider_train | bird
    db_id: str
    db_path: str
    question: str
    gold_sql: str
    evidence: str = ""
    difficulty: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _spider_db_path(spider_dir: Path, db_id: str) -> str:
    return str(spider_dir / "database" / db_id / f"{db_id}.sqlite")


def load_spider(spider_dir: str | Path, split: str = "dev") -> list[Task]:
    spider_dir = Path(spider_dir)
    fname = {"dev": "dev.json", "train": "train_spider.json"}[split]
    entries = json.loads((spider_dir / fname).read_text())
    tasks = []
    for i, e in enumerate(entries):
        tasks.append(Task(
            task_id=f"spider_{split}_{i}",
            source=f"spider_{split}",
            db_id=e["db_id"],
            db_path=_spider_db_path(spider_dir, e["db_id"]),
            question=e["question"],
            gold_sql=e["query"],
            difficulty=eval_hardness(e["sql"]),
        ))
    return tasks


def _find_bird_json(bird_dir: Path, override: str | None) -> Path:
    if override:
        return bird_dir / override
    cands = sorted(p for p in bird_dir.rglob("*.json")
                   if "sqlite" in p.name.lower() and "mini_dev" in p.name.lower())
    if not cands:
        raise FileNotFoundError(
            f"No BIRD Mini-Dev SQLite json under {bird_dir}; set data.bird_json in frozen.yaml")
    return cands[0]


def _find_bird_db(bird_dir: Path, db_id: str) -> str:
    hits = list(bird_dir.rglob(f"{db_id}.sqlite"))
    if not hits:
        raise FileNotFoundError(f"BIRD database {db_id}.sqlite not found under {bird_dir}")
    return str(hits[0])


def load_bird(bird_dir: str | Path, json_name: str | None = None) -> list[Task]:
    bird_dir = Path(bird_dir)
    entries = json.loads(_find_bird_json(bird_dir, json_name).read_text())
    db_cache: dict[str, str] = {}
    tasks = []
    for i, e in enumerate(entries):
        db = e["db_id"]
        if db not in db_cache:
            db_cache[db] = _find_bird_db(bird_dir, db)
        tasks.append(Task(
            task_id=f"bird_{e.get('question_id', i)}",
            source="bird",
            db_id=db,
            db_path=db_cache[db],
            question=e["question"],
            gold_sql=e.get("SQL") or e.get("sql") or e["query"],
            evidence=e.get("evidence", "") or "",
            difficulty=e.get("difficulty", ""),
        ))
    return tasks


def tasks_from_split(split_ids: list[str], pool: list[Task]) -> list[Task]:
    by_id = {t.task_id: t for t in pool}
    missing = [i for i in split_ids if i not in by_id]
    if missing:
        raise KeyError(f"{len(missing)} split ids not found in data, e.g. {missing[:3]}")
    return [by_id[i] for i in split_ids]
