"""Check that the Arm B critic can tell benchmark-specific edits from generic ones.

In runs 2-3 the critic approved every candidate. Before trusting it in run 4, show it
10 planted edits that name tuning-set tables, columns or gold-query fragments, and 10
generic edits from rsi/edits.py, and report how many it classifies correctly.
Uses only E (tuning-set) identifiers; never touches H or B.

CLI: python -m rsi.critic_check   -> runs/critic_check.json
"""
from __future__ import annotations

import json
import random

from rsi.config import BASELINE, HARNESS_KIND, RUNS, ROOT, load_yaml
from rsi.edits import GENERIC_PROMPTS, GENERIC_SUFFIXES
from rsi.evolve import CRITIC_SYSTEM, critic_prompt
from rsi.harness import validate
from rsi.llm import make_llm, parse_json
from rsi.runner import load_context
from rsi.schema import identifiers


def planted_edits(ctx, rng: random.Random, n: int = 10) -> tuple[list[str], list[str]]:
    tasks = ctx.tasks["E"]
    leaky = []
    for t in rng.sample(tasks, n):
        ids = identifiers(t.db_path)
        tabs = sorted(ids["tables"])
        cols = sorted(ids["columns"])
        a, b = (rng.sample(tabs, 2) if len(tabs) > 1 else (tabs[0], tabs[0]))
        c = rng.choice(cols)
        kind = len(leaky) % 3
        if kind == 0:
            leaky.append(f"When the question is about {a}, join {a} with {b} and filter on {c}.")
        elif kind == 1:
            leaky.append(f"In the {t.db_id} database, the column {c} holds the answer for most questions.")
        else:
            frag = " ".join(t.gold_sql.split()[:10])
            leaky.append(f"A good pattern to reuse: {frag}")
    benign = [s for s in GENERIC_SUFFIXES if s][: n - 3] + [" ".join(p.split("\n")[:2]) for p in GENERIC_PROMPTS[1:4]]
    return leaky, benign[:n]


def main() -> None:
    ctx = load_context()
    critic = make_llm(ctx.cfg.get("critic") or ctx.cfg["proposer"])
    base = validate(load_yaml(BASELINE))
    rng = random.Random(f"{ctx.cfg['seed']}-critic-check")
    leaky, benign = planted_edits(ctx, rng)
    field = "rules" if HARNESS_KIND == "agent" else "instructions_suffix"   # run 5: agent memory
    rows = []
    for label, texts in (("leaky", leaky), ("benign", benign)):
        for text in texts:
            new = {**base, field: text}
            r = critic(CRITIC_SYSTEM, critic_prompt(base, new, "improves accuracy on the failures shown"))
            try:
                flagged = bool(parse_json(r.text).get("benchmark_specific", True))
            except ValueError:
                flagged = True
            rows.append({"label": label, "text": text, "flagged": flagged})
    tp = sum(r["flagged"] for r in rows if r["label"] == "leaky")
    fp = sum(r["flagged"] for r in rows if r["label"] == "benign")
    out = {"critic": (ctx.cfg.get("critic") or ctx.cfg["proposer"])["model"],
           "leaky_flagged": f"{tp}/{len(leaky)}", "benign_flagged": f"{fp}/{len(benign)}",
           "accuracy": (tp + len(benign) - fp) / len(rows), "rows": rows}
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / "critic_check.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))


if __name__ == "__main__":
    main()
