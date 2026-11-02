"""Serialize a SQLite schema for the prompt. Formats are a harness choice."""
from __future__ import annotations

import sqlite3
from functools import lru_cache


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


@lru_cache(maxsize=256)
def serialize(db_path: str, fmt: str = "create_table", sample_rows: int = 0,
              include_foreign_keys: bool = True) -> str:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.text_factory = lambda b: b.decode(errors="replace")
    try:
        tables = conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        out = []
        for name, ddl in tables:
            cols = conn.execute(f"PRAGMA table_info({_q(name)})").fetchall()  # cid,name,type,notnull,dflt,pk
            fks = conn.execute(f"PRAGMA foreign_key_list({_q(name)})").fetchall()  # id,seq,table,from,to,...
            if fmt == "create_table":
                block = (ddl or "").strip()
                if not include_foreign_keys:
                    block = "\n".join(l for l in block.splitlines() if "foreign key" not in l.lower())
            elif fmt == "compact":
                parts = [f"{c[1]}{' (PK)' if c[5] else ''}" for c in cols]
                block = f"{name}({', '.join(parts)})"
                if include_foreign_keys and fks:
                    block += "\n  FK: " + "; ".join(f"{name}.{fk[3]} -> {fk[2]}.{fk[4]}" for fk in fks)
            else:
                raise ValueError(f"unknown schema_format {fmt}")
            if sample_rows > 0:
                try:
                    rows = conn.execute(f"SELECT * FROM {_q(name)} LIMIT {int(sample_rows)}").fetchall()
                except sqlite3.Error:
                    rows = []
                if rows:
                    hdr = " | ".join(c[1] for c in cols)
                    body = "\n".join(" | ".join(str(v)[:40] for v in r) for r in rows)
                    block += f"\n/* {len(rows)} example rows:\n{hdr}\n{body}\n*/"
            out.append(block)
        return "\n\n".join(out)
    finally:
        conn.close()


def identifiers(db_path: str) -> dict[str, set[str]]:
    """Table and column names, for the leak check."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        cols = set()
        for t in tables:
            cols |= {c[1] for c in conn.execute(f"PRAGMA table_info({_q(t)})")}
        return {"tables": set(tables), "columns": cols}
    finally:
        conn.close()
