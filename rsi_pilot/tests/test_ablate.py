"""Fixed-harness ablation (rsi/ablate.py): plumbing tests on synthetic tasks with a fake student.

In-process tests use the single-shot harness kind (the test session's default); the agent-kind
end-to-end test runs in a subprocess with RSI_HARNESS_KIND=agent, as in tests/test_agent.py."""
import csv
import json
import os
import subprocess
import sys

import pytest

from rsi.ablate import SplitsMismatch, check_splits, eval_order, load_variants, report, run_seed
from rsi.agent import first_message
from rsi.config import ROOT, dump_yaml, load_yaml
from rsi.fewshot import FewShotPool
from rsi.harness import HarnessError, validate
from rsi.pool import wilcoxon_exact
from rsi.runner import Context
from rsi.student import Completion

EVAL = {"exec_timeout_s": 5, "max_result_rows": 1000, "keep_distinct": True,
        "verifier": "spider_official", "bird_include_evidence": True}


class CountingStudent:
    """Single-shot fake: right only when sample rows are shown (the 'variant' field below)."""
    def __init__(self, tasks):
        self.gold = {t.question: t.gold_sql for ts in tasks.values() for t in ts}
        self.calls = 0

    def __call__(self, messages):
        self.calls += 1
        user = messages[1]["content"]
        q = [l for l in user.splitlines() if l.startswith("Question: ")][-1][10:]
        sql = self.gold[q] if "example rows" in user else "SELECT 1"
        return Completion(f"```sql\n{sql}\n```", 100, 10, 0.01)


@pytest.fixture
def sql_base():
    return validate(load_yaml(ROOT / "harness.yaml"))


@pytest.fixture
def ctx(tasks, tmp_path):
    cfg = load_yaml(ROOT / "frozen.yaml")
    cfg["seed"] = 20261212
    pool = FewShotPool(tasks["train"], {"evo", "held", "bird"}, cfg["seed"])
    return Context(cfg, {"n_per_split": 6}, {k: tasks[k] for k in ("E", "H", "B")}, pool,
                   CountingStudent(tasks), runs_dir=tmp_path / "runs")


def write_finals(ctx, h):
    for a in ("A", "B"):
        dump_yaml(h, ctx.runs_dir / f"arm_{a}" / "final.yaml")


def test_variants_exactly_one_field(tmp_path, sql_base):
    f = tmp_path / "v.yaml"
    f.write_text("rows_only:\n  sample_rows: 2\nsuffix_only:\n  instructions_suffix: Be brief.\n")
    v = load_variants(f, sql_base)
    assert list(v) == ["rows_only", "suffix_only"] and v["rows_only"]["sample_rows"] == 2
    assert {k for k in sql_base if sql_base[k] != v["rows_only"][k]} == {"sample_rows"}
    bad = {"two": "two:\n  sample_rows: 2\n  max_retries: 1\n",
           "same_as_baseline": f"same:\n  sample_rows: {sql_base['sample_rows']}\n",
           "invalid_value": "bad:\n  sample_rows: 9\n",
           "unknown_field": "bad:\n  no_such_field: 1\n",
           "reserved_name": "baseline:\n  sample_rows: 2\n",
           "duplicate": "a:\n  sample_rows: 2\nb:\n  sample_rows: 2\n",
           "empty": "# nothing\n"}
    for case, text in bad.items():
        f.write_text(text)
        with pytest.raises(HarnessError):
            load_variants(f, sql_base)


def test_schema_only_first_message_has_full_schema(tasks):
    base = load_yaml(ROOT / "harness_agent.yaml")
    t = tasks["H"][0]
    b, v = first_message(base, t, EVAL), first_message({**base, "schema_upfront": "full"}, t, EVAL)
    assert "CREATE TABLE" not in b and "Tables: held_album, held_band" in b
    assert "CREATE TABLE" in v and "sales" in v and "FOREIGN KEY" in v.upper()


def test_eval_order_alternates_by_seed_parity():
    assert eval_order(20261212, ["x", "y"]) == ["baseline", "x", "y"]
    assert eval_order(20261211, ["x", "y"]) == ["x", "y", "baseline"]


def test_guard_refuses_without_finals_then_allows_and_logs(ctx, sql_base, tmp_path):
    variants = {"rows_only": {**sql_base, "sample_rows": 1}}
    out = ctx.runs_dir / "ablation"
    with pytest.raises(PermissionError):
        run_seed(ctx, variants, ["H", "B"], sql_base, out)
    assert not (out / "ablation.json").exists()
    log = [json.loads(l) for l in (ctx.runs_dir / "heldout_access.jsonl").read_text().splitlines()]
    assert [(r["split"], r["purpose"], r["is_baseline"]) for r in log] == \
        [("H", "ablation_baseline", True), ("B", "ablation_baseline", True)]   # even seed: baseline first

    write_finals(ctx, {**sql_base, "max_retries": 1})
    (ctx.runs_dir / "heldout_access.jsonl").unlink()
    s = run_seed(ctx, variants, ["H", "B"], sql_base, out)
    log = [json.loads(l) for l in (ctx.runs_dir / "heldout_access.jsonl").read_text().splitlines()]
    assert [(r["split"], r["purpose"]) for r in log] == [("H", "ablation_baseline"), ("B", "ablation_baseline"),
                                                         ("H", "ablation_rows_only"), ("B", "ablation_rows_only")]
    assert s["order"] == ["baseline/H", "baseline/B", "rows_only/H", "rows_only/B"]
    assert s["changed_field"] == {"rows_only": "sample_rows"}
    assert s["results"]["rows_only"]["H"]["passed"] == 6 and s["results"]["baseline"]["H"]["passed"] < 6
    assert s["results"]["baseline"]["H"]["tokens_per_task"] == 110
    full = json.loads((out / "rows_only_H.json").read_text())
    assert len(full["records"]) == 6 and full["passed"] == 6
    on_disk = json.loads((out / "ablation.json").read_text())
    assert on_disk["harnesses"]["rows_only"]["sample_rows"] == 1 and on_disk["student"] == ctx.cfg["student"]
    # fresh evaluations, separate cache dir (run 5's cache is never overwritten)
    caches = [p.name for p in (ctx.runs_dir / "cache").iterdir()]
    assert caches and all(c.startswith("ablation_") for c in caches)
    calls = ctx.student.calls
    with pytest.raises(FileExistsError):
        run_seed(ctx, variants, ["H"], sql_base, out)
    run_seed(ctx, variants, ["H"], sql_base, out, force=True)
    assert ctx.student.calls == calls + 12


def test_odd_seed_runs_variants_first(ctx, sql_base):
    ctx.cfg["seed"] = 20261211
    write_finals(ctx, sql_base | {"max_retries": 1})
    s = run_seed(ctx, {"rows_only": {**sql_base, "sample_rows": 1}}, ["H"], sql_base, ctx.runs_dir / "ablation")
    assert s["order"] == ["rows_only/H", "baseline/H"]


def test_splits_consistency_check(tmp_path):
    cfg = {"splits": {"h_max": 3, "b_max": 2}}
    runs = tmp_path / "s1"
    runs.mkdir()
    sp = {"H": ["h1", "h2", "h3"], "B": ["b1", "b2"]}
    with pytest.raises(SplitsMismatch, match="audit.json"):
        check_splits(sp, cfg, runs)                       # no audit: cannot check
    (runs / "audit.json").write_text(json.dumps({
        "baseline/H": {"testsuite_false_positive_ids": ["h1"]}, "arm_A/H": {"testsuite_false_positive_ids": ["h3"]},
        "baseline/B": {"passes": 1}}))
    check_splits(sp, cfg, runs)
    with pytest.raises(SplitsMismatch, match="not in the regenerated H"):
        check_splits({**sp, "H": ["h1", "h2", "h4"]}, cfg, runs)
    with pytest.raises(SplitsMismatch, match="H has 2 tasks"):
        check_splits({**sp, "H": ["h1", "h3"]}, cfg, runs)
    (runs / "evals").mkdir()
    (runs / "evals" / "baseline_B.json").write_text(json.dumps({"vector": {"b1": True, "b9": False}}))
    with pytest.raises(SplitsMismatch, match="B task ids differ"):
        check_splits(sp, cfg, runs)


def fake_session(seed, base_h, var_h, n=200, tok=(2000, 1800)):
    vec = lambda k: {f"t{i}": i < k for i in range(n)}
    res = lambda k, t: {"passed": k, "n": n, "accuracy": k / n, "tokens_per_task": t, "vector": vec(k)}
    order = ["baseline/H", "schema_only/H"] if seed % 2 == 0 else ["schema_only/H", "baseline/H"]
    return {"seed": seed, "splits": ["H"], "order": order, "changed_field": {"schema_only": "schema_upfront"},
            "harnesses": {"baseline": {"schema_upfront": "tables"}, "schema_only": {"schema_upfront": "full"}},
            "results": {"baseline": {"H": res(base_h, tok[0])}, "schema_only": {"H": res(var_h, tok[1])}}}


def test_report_math(tmp_path):
    root = tmp_path / "runs_v5"
    data = [(20261211, 96, 118), (20261212, 95, 113), (20261213, 91, 117), (20261214, 95, 95)]
    for seed, b, v in data:
        d = root / f"s{seed}" / "ablation"
        d.mkdir(parents=True)
        (d / "ablation.json").write_text(json.dumps(fake_session(seed, b, v)))
    with open(root / "summary.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["seed", "harness", "E", "E2", "H", "B", "n_E", "n_E2", "n_H", "n_B", "tokens_per_task_H"])
        for seed in (1, 2):
            w.writerow([seed, "baseline", 0, 0, 94, 40, 50, 50, 200, 200, 2000])
            for arm, h in (("arm_A", 116), ("arm_B", 118), ("arm_C", 120)):
                w.writerow([seed, arm, 0, 0, h, 60, 50, 50, 200, 200, 3000])
    dirs = sorted(root.glob("s*"))
    md = report(dirs, root / "summary.csv")
    assert md == report(list(reversed(dirs)), root / "summary.csv")          # deterministic, sorted by seed
    net = [22, 18, 26, 0]
    p = wilcoxon_exact(net)
    assert p == pytest.approx(0.25)                                          # zero dropped, 3 positive
    assert f"| schema_only | H | +22, +18, +26, +0 | +11.0, +9.0, +13.0, +0.0 | +8.2 | 5.7 | 66/0 | 3/0 | 0.90 | {p:.3f} |" in md
    assert "| baseline | H | 4 | 47.1% | 1.1 | 2000 |" in md
    assert "| 20261211 | schema_only | 1 | 118/200 | 1800 |" in md and "| 20261211 | baseline | 2 | 96/200 | 2000 |" in md
    assert "reference from run 5, different session, not a paired comparison" in md.lower()
    assert "| arm_B | 59.0% | +12.0 pp | 30.0% | +10.0 pp |" in md          # baseline mean H = 47.0%
    assert "Arms' mean H gain over the run-5 baseline: +12.0 pp." in md


def test_agent_kind_end_to_end():
    """RSI_HARNESS_KIND=agent: the shipped variants file loads against harness_agent.yaml, the
    schema_only agent sees the full schema in its first message and the baseline does not."""
    code = r'''
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, "tests")
from conftest import make_db, task
from rsi.ablate import load_variants, run_seed, VARIANTS
from rsi.config import BASELINE, ROOT, dump_yaml, load_yaml
from rsi.harness import validate
from rsi.runner import Context
from rsi.student import Completion
tmp = Path(tempfile.mkdtemp())
db = make_db(tmp / "held.sqlite", "held")
kinds = ["count", "top", "join"]
H = [task(f"spider_dev_{i}", "spider_dev", "held", db, "held", kinds[i % 3]) for i in range(6)]
gold = {t.question: t.gold_sql for t in H}
firsts = []
def student(messages):
    first = messages[1]["content"]
    firsts.append(first)
    q = [l for l in first.splitlines() if l.startswith("Question: ")][-1][10:]
    sql = gold[q] if "CREATE TABLE" in first else "SELECT 1"
    return Completion(json.dumps({"tool": "submit", "arg": sql}), 50, 5, 0.01)
base = validate(load_yaml(BASELINE))
variants = load_variants(VARIANTS, base)
assert list(variants) == ["schema_only"], variants
cfg = load_yaml(ROOT / "frozen_v5_s20261214.yaml")
runs = tmp / "runs"
for a in "ABC":
    dump_yaml(variants["schema_only"], runs / f"arm_{a}" / "final.yaml")
ctx = Context(cfg, {}, {"H": H}, None, student, runs_dir=runs)
s = run_seed(ctx, variants, ["H"], base, runs / "ablation")
log = [json.loads(l)["purpose"] for l in (runs / "heldout_access.jsonl").read_text().splitlines()]
print(json.dumps({"order": s["order"], "passed": {k: v["H"]["passed"] for k, v in s["results"].items()},
                  "full_in_first": [("CREATE TABLE" in f) for f in firsts], "log": log}))
'''
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                         env={**os.environ, "RSI_HARNESS_KIND": "agent"})
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout.strip().splitlines()[-1])
    assert r["order"] == ["baseline/H", "schema_only/H"]                     # 20261214 is even
    assert r["passed"] == {"baseline": 0, "schema_only": 6}
    assert r["full_in_first"] == [False] * 6 + [True] * 6
    assert r["log"] == ["ablation_baseline", "ablation_schema_only"]
