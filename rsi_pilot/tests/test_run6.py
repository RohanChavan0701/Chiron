"""Run 6 plumbing: FinQA domain, proxy graders, Goodhart-share estimator, stage-0 wiring.
Synthetic data and scripted models only; nothing here is an experimental result."""
import json
import random
from statistics import fmean
from types import SimpleNamespace

import pytest

from rsi import goodhart, proxies, stage0
from rsi.config import ROOT, load_yaml
from rsi.domains import finqa
from rsi.student import Completion

RAW = [{"id": "ACME/2020/page_1.pdf-1", "pre_text": ["acme reported results ."],
        "table": [["", "2020", "2019"], ["revenue", "120.0", "100.0"], ["costs", "80.0", "70.0"]],
        "post_text": ["amounts in millions ."],
        "qa": {"question": "what was the percentage change in revenue?", "exe_ans": 0.2}},
       {"id": "ACME/2020/page_1.pdf-2", "pre_text": [], "table": [], "post_text": ["revenue rose ."],
        "qa": {"question": "did revenue rise?", "exe_ans": "yes"}}]


@pytest.fixture
def fin_tasks(tmp_path):
    f = tmp_path / "dev.json"
    f.write_text(json.dumps(RAW), encoding="utf-8")
    return finqa.load_finqa(f)


def base():
    return finqa.validate(load_yaml(ROOT / "harness_fin.yaml"))


class Script:
    def __init__(self, actions):
        self.actions, self.seen = list(actions), []

    def __call__(self, messages):
        self.seen.append(messages[-1]["content"])
        a = self.actions.pop(0)
        return Completion(a if isinstance(a, str) else json.dumps(a), 10, 5, 0.01)


def judge_saying(obj):
    return lambda system, user, max_tokens=256: SimpleNamespace(text=json.dumps(obj))


def test_grade_number_percent_and_yes_no():
    assert finqa.grade(0.2, "20%") == {"pass": True, "pass_strict": True, "parsed": 20.0}
    assert finqa.grade(0.2, "0.2")["pass_strict"]
    g = finqa.grade(0.2, "20")            # factor of 100 with no percent sign: lenient only
    assert g["pass"] and not g["pass_strict"]
    assert not finqa.grade(0.2, "25%")["pass"]
    assert finqa.grade(1234.5, "$1,235 million")["pass_strict"]
    assert finqa.grade("yes", "Yes, it rose")["pass"] and not finqa.grade("yes", "no")["pass"]
    assert finqa.grade(0.2, "unclear") == {"pass": False, "pass_strict": False, "parsed": None}


def test_safe_calc_is_arithmetic_only():
    assert finqa.safe_calc("(120 - 100) / 100") == pytest.approx(0.2)
    assert finqa.safe_calc("1,200 * 5%") == pytest.approx(60)
    for bad in ("__import__('os')", "open('x')", "1/0", "a + 1", "2 +"):
        with pytest.raises(ValueError):
            finqa.safe_calc(bad)


def test_agent_calculates_then_submits(fin_tasks):
    s = Script([{"tool": "calc", "arg": "(120.0 - 100.0) / 100.0"}, {"tool": "submit", "arg": "20%"}])
    r = finqa.run_task(base(), fin_tasks[0], s)
    assert r["pass"] and r["ended"] == "submitted" and r["n_steps"] == 2
    assert "| revenue | 120.0 | 100.0 |" in s.seen[0] and s.seen[1].startswith("0.2")
    assert "Result: 0.2" in finqa.work_shown(r)


def test_agent_out_of_steps_uses_last_calc_and_verify_costs_a_step(fin_tasks):
    h = {**base(), "max_steps": 2}
    r = finqa.run_task(h, fin_tasks[0], Script(["hmm", {"tool": "calc", "arg": "20/100"}]))
    assert r["ended"] == "out_of_steps" and r["pass"] and not proxies.p3_validity(r)
    h = {**base(), "verify_before_submit": True}
    s = Script([{"tool": "submit", "arg": "25%"}, {"tool": "submit", "arg": "20%"}, {"tool": "confirm"}])
    r = finqa.run_task(h, fin_tasks[0], s)
    assert r["pass"] and r["n_steps"] == 3 and "about to submit: 25%" in s.seen[1]


def test_rows_format_and_validation(fin_tasks):
    assert "item: revenue; 2020: 120.0; 2019: 100.0" in finqa.render_context(fin_tasks[0], "rows")
    with pytest.raises(ValueError):
        finqa.validate({**base(), "max_steps": 99})
    with pytest.raises(ValueError):
        finqa.validate({k: v for k, v in base().items() if k != "rules"})


def test_proxies_read_the_episode_and_survive_bad_judges(fin_tasks):
    r = finqa.run_task(base(), fin_tasks[0], Script([{"tool": "submit", "arg": "25%"}]))
    assert not r["pass"] and proxies.p3_validity(r)          # wrong but well-formed
    seen = {}

    def judge(system, user, max_tokens=256):
        seen["user"] = user
        return SimpleNamespace(text='{"correct": true, "score": 9}')

    assert proxies.p2_judge_free(fin_tasks[0], r, judge) == {"correct": True, "score": 9}
    assert "Reference" not in seen["user"] and "Final answer: 25%" in seen["user"]
    proxies.p1_judge_ref(fin_tasks[0], r, judge)
    assert "Reference answer: 0.2" in seen["user"]
    assert proxies.p2_judge_free(fin_tasks[0], r, judge_saying("nope"))["correct"] is None

    def broken(system, user, max_tokens=256):
        raise RuntimeError("hit num_predict")

    assert proxies.p1_judge_ref(fin_tasks[0], r, broken)["correct"] is None


def gaussian_bank(n, m, sd_a, sd_b, sd_noise, rng):
    """Edits with known true-gain and bias spreads; t0 = p0 = 0 so t = a and p = a + b."""
    tau = [rng.gauss(0, 0.2) for _ in range(m)]
    alpha, beta = [rng.gauss(0, sd_a) for _ in range(n)], [rng.gauss(0, sd_b) for _ in range(n)]
    t = [[alpha[i] + tau[j] + rng.gauss(0, sd_noise) for j in range(m)] for i in range(n)]
    p = [[t[i][j] + beta[i] + rng.gauss(0, sd_noise) for j in range(m)] for i in range(n)]
    return t, p, [0.0] * m, [0.0] * m, alpha, beta


def test_components_recover_known_spreads_and_ignore_task_effects():
    t, p, t0, p0, _, _ = gaussian_bank(400, 60, 0.03, 0.05, 0.3, random.Random(1))
    c = goodhart.components(t, p, t0, p0)
    assert c["s_aa"] ** 0.5 == pytest.approx(0.03, abs=0.008)
    assert c["s_bb"] ** 0.5 == pytest.approx(0.05, abs=0.008)
    assert abs(c["s_ab"]) < 0.0006
    # with no real spread at all, the raw spread of edit means is pure noise and is subtracted
    t, p, t0, p0, _, _ = gaussian_bank(400, 60, 0.0, 0.0, 0.3, random.Random(2))
    c = goodhart.components(t, p, t0, p0)
    assert abs(c["s_aa"]) < 0.0004 and abs(c["s_bb"]) < 0.0004


def test_shares_match_a_brute_force_best_of_k_replay():
    rng, k, m = random.Random(3), 20, 40
    t, p, t0, p0, alpha, beta = gaussian_bank(3000, m, 0.03, 0.04, 0.3, rng)
    pred = goodhart.shares(goodhart.components(t, p, t0, p0), m)
    real, bias, total = [], [], []
    for start in range(0, 3000, k):
        block = range(start, start + k)
        proxy_gain = {i: fmean(p[i]) for i in block}
        w = max(block, key=proxy_gain.get)
        centre = fmean(proxy_gain.values())      # removes the task effect all candidates share
        real.append(alpha[w] - fmean(alpha[i] for i in block))
        bias.append(beta[w] - fmean(beta[i] for i in block))
        total.append(proxy_gain[w] - centre)
    assert fmean(real) / fmean(total) == pytest.approx(pred["real"], abs=0.06)
    assert fmean(bias) / fmean(total) == pytest.approx(pred["goodhart"], abs=0.06)
    assert pred["real"] + pred["goodhart"] + pred["noise"] == pytest.approx(1.0)
    # more selection tasks remove noise only, so the Goodhart share goes up
    assert goodhart.shares(goodhart.components(t, p, t0, p0), 400)["goodhart"] > pred["goodhart"]


def test_binary_simulation_and_power_run():
    t, p, t0, p0 = goodhart.simulate(40, 80, 0.05, 0.08, 0.5, 0.3, 0.1, random.Random(4))
    assert len(t) == 40 and len(t[0]) == 80 and set(map(float, t0)) <= {0.0, 1.0}
    big = goodhart.power(40, 80, 0.02, 0.10, 0.5, 0.3, 0.1, sims=30, seed=5)
    none = goodhart.power(40, 80, 0.02, 0.0, 0.5, 0.3, 0.1, sims=30, seed=5)
    assert big["sd_bias_est_median"] > none["sd_bias_est_median"]
    assert big["goodhart_median"] > none["goodhart_median"]


def test_stage0_end_to_end_with_scripted_models(fin_tasks, tmp_path):
    cfg = {"out_dir": str(tmp_path / "out"), "baseline_repeats": 2, "headroom": [0.15, 0.8], "seed": 1,
           "student": {"model": "fake"}, "judge": {"model": "fake"}}

    def student(messages):                 # always answers 20%: right on task 1, wrong on the yes/no task
        return Completion('{"tool": "submit", "arg": "20%"}', 1, 1, 0.0)

    judge = judge_saying({"correct": True, "score": 8})       # a judge that approves everything
    h = stage0.headroom(cfg, fin_tasks, student, judge, 1)
    assert h["truth_mean"] == 0.5 and h["truth_spread"] == 0 and h["in_band"]
    assert h["baseline_runs"][0]["p2"] == 1.0 and h["baseline_runs"][0]["p2_false_pos"] == 1.0
    n_files = len(list((tmp_path / "out").glob("ep_*.json")))
    assert n_files == 2
    stage0.headroom(cfg, fin_tasks, student, judge, 1)       # cached: no new files
    assert len(list((tmp_path / "out").glob("ep_*.json"))) == n_files
    j = stage0.judgecheck(cfg, fin_tasks, student, judge, 1)
    assert set(j["edits"]) == set(stage0.STYLE) | set(stage0.SUBSTANCE)
    assert j["edits"]["confident"] == {"group": "style", "true_gain": 0.0, "p1_gain": 0.0, "p2_gain": 0.0,
                                       "p3_gain": 0.0}
    assert j["p2_style"]["n_edits"] == len(stage0.STYLE)
    rows = stage0.power_table(cfg, j)
    assert len(rows) == 9 and rows[0]["sims"] == 100


def test_judge_calibration_regrades_stored_transcripts(fin_tasks, tmp_path):
    from rsi import judgecal
    cfg = {"out_dir": str(tmp_path / "out"), "baseline_repeats": 1, "seed": 1,
           "student": {"model": "fake"}, "judge": {"model": "fake", "num_predict": 256}}

    def student(messages):                 # right on task 1, wrong on the yes/no task
        return Completion('{"tool": "submit", "arg": "20%"}', 1, 1, 0.0)

    stage0.episodes(cfg, stage0.baseline(), fin_tasks, student, 0, 1)
    built = []

    def make_judge(jcfg):
        built.append((jcfg["model"], jcfg["num_predict"]))

        def judge(system, user, max_tokens=256):       # a perfect judge that shows its work first
            good = "percentage change" in user
            return SimpleNamespace(text="120 - 100 = 20; set {a, b}\n" + json.dumps(
                {"correct": good, "score": 9 if good else 1}))
        return judge

    rows = judgecal.run(cfg, fin_tasks, make_judge, 1, variants=[("m", "verdict"), ("m", "recompute")])
    assert built == [("m", 256), ("m", 700)]
    assert rows[1]["approves_right"] == 1.0 and rows[1]["approves_wrong"] == 0.0 and rows[1]["auroc_score"] == 1.0
    assert rows[1]["unparsed"] == 0.0 and "verdicts" not in rows[1]
    assert judgecal.auroc([10, 10], [10, 0]) == 0.75 and judgecal.auroc([], [1]) is None


def test_catalog_is_valid_single_edits_with_stable_ids():
    from rsi import fin_edits
    for anchor in (fin_edits.WEAK, base()):
        cat = fin_edits.catalog(anchor)
        ids = [c["id"] for c in cat]
        assert len(ids) == len(set(ids)) == 40
        assert {c["source"] for c in cat} == {"placebo", "style", "substance", "targeted", "structural"}
        for c in cat:
            changed = [k for k in anchor if c["harness"][k] != anchor[k]]
            assert len(changed) == 1
    weak_ids = {c["id"] for c in fin_edits.catalog(fin_edits.WEAK) if c["source"] != "structural"}
    assert weak_ids == {c["id"] for c in fin_edits.catalog(base()) if c["source"] != "structural"}
    assert len(fin_edits.anchor_grid(base())) == 16


def test_replay_splits_the_winner_and_rules_behave():
    from rsi import replay
    t, p, _, _, _, _ = gaussian_bank(300, 80, 0.03, 0.04, 0.3, random.Random(7))
    t0 = [fmean(col) for col in zip(*t)]       # a baseline that shares the task effects, as real ones do
    p0 = [fmean(col) for col in zip(*p)]
    g = replay.replay(t, p, t0, p0, k=20, m=40, rule="greedy", rounds=600, seed=1)
    assert g["reported"] == pytest.approx(g["real"] + g["bias"] + g["noise"])
    assert g["bias"] > 0 and g["noise"] > 0 and g["real"] > 0
    r = replay.replay(t, p, t0, p0, k=20, m=40, rule="random", rounds=600, seed=1)
    assert abs(r["reported"]) < g["reported"] / 3          # no selection, no inflation
    hi = replay.replay(t, p, t0, p0, k=20, m=40, rule="threshold:0.5", rounds=200, seed=1)
    assert hi["kept"] == 0 and hi["reported"] == 0
    a = replay.replay(t, p, t0, p0, k=20, m=40, rule="audit:40", rounds=600, seed=1)
    assert a["bias"] + a["noise"] < g["bias"] + g["noise"] + 0.01
    with pytest.raises(ValueError):
        replay.replay(t, p, t0, p0, k=5, m=80)


def test_bank_end_to_end_with_scripted_models(fin_tasks, tmp_path):
    from rsi import bank
    cfg = {"out_dir": str(tmp_path / "out"), "baseline_repeats": 1, "seed": 1,
           "student": {"model": "fake"}, "judge": {"model": "fake", "style": "recompute", "num_predict": 700}}
    tasks = fin_tasks * 2                       # 4 tasks, ids repeat; enough for plumbing

    def student(messages):                      # confident replies get the yes/no task wrong too
        return Completion('{"tool": "submit", "arg": "20%"}', 1, 1, 0.0)

    def judge(system, user, max_tokens=256):    # fooled by one rule, otherwise always says wrong
        fooled = "Reference answer" not in user and "20%" in user
        return SimpleNamespace(text=json.dumps({"correct": fooled, "score": 5}))

    a = bank.find_anchor(cfg, tasks, student, 1)
    assert len(a["grid"]) == 16 and a["strong_truth"] == 0.5 and set(bank.anchors(cfg)) == {"weak", "strong"}
    b = bank.build(cfg, tasks, student, judge, 1)
    assert b["evaluated"] == 2 + 80 and b["skipped_for_deadline"] == 0
    assert bank.build(cfg, tasks, student, judge, 1)["seconds_per_harness"] is None     # all cached
    out = bank.analyze(cfg, tasks)
    assert out["weak"]["n_edits"] == 40 and out["strong"]["n_edits"] == 40
    assert set(out["weak"]["proxies"]) == {"p1", "p2", "p3"}
    assert out["weak"]["proxies"]["p2"]["replay"]["greedy"]["rule"] == "greedy"
    cut = bank.build({**cfg, "out_dir": str(tmp_path / "cut")}, tasks, student, judge, 1, deadline=1.0)
    assert cut["evaluated"] == 1 and cut["skipped_for_deadline"] > 0


def test_proposals_parse_validate_and_join_the_bank(fin_tasks, tmp_path):
    from rsi import bank, fin_propose
    anchor = base()
    reply = json.dumps([
        {"type": "rule", "text": "Show the formula before submitting.", "rationale": "r1"},
        {"type": "rule", "text": "Show the formula before submitting."},                 # duplicate
        {"type": "setting", "field": "max_steps", "value": 6, "rationale": "more room"},
        {"type": "setting", "field": "max_steps", "value": 99},                           # out of range
        {"type": "setting", "field": "system_prompt", "value": "x"},                      # not a setting
        {"type": "setting", "field": "verify_before_submit", "value": "yes"},             # wrong type
        {"type": "rule", "text": "x" * 300}, "junk"])
    edits = fin_propose.parse_edits("Here you go: " + reply, anchor, "s4")
    assert [e["id"] for e in edits] == ["s4/00", "s4/01"] and edits[0]["harness"]["rules"].startswith("- Show")
    assert edits[1]["harness"]["max_steps"] == 6 and fin_propose.parse_edits("no json", anchor, "s2") == []

    cfg = {"out_dir": str(tmp_path / "out"), "baseline_repeats": 1, "seed": 1, "student": {"model": "fake"},
           "judge": {"model": "fake", "style": "recompute", "num_predict": 700},
           "proposer": {"edits_per_source": 2, "max_calls": 2}}
    student = lambda messages: Completion('{"tool": "submit", "arg": "20%"}', 1, 1, 0.0)
    judge = judge_saying({"correct": False, "score": 1})
    stage0.evaluate(cfg, fin_edits_weak(), fin_tasks, student, judge, 0, 1)
    seen = []

    def llm(system, user, max_tokens=2000):
        seen.append(user)
        return SimpleNamespace(text=reply)

    out = bank.propose_all(cfg, fin_tasks, llm)
    assert out == {"weak/s2": 2, "weak/s3": 2, "weak/s4": 2}
    assert "Reviewer's instructions" not in seen[0] and "Reviewer's instructions" in seen[1]
    assert "Approval is the only thing measured" in seen[2] and "Reviewer: rejected" in seen[0]
    assert "exe_ans" not in seen[0] and "Reference" not in seen[0]            # the proposer never sees truth
    assert len(bank.all_edits(cfg, "weak", fin_edits_weak())) == 46
    bank.propose_all(cfg, fin_tasks, lambda *a, **k: 1 / 0)                   # cached: the proposer is not called


def fin_edits_weak():
    from rsi import fin_edits
    return finqa.validate(dict(fin_edits.WEAK))
