"""End-to-end plumbing test with a fake student and fake proposer. Not an experiment."""
import json

import pytest

from rsi.config import ROOT, load_yaml
from rsi.evolve import run_arm
from rsi.fewshot import FewShotPool
from rsi.harness import validate
from rsi.llm import LLMReply
from rsi.runner import Context, evaluate
from rsi.student import Completion


class FakeStudent:
    """Correct SQL only when the system prompt contains 'CAREFUL'; otherwise correct on 'count' tasks only."""
    def __init__(self, tasks):
        self.gold = {t.question: t.gold_sql for ts in tasks.values() for t in ts}

    def __call__(self, messages):
        sys_p = messages[0]["content"]
        q = [l for l in messages[1]["content"].splitlines() if l.startswith("Question: ")][-1][10:]
        gold = self.gold[q]
        sql = gold if ("CAREFUL" in sys_p or "count(*)" in gold) else "SELECT 1"
        return Completion(f"```sql\n{sql}\n```", prompt_tokens=100, completion_tokens=10, seconds=0.01)


class FakeLLM:
    """Proposer: gen 1 offers a leaking edit, a 3-field edit and a good 1-field edit.
    Later gens offer a useless sample_rows bump. Critic flags anything mentioning 'evo_'."""
    def __call__(self, system, user, max_tokens=0):
        if "audit proposed harness edits" in system:
            return LLMReply(json.dumps({"benchmark_specific": "evo_" in user, "reason": "test"}))
        if "Current score on the tuning set: 2/6" in user:
            base = load_yaml(ROOT / "harness.yaml")["system_prompt"]
            return LLMReply(json.dumps([
                {"edits": {"instructions_suffix": "Remember evo_album joins evo_band."}, "rationale": "leak"},
                {"edits": {"sample_rows": 1, "fewshot_k": 1, "max_retries": 1}, "rationale": "three fields"},
                {"edits": {"system_prompt": base + "\nBe CAREFUL."}, "rationale": "good"},
            ]))
        return LLMReply(json.dumps([{"edits": {"sample_rows": 2}, "rationale": "noop-ish"}]))


@pytest.fixture
def ctx(tasks, tmp_path):
    cfg = load_yaml(ROOT / "frozen.yaml")
    cfg["evolution"].update(generations=3, candidates_per_generation=3, failures_shown=3, min_keep_delta_tasks=1)
    pool = FewShotPool(tasks["train"], {"evo", "held", "bird"}, cfg["seed"])
    sp = {"n_per_split": 6}
    return Context(cfg, sp, {k: tasks[k] for k in ("E", "H", "B")}, pool, FakeStudent(tasks), runs_dir=tmp_path)


def test_heldout_guard_blocks_non_baseline(ctx):
    h = validate(load_yaml(ROOT / "harness.yaml"))
    evaluate(ctx, h, "H")  # baseline allowed
    with pytest.raises(PermissionError):
        evaluate(ctx, {**h, "sample_rows": 1}, "H")
    log = (ctx.runs_dir / "heldout_access.jsonl").read_text().splitlines()
    assert len(log) == 1 and json.loads(log[0])["is_baseline"]


def test_arm_b_rejects_leaks_and_wide_edits_then_prunes(ctx):
    s = run_arm(ctx, "B", FakeLLM())
    log = [json.loads(l) for l in (ctx.runs_dir / "arm_B" / "log.jsonl").read_text().splitlines()]
    decisions = [r["decision"] for r in log if r.get("event") == "candidate" and r["gen"] == 1]
    assert decisions == ["rejected_leakcheck", "rejected_too_many_fields", "scored"]
    assert s["E_base"] == 2 and s["E_final"] == 6
    assert s["changed_from_baseline"] == ["system_prompt"]  # sample_rows never kept or got pruned


def test_arm_a_scores_everything_and_logs_leaks(ctx):
    s = run_arm(ctx, "A", FakeLLM())
    log = [json.loads(l) for l in (ctx.runs_dir / "arm_A" / "log.jsonl").read_text().splitlines()]
    gen1 = [r for r in log if r.get("event") == "candidate" and r["gen"] == 1]
    assert all(r["decision"] == "scored" for r in gen1)
    assert gen1[0]["leak_problems"]
    assert s["E_final"] == 6
    # after both arms finish, the held-out guard opens
    run_arm(ctx, "B", FakeLLM())
    final_a = load_yaml(ctx.runs_dir / "arm_A" / "final.yaml")
    assert evaluate(ctx, final_a, "H")["passed"] == 6


def test_heldout_and_audit_end_to_end(ctx, monkeypatch, tasks, dbs, tmp_path, capsys):
    import shutil
    import sys
    from rsi import audit, heldout
    run_arm(ctx, "A", FakeLLM())
    run_arm(ctx, "B", FakeLLM())
    for mod in (heldout, audit):
        monkeypatch.setattr(mod, "RUNS", ctx.runs_dir)
        monkeypatch.setattr(mod, "load_context", lambda **kw: ctx)
    ctx.splits["n_per_split"] = 6
    monkeypatch.setattr(sys, "argv", ["heldout"])
    heldout.main()
    res = json.loads((ctx.runs_dir / "results.json").read_text())
    assert res["accuracy"]["arm_A/H"] == 1.0 and res["accuracy"]["baseline/H"] == pytest.approx(2 / 6)
    t = res["tests"]["arm_A_vs_baseline/H"]
    assert (t["improved"], t["regressed"]) == (4, 0) and t["p_mcnemar"] == pytest.approx(0.125)
    assert "arm_B_vs_arm_A/B" in res["tests"]
    # test-suite dir: one alternate db per spider database
    ts = tmp_path / "ts"
    for db in ("evo", "held"):
        (ts / db).mkdir(parents=True)
        shutil.copy(dbs[db], ts / db / f"{db}.sqlite")
    monkeypatch.setattr(sys, "argv", ["audit", "--testsuite-dir", str(ts)])
    audit.main()
    rep = json.loads((ctx.runs_dir / "audit.json").read_text())
    assert rep["arm_A/H"]["testsuite_checked"] == 6 and rep["arm_A/H"]["testsuite_false_positives"] == 0
    assert (ctx.runs_dir / "audit_bird_labels.csv").exists()
