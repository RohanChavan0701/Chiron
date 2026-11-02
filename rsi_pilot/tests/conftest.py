"""Synthetic fixtures. These exercise plumbing only; nothing here is an experimental result."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rsi.data import Task  # noqa: E402


def make_db(path: Path, prefix: str) -> str:
    conn = sqlite3.connect(path)
    conn.executescript(f"""
    CREATE TABLE {prefix}_band (band_id INTEGER PRIMARY KEY, name TEXT, founded INTEGER);
    CREATE TABLE {prefix}_album (album_id INTEGER PRIMARY KEY, band_id INTEGER, title TEXT, sales INTEGER,
        FOREIGN KEY (band_id) REFERENCES {prefix}_band(band_id));
    INSERT INTO {prefix}_band VALUES (1,'Alpha',1990),(2,'Beta',2001),(3,'Gamma',1985);
    INSERT INTO {prefix}_album VALUES (1,1,'A1',100),(2,1,'A2',300),(3,2,'B1',50),(4,3,'C1',700);
    """)
    conn.commit(); conn.close()
    return str(path)


@pytest.fixture
def dbs(tmp_path):
    return {p: make_db(tmp_path / f"{p}.sqlite", p) for p in ("evo", "held", "bird", "train")}


def task(tid, src, db_id, db_path, prefix, kind, difficulty="hard"):
    q = {
        "count": ("How many bands are there?", f"SELECT count(*) FROM {prefix}_band"),
        "top": ("Which album sold the most?", f"SELECT title FROM {prefix}_album ORDER BY sales DESC LIMIT 1"),
        "join": ("List band names with albums selling over 200.",
                 f"SELECT DISTINCT b.name FROM {prefix}_band b JOIN {prefix}_album a ON a.band_id = b.band_id WHERE a.sales > 200"),
    }[kind]
    return Task(tid, src, db_id, db_path, f"[{prefix}] {q[0]}", q[1], "", difficulty)


@pytest.fixture
def tasks(dbs):
    kinds = ["count", "top", "join"]
    E = [task(f"spider_dev_{i}", "spider_dev", "evo", dbs["evo"], "evo", kinds[i % 3]) for i in range(6)]
    H = [task(f"spider_dev_{10+i}", "spider_dev", "held", dbs["held"], "held", kinds[i % 3]) for i in range(6)]
    B = [task(f"bird_{i}", "bird", "bird", dbs["bird"], "bird", kinds[i % 3], "simple") for i in range(6)]
    T = [task(f"spider_train_{i}", "spider_train", "train", dbs["train"], "train", kinds[i % 3]) for i in range(6)]
    return {"E": E, "H": H, "B": B, "train": T}
