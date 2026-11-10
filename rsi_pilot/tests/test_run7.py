"""Run 7: replay with task weights, bootstrap, config variants, task sampling. No model calls."""
import random

import pytest

from rsi import replay, run7, stage0
from rsi.config import ROOT, load_yaml


def _bank(n_edits=20, n_tasks=120, flip=0.25, seed=0):
    """Edits with no real effect; the proxy is truth with `flip` of its verdicts inverted."""
    rng = random.Random(seed)
    diff = [rng.uniform(0.3, 0.8) for _ in range(n_tasks)]
    run = lambda: [float(rng.random() < d) for d in diff]
    noisy = lambda row: [1.0 - x if rng.random() < flip else x for x in row]
    t0 = run()
    t = [run() for _ in range(n_edits)]
    return t, {"truth": t, "judge": [noisy(r) for r in t]}, t0, {"truth": t0, "judge": noisy(t0)}


def test_curse_boot_matches_committed_replay():
    t, P, t0, P0 = _bank()
    got = run7.curse_boot(t, P, t0, P0, k=8, m=60, rounds=1500, rng=random.Random(3))
    for s in P:
        want = replay.replay(t, P[s], t0, P0[s], k=8, m=60, rule="greedy", rounds=1500, seed=3)
        for mine, theirs in (("noise", "noise"), ("bias", "bias"), ("real", "real"), ("kept", "kept")):
            assert got[s][mine] == pytest.approx(want[theirs], abs=1e-9)


def test_noisier_selector_has_a_larger_curse():
    t, P, t0, P0 = _bank(n_edits=30, n_tasks=200)
    d = run7._derived(run7.curse_boot(t, P, t0, P0, k=8, m=100, rounds=2000, rng=random.Random(1)))
    assert d["truth"]["multiplier"] == 1.0
    assert d["truth"]["curse"] > 0
    assert d["judge"]["multiplier"] > 1.1
    assert d["truth"]["bias_minus_random"] == 0.0


def test_weights_keep_selection_and_fresh_disjoint():
    t, P, t0, P0 = _bank(n_edits=6, n_tasks=40)
    w = [0.0] * 40
    w[0] = w[1] = 5.0                                    # only two tasks carry weight
    out = run7.curse_boot(t, P, t0, P0, k=3, m=20, rounds=200, rng=random.Random(0), weights=w)
    assert all(abs(v) <= 2.0 for a in out.values() for v in a.values())   # finite, bounded gains
    w = [0.0] * 40
    w[0] = 3.0                                           # one task: no round has both halves
    out = run7.curse_boot(t, P, t0, P0, k=3, m=20, rounds=50, rng=random.Random(0), weights=w)
    assert out["truth"]["noise"] == 0.0


def test_bootstrap_returns_ordered_intervals():
    t, P, t0, P0 = _bank(n_edits=10, n_tasks=60)
    ci = run7.bootstrap(t, P, t0, P0, k=4, m=30, boots=30, rounds=60, seed=5)
    lo, hi = ci["judge"]["multiplier"]
    assert lo <= hi
    assert ci["truth"]["multiplier"] == [1.0, 1.0]
    joint = run7.bootstrap(t, P, t0, P0, k=4, m=30, boots=30, rounds=60, seed=5, resample_edits=True)
    assert joint["judge"]["multiplier"] != ci["judge"]["multiplier"]


def test_variants_change_only_the_judge_block():
    cfg = load_yaml(ROOT / "frozen_v7.yaml")
    v, r = run7.variant(cfg, "verdict"), run7.variant(cfg, "repeat")
    assert v["judge"]["style"] == "verdict" and v["judge"]["num_predict"] == 256
    assert v["judge"]["model"] == cfg["judge"]["model"] and v["student"] == cfg["student"]
    assert r["judge"] == {**cfg["judge"], "repeat": 1}
    assert cfg["judge"]["style"] == "recompute"          # the frozen config itself is untouched
    assert cfg["analysis"]["m"] * 2 == cfg["data"]["n_tasks"]


def test_repeat_subset_is_baselines_plus_first_edits():
    cfg = load_yaml(ROOT / "frozen_v7.yaml")
    jobs = run7.subset(cfg, "repeat")
    assert [j[1] for j in jobs[:3]] == ["baseline"] * 3
    assert len(jobs) == 3 + cfg["repeat_edits"]
    assert len(run7.subset(cfg, "verdict")) == 43        # 3 baselines + 40 catalog edits, weak anchor only


def test_run7_tasks_are_disjoint_from_run6():
    if not (ROOT / "data/finqa/dev.json").exists():
        pytest.skip("FinQA dev file not present")
    ids = lambda f: {t.task_id for t in stage0.sample_tasks(load_yaml(ROOT / f))}
    new = ids("frozen_v7.yaml")
    assert len(new) == 300
    assert not new & ids("frozen_v6_stage0.yaml")
    assert not new & ids("frozen_v6_stage1.yaml")


def test_run7_end_to_end_with_scripted_models(tmp_path):
    import json
    from types import SimpleNamespace

    from rsi import bank
    from rsi.domains import finqa
    from rsi.student import Completion

    RAW = [{"id": "ACME/2020/page_1.pdf-1", "pre_text": ["acme reported results ."],
            "table": [["", "2020", "2019"], ["revenue", "120.0", "100.0"], ["costs", "80.0", "70.0"]],
            "post_text": ["amounts in millions ."],
            "qa": {"question": "what was the percentage change in revenue?", "exe_ans": 0.2}},
           {"id": "ACME/2020/page_1.pdf-2", "pre_text": [], "table": [], "post_text": ["revenue rose ."],
            "qa": {"question": "did revenue rise?", "exe_ans": "yes"}}]
    f = tmp_path / "dev.json"
    f.write_text(json.dumps(RAW), encoding="utf-8")
    tasks = finqa.load_finqa(f) * 3                  # 6 tasks, ids repeat; enough for plumbing
    cfg = {"out_dir": str(tmp_path / "out"), "baseline_repeats": 2, "seed": 1, "repeat_edits": 2,
           "student": {"model": "fake"}, "judge": {"model": "fake", "style": "recompute", "num_predict": 700},
           "judge_verdict": {"style": "verdict", "num_predict": 256},
           "analysis": {"k": 4, "m": 3, "rounds": 50, "boots": 25, "boot_rounds": 10, "grid_k": [4], "grid_m": [2]}}
    calls = {"n": 0, "s": 0}

    def student(messages):                           # answer changes from call to call, so truth varies
        calls["s"] += 1
        return Completion('{"tool": "submit", "arg": "%s"}' % ("20%" if calls["s"] % 4 else "yes"), 1, 1, 0.0)

    def judge(system, user, max_tokens=256):         # verdict flips on every call: an unstable judge
        calls["n"] += 1
        return SimpleNamespace(text=json.dumps({"correct": calls["n"] % 3 == 0, "score": 5}))

    assert bank.build(cfg, tasks, student, judge, 1)["evaluated"] == 2 + 40
    assert run7.regrade(cfg, tasks, "verdict", judge, 1)["graded"] == 42
    rep = run7.regrade(cfg, tasks, "repeat", judge, 1)
    assert rep["graded"] == 4 and rep["not_in_bank"] == 0
    assert run7.regrade(cfg, tasks, "repeat", judge, 1)["seconds_per_harness"] is None     # all cached
    out = run7.analyze(cfg, tasks)
    assert out["selectors"] == ["truth", "p1", "p2", "p2v"] and out["n_edits"] == 40
    assert out["point"]["truth"]["multiplier_theory"] in (1.0, None)
    assert set(out["interval95"]) == set(out["selectors"]) and "k4_m2" in out["grid"]
    assert set(out["interval95_tasks_and_edits"]) == set(out["selectors"])
    assert out["judge_repeat"]["harnesses"] == 4 and 0 <= out["judge_repeat"]["p2_flip_rate"] <= 1
    json.dumps(out)                                  # serialisable
