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
    assert stats.transfer_ratio(0.04, 0.02, 0.04) is None
    assert stats.transfer_ratio(0.04, 0.08, 0.04) == pytest.approx(0.5)


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
