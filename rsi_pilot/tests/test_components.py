import json

import pytest

from rsi import stats
from rsi.config import load_yaml, ROOT
from rsi.data import Task, load_spider
from rsi.fewshot import FewShotPool
from rsi.harness import HarnessError, extract_sql, validate
from rsi.leakcheck import LeakChecker
from rsi.splits import make_splits
from rsi.sqlexec import compare, execute, score


# --- verifier -------------------------------------------------------------

def test_order_matters_only_with_order_by():
    a, b = [(1,), (2,)], [(2,), (1,)]
    assert compare(a, b, "SELECT x FROM t")
    assert not compare(a, b, "SELECT x FROM t ORDER BY x")


def test_column_permutation_allowed():
    assert compare([(1, "a"), (2, "b")], [("a", 1), ("b", 2)], "SELECT id, name FROM t")


def test_empty_gold_accepts_any_empty_result():
    # documents a known way to game result-set matching (audited in rsi.audit)
    assert compare([], [], "SELECT x FROM t WHERE 0")


def test_execute_is_read_only(dbs):
    r = execute(dbs["evo"], "INSERT INTO evo_band VALUES (9,'Z',2000)")
    assert not r.ok and "readonly" in r.error.lower()


def test_execute_timeout(dbs):
    r = execute(dbs["evo"], "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) SELECT count(*) FROM c",
                timeout_s=0.5)
    assert not r.ok and r.error == "timeout"


def test_score_wrong_reason_still_passes(dbs):
    # different logic, same rows on this db: single-db execution match cannot tell
    gold = "SELECT name FROM evo_band WHERE founded < 1995"
    pred = "SELECT name FROM evo_band WHERE band_id != 2"
    assert score(dbs["evo"], gold, pred)["pass"]


# --- stats ----------------------------------------------------------------

@pytest.mark.parametrize("b,c,p", [(6, 0, 0.03125), (5, 0, 0.0625), (7, 1, 0.0703125), (0, 0, 1.0), (3, 3, 1.0)])
def test_mcnemar_exact(b, c, p):
    assert stats.mcnemar_exact(b, c) == pytest.approx(p)


def test_bootstrap_ci_brackets_delta():
    base = {str(i): i < 20 for i in range(50)}
    new = {str(i): i < 26 for i in range(50)}
    lo, hi = stats.paired_bootstrap_ci(base, new)
    assert lo <= 0.12 <= hi and lo >= 0


def test_transfer_ratio_none_when_e_gain_small():
    assert stats.transfer_ratio(0.04, 0.02, 1) is None
    assert stats.transfer_ratio(0.04, 0.08, 4) == pytest.approx(0.5)


def test_transfer_ratio_accepts_exactly_two_tasks():
    # 0.44 - 0.40 < 2/50 in floating point; the integer check must still accept it
    assert stats.transfer_ratio(0.02, 0.44 - 0.40, 2) == pytest.approx(0.5)


# --- harness --------------------------------------------------------------

def test_baseline_harness_valid():
    validate(load_yaml(ROOT / "harness.yaml"))


@pytest.mark.parametrize("patch", [{"temperature": 0.5}, {"fewshot_k": 9}, {"sample_rows": True},
                                   {"schema_format": "json"}, {"max_retries": "2"}])
def test_harness_rejects_bad_edits(patch):
    h = load_yaml(ROOT / "harness.yaml")
    with pytest.raises(HarnessError):
        validate({**h, **patch})


def test_extract_sql():
    assert extract_sql("Here:\n```sql\nSELECT 1;\n```") == "SELECT 1"
    assert extract_sql("The answer is SELECT a FROM b;") == "SELECT a FROM b"


# --- data / splits / few-shot ---------------------------------------------

def test_load_spider_hardness(tmp_path):
    easy_sql = {"select": [False, [[3, [0, [0, "__all__", False], None]]]],
                "from": {"table_units": [["table_unit", 0]], "conds": []}, "where": [], "groupBy": [],
                "having": [], "orderBy": [], "limit": None, "intersect": None, "union": None, "except": None}
    (tmp_path / "dev.json").write_text(json.dumps([{"db_id": "x", "question": "q", "query": "SELECT count(*) FROM t",
                                                    "sql": easy_sql}]))
    t = load_spider(tmp_path, "dev")[0]
    assert t.difficulty == "easy" and t.db_path.endswith("database/x/x.sqlite")


def test_splits_disjoint_databases():
    dev = [Task(f"spider_dev_{db}_{i}", "spider_dev", f"db{db}", "", "q", "s", "", "hard" if i % 2 else "extra")
           for db in range(12) for i in range(12)]
    bird = [Task(f"bird_{i}", "bird", "b", "", "q", "s", "", "simple") for i in range(30)]
    cfg = {"seed": 1, "splits": {"n_per_split": 20, "e_hardness": ["hard", "extra"], "h_hardness": ["hard"],
                                 "b_difficulty": ["simple"], "b_fallback_difficulty": ["simple"]}}
    sp = make_splits(dev, bird, cfg)
    assert len(sp["E"]) == len(sp["H"]) == len(sp["B"]) == 20
    assert not set(sp["E_dbs"]) & set(sp["H_dbs"])
    assert sp == make_splits(dev, bird, cfg)  # deterministic


def test_fewshot_pool_rejects_eval_databases(tasks):
    with pytest.raises(ValueError):
        FewShotPool(tasks["train"], {"train"}, 0)
    with pytest.raises(ValueError):
        FewShotPool(tasks["E"], {"held"}, 0)  # not a train split
    pool = FewShotPool(tasks["train"], {"evo", "held", "bird"}, 0)
    assert len(pool.select(tasks["E"][0], 2, "lexical")) == 2


def test_pool_without_drops_shared_databases(tasks):
    # Real data: Spider train and BIRD Mini-Dev both contain formula_1.
    import dataclasses
    from rsi.runner import pool_without
    shared = dataclasses.replace(tasks["train"][0], task_id="spider_train_shared", db_id="bird")
    train = tasks["train"] + [shared]
    with pytest.raises(ValueError):
        FewShotPool(train, {"evo", "held", "bird"}, 0)
    kept = pool_without(train, {"evo", "held", "bird"})
    assert kept == tasks["train"]
    FewShotPool(kept, {"evo", "held", "bird"}, 0)


# --- leak check -----------------------------------------------------------

def test_leakcheck(tasks):
    lc = LeakChecker(tasks["E"])
    h = load_yaml(ROOT / "harness.yaml")
    assert lc.check(h, {**h, "instructions_suffix": "Join evo_album to evo_band on band_id."})
    gold = tasks["E"][2].gold_sql
    assert lc.check(h, {**h, "system_prompt": h["system_prompt"] + "\nExample: " + gold})
    assert not lc.check(h, {**h, "instructions_suffix": "Use JOIN conditions from the foreign keys."})


def test_agentwatch_checker_differs_from_spider_official():
    from rsi.sqlexec import compare, compare_agentwatch
    # AgentWatch casts and lowercases values: 1 == '1', 'Alpha' == 'alpha'
    assert compare_agentwatch([(1,)], [("1",)], "SELECT x FROM t")
    assert not compare([(1,)], [("1",)], "SELECT x FROM t")
    # Spider allows column permutation; AgentWatch does not
    assert compare([(1, "a")], [("a", 1)], "SELECT id, name FROM t")
    assert not compare_agentwatch([(1, "a")], [("a", 1)], "SELECT id, name FROM t")


def test_score_records_both_verifiers(dbs):
    s = score(dbs["evo"], "SELECT band_id, name FROM evo_band", "SELECT name, band_id FROM evo_band",
              verifier="agentwatch")
    assert s["pass"] is False and s["pass_other"] is True


def test_parse_json_strips_think_blocks():
    from rsi.llm import parse_json
    reply = '<think>maybe [1, 2] or {"x": 1}?</think>\n```json\n[{"edits": {"fewshot_k": 2}, "rationale": "r"}]\n```'
    assert parse_json(reply) == [{"edits": {"fewshot_k": 2}, "rationale": "r"}]
    assert parse_json('reasoning [ ] </think> {"benchmark_specific": false}') == {"benchmark_specific": False}


def test_keyless_openai_compatible_client():
    from rsi.llm import make_llm
    llm = make_llm({"provider": "openai_compatible", "model": "m", "base_url": "http://localhost:11434/v1",
                    "api_key_env": None})
    assert llm.key is None


def test_execute_two_statements_is_an_error_not_a_crash(tmp_path):
    import sqlite3
    db = tmp_path / "t.sqlite"
    c = sqlite3.connect(db); c.execute("create table t (x int)"); c.commit(); c.close()
    r = execute(str(db), "SELECT x FROM t; SELECT x FROM t")
    assert not r.ok and "one statement" in r.error


# --- run 2 (critique) changes ---------------------------------------------

def test_prune_decision_cost_rule():
    from rsi.evolve import prune_decision
    assert prune_decision(29, 29, 100, 100, 2, 1.25) == (True, "no_E_loss")
    # 1-task gain (within threshold 2) but 2x tokens: revert under the cost rule
    assert prune_decision(29, 28, 200, 100, 2, 1.25) == (True, "gain_within_noise_and_expensive")
    # same, cost rule off: keep
    assert prune_decision(29, 28, 200, 100, 2, None)[0] is False
    # gain at/above threshold: keep even if expensive
    assert prune_decision(29, 25, 200, 100, 2, 1.25)[0] is False


def test_edit_history_lists_earlier_candidates(tmp_path):
    from rsi.config import append_jsonl
    from rsi.evolve import edit_history, proposer_prompt
    log = tmp_path / "log.jsonl"
    assert edit_history(log) == "None yet."
    append_jsonl(log, {"event": "candidate", "gen": 1, "edits": {"sample_rows": 3}, "E_passed": 29})
    append_jsonl(log, {"event": "candidate", "gen": 1, "edits": {"fewshot_k": 2}, "decision": "rejected_critic"})
    h = edit_history(log)
    assert "sample_rows" in h and "E=29" in h and "rejected_critic" in h
    res = {"passed": 1, "n": 2}
    assert "Edits already tried" in proposer_prompt({"a": 1}, res, "T", 3, None, h)
    assert "Edits already tried" not in proposer_prompt({"a": 1}, res, "T", 3, None)


def test_ollama_llm_requires_fixed_sampling():
    from rsi.llm import OllamaLLM, make_llm
    with pytest.raises(ValueError):
        make_llm({"provider": "ollama", "model": "m", "base_url": "http://x"})
    ok = make_llm({"provider": "ollama", "model": "m", "base_url": "http://x", "temperature": 0,
                   "seed": 1, "num_ctx": 8192})
    assert isinstance(ok, OllamaLLM)


def test_splits_cap_and_empty_gold(tasks):
    import copy
    from rsi.splits import gold_nonempty, make_splits
    cfg = copy.deepcopy(load_yaml(ROOT / "frozen.yaml"))
    cfg["splits"]["n_per_split"] = 2
    cfg["splits"]["e_hardness"] = cfg["splits"]["h_hardness"] = sorted({t.difficulty for t in tasks["E"] + tasks["H"]})
    cfg["splits"]["b_difficulty"] = sorted({t.difficulty for t in tasks["B"]})
    dev = tasks["E"] + tasks["H"]
    base = make_splits(dev, tasks["B"], cfg)
    assert "max_tasks_per_db" not in base and "exclude_empty_gold" not in base  # run-1 output unchanged
    cfg["splits"]["max_tasks_per_db"] = 2
    cfg["splits"]["exclude_empty_gold"] = True
    sp = make_splits(dev, tasks["B"], cfg)
    assert sp["max_tasks_per_db"] == 2 and sp["exclude_empty_gold"] is True
    by_id = {t.task_id: t for t in dev + tasks["B"]}
    assert all(gold_nonempty(by_id[i], cfg) for i in sp["E"] + sp["H"] + sp["B"])


def test_pool_sign_test_and_table(tmp_path):
    from rsi.pool import pool, sign_test
    assert sign_test(6, 0) == 0.03125 and sign_test(0, 0) == 1.0 and sign_test(3, 3) == 1.0
    t = {"delta": 0.1, "improved": 3, "regressed": 1}
    r = {"tests": {f"{c}/{s}": t for c in ("arm_A_vs_baseline", "arm_B_vs_baseline", "arm_B_vs_arm_A")
                   for s in "EHB"}}
    for name in ("r1", "r2"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "results.json").write_text(json.dumps(r))
    md = pool([tmp_path / "r1", tmp_path / "r2"])
    assert "| arm_B vs arm_A | H | 6 | 2 | +4 |" in md


def _mkdb(path, rows):
    import sqlite3
    c = sqlite3.connect(path)
    c.execute("create table t(x int)")
    c.executemany("insert into t values (?)", [(r,) for r in rows])
    c.commit(); c.close()


def test_testsuite_pass_none_when_gold_fails_everywhere(tmp_path):
    from rsi.audit import testsuite_pass
    d = tmp_path / "db1"; d.mkdir()
    _mkdb(str(d / "a.sqlite"), [1, 2])
    # gold references a missing table on every test database: nothing was checked
    assert testsuite_pass(tmp_path, "db1", "select y from missing", "select x from t", True, 5) is None
    assert testsuite_pass(tmp_path, "db1", "select x from t", "select x from t", True, 5) is True
    assert testsuite_pass(tmp_path, "db1", "select x from t", "select 1", True, 5) is False
    assert testsuite_pass(tmp_path, "nodb", "select x from t", "select x from t", True, 5) is None


# ---- run 4 ----

def test_random_edit_is_valid_and_bounded():
    import random as _r
    from rsi.edits import random_edit
    from rsi.harness import diff_fields
    base = validate(load_yaml(ROOT / "harness.yaml"))
    rng = _r.Random(0)
    for _ in range(200):
        e = random_edit(base, rng, 3)
        new = validate({**base, **e})
        assert 1 <= len(diff_fields(base, new)) <= 3


def test_cosine_budget_anneals_from_max_to_min():
    from rsi.edits import cosine_budget
    b = [cosine_budget(g, 10, 3, 1) for g in range(1, 11)]
    assert b[0] == 3 and b[-1] == 1 and b == sorted(b, reverse=True)


def test_placebo_threshold():
    from rsi.edits import placebo_threshold
    # all placebo deltas 0: the best of 3 never reaches +1, so the floor applies
    assert placebo_threshold([0] * 10, 3, 0.05, 2) == 2
    # placebo deltas reach +4: best-of-3 reaches 4 with p = 1 - 0.9^3 > 0.05, so t = 5
    assert placebo_threshold([-3, -2, -1, 0, 0, 1, 1, 2, 3, 4], 3, 0.05, 2) == 5


def test_splits_v4_disjoint_and_fixed_heldout(dbs):
    from rsi.splits import make_splits_v4
    dev = [Task(f"spider_dev_{i}", "spider_dev", f"dev{i % 2}", dbs["held"], "q", "SELECT 1", "", "hard")
           for i in range(10)]
    train = [Task(f"spider_train_{i}", "spider_train", f"tr{i % 5}", dbs["train"], f"q{i}", "SELECT 1", "", "extra")
             for i in range(40)]
    bird = [Task(f"bird_{i}", "bird", "b", dbs["bird"], "q", "SELECT 1", "", "simple") for i in range(7)]
    cfg = {"seed": 1, "eval": {"exec_timeout_s": 5, "max_result_rows": 10},
           "splits": {"n_e": 8, "n_e2": 8, "max_tasks_per_db": 2, "e_hardness": ["hard", "extra"],
                      "h_hardness": ["hard", "extra"], "b_difficulty": ["simple"], "exclude_empty_gold": True}}
    a = make_splits_v4(dev, train, bird, cfg)
    assert len(a["E"]) == 8 and len(a["E2"]) == 8 and not set(a["E"]) & set(a["E2"])
    assert len(a["H"]) == 10 and len(a["B"]) == 7
    b = make_splits_v4(dev, train, bird, {**cfg, "seed": 2})
    assert a["H"] == b["H"] and a["B"] == b["B"]          # held-out sets do not depend on the seed


def test_wilcoxon_and_holm():
    from rsi.pool import holm, wilcoxon_exact
    assert wilcoxon_exact([3] * 10) == pytest.approx(2 / 1024)
    assert wilcoxon_exact([0, 0, 0]) == 1.0
    assert wilcoxon_exact([1, -1, 2, -2]) == 1.0
    assert holm({"a": 0.01, "b": 0.04, "c": 0.03}) == {"a": 0.03, "c": 0.06, "b": 0.06}
