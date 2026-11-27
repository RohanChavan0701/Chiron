"""Offline checks of cloud/modal_ablation.py: no Modal token, no network. Only the pure helpers
and the declared function settings are tested; nothing here runs on Modal."""
import ast
import warnings
from pathlib import Path

import pytest

modal = pytest.importorskip("modal")

from cloud import modal_ablation as M  # noqa: E402

SRC = Path(M.__file__).read_text(encoding="utf-8")
REPO = Path(M.__file__).resolve().parents[1]

PS_GPU = """NAME                   ID              SIZE      PROCESSOR    CONTEXT    UNTIL
qwen2.5:7b-instruct    845dbda0ea48    6.0 GB    100% GPU     8192       Forever
"""
PS_SPLIT = """NAME                   ID              SIZE      PROCESSOR          CONTEXT    UNTIL
qwen2.5:7b-instruct    845dbda0ea48    9.8 GB    23%/77% CPU/GPU    8192       Forever
"""
PS_CPU = """NAME                   ID              SIZE      PROCESSOR    CONTEXT    UNTIL
qwen2.5:7b-instruct    845dbda0ea48    6.0 GB    100% CPU     8192       Forever
"""
PS_OTHER = """NAME                    ID              SIZE     PROCESSOR    CONTEXT    UNTIL
qwen2.5:32b-instruct    9f13ba1299af    21 GB    100% GPU     8192       4 minutes from now
"""
PS_EMPTY = "NAME    ID    SIZE    PROCESSOR    CONTEXT    UNTIL\n"


def _spec(fn):
    from modal._utils.async_utils import synchronizer
    return synchronizer._translate_in(fn)._spec


def _decorators():
    """name -> {keyword: ast node} for every @app.function(...) in the module."""
    out = {}
    for node in ast.parse(SRC).body:
        if isinstance(node, ast.FunctionDef):
            for d in node.decorator_list:
                if isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "function":
                    out[node.name] = {k.arg: k.value for k in d.keywords}
    return out


# ---------------- import and declarations ----------------

def test_imports_and_registers_without_credentials():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assert set(M.app.registered_functions) == {"prepare", "run_seed", "orchestrate"}
        assert set(M.app.registered_entrypoints) == {"main"}


def test_no_function_declares_retries():
    decs = _decorators()
    assert set(decs) == {"prepare", "run_seed", "orchestrate"}
    for name, kw in decs.items():
        assert "retries" not in kw, f"{name} declares retries"
    assert "retries=" not in SRC.replace("retries=0", "")


def test_seed_function_settings():
    kw = _decorators()["run_seed"]
    assert ast.unparse(kw["gpu"]) == "GPU"
    assert ast.unparse(kw["timeout"]) == "MAX_SEED_MINUTES * 60"
    assert ast.unparse(kw["max_containers"]) == "MAX_CONTAINERS"
    assert ast.unparse(kw["single_use_containers"]) == "True"
    s = _spec(M.run_seed)
    assert s.gpus == M.GPU == "A100-80GB"
    assert s.cpu == (M.SEED_CPU, M.SEED_CPU) and s.memory == (M.SEED_MEM_MIB, M.SEED_MEM_MIB)
    assert set(s.volumes) == {M.DATA_MOUNT, M.MODELS_MOUNT, M.OUT_MOUNT}
    assert M.MAX_CONTAINERS == 6 and M.MAX_STARTS_PER_SEED == 2
    assert _spec(M.prepare).gpus is None and _spec(M.orchestrate).gpus is None
    assert ast.unparse(_decorators()["orchestrate"]["nonpreemptible"]) == "True"
    assert M.GPU in M.EXPECTED_GPU and M.GPU in M.GPU_PRICE_PER_S


def test_ollama_pin_and_settings():
    assert M.OLLAMA_VERSION == "0.40.13" and M.OLLAMA_PORT == 11435 and M.WORKERS == 8
    env = M._ollama_env("/tmp/m")
    assert env["OLLAMA_HOST"] == "127.0.0.1:11435" and env["OLLAMA_NUM_PARALLEL"] == "8"
    assert env["OLLAMA_KEEP_ALIVE"] == "-1" and "OLLAMA_FLASH_ATTENTION" not in env
    assert "OLLAMA_VERSION={OLLAMA_VERSION} sh" in SRC


def test_no_result_numbers_leave_the_container():
    """run_seed returns only these keys; its prints never mention accuracy or passes."""
    body = SRC[SRC.index("def run_seed"):SRC.index("def orchestrate")]
    body = body[body.index('never an accuracy or a pass count."""') + 40:]   # skip the docstring
    assert '{"seed": seed, "ok": False, "duration_s": 0, "error": "", "attempt": 0, "skipped": False}' in body
    for word in ("accuracy", "passed", "ablation.json\").read"):
        assert word not in body


# ---------------- pure helpers ----------------

def test_parse_seeds():
    assert M.parse_seeds("all") == list(M.SEEDS)
    assert M.parse_seeds("20261214, 20261211,20261214") == [20261211, 20261214]
    for bad in ("", "2026121", "20261217", "all,20261211", "x"):
        with pytest.raises(ValueError):
            M.parse_seeds(bad)


def test_cost_arithmetic():
    rate = 0.000694 + 8 * 0.0000131 + 32 * 0.00000222
    assert M.seed_rate_per_s() == pytest.approx(rate)
    assert M.attempt_worst_usd(75) == pytest.approx(80 * 60 * rate)
    p = M.cost_plan(6)
    assert p["first_round_worst"] == pytest.approx(6 * 80 * 60 * rate + M.overhead_worst_usd())
    assert p["all_twice_worst"] > M.BUDGET_USD          # why reruns are budget-admitted
    assert M.cost_plan(6, 90)["all_twice_worst"] == pytest.approx(12 * 95 * 60 * rate + M.overhead_worst_usd())
    assert p["first_round_worst"] <= M.BUDGET_USD and p["guaranteed_retries"] >= 1
    assert 0 < M.overhead_worst_usd() < 1
    assert M.MAX_SEED_MINUTES >= 60


def test_cost_guard_refuses():
    assert M.check_budget(6)["budget"] == 30.0
    with pytest.raises(M.CostGuardError):
        M.check_budget(6, minutes=90)                      # 6 x 95 min alone passes 30 USD
    with pytest.raises(M.CostGuardError):
        M.check_budget(6, budget=20.0)
    with pytest.raises(M.CostGuardError):
        M.seed_rate_per_s("H100")


def test_retries_allowed():
    worst = M.attempt_worst_usd()
    assert M.billed_estimate_usd(None) == pytest.approx(worst)
    assert M.billed_estimate_usd(10 ** 6) == pytest.approx(worst)
    # every first attempt hit the timeout: exactly the guaranteed reruns fit
    assert M.retries_allowed(6 * worst, 6) == M.cost_plan(6)["guaranteed_retries"] == 1
    # typical 45 min sessions, three failures: all three rerun
    assert M.retries_allowed(6 * M.billed_estimate_usd(45 * 60), 3) == 3
    assert M.retries_allowed(M.BUDGET_USD, 2) == 0
    assert M.retries_allowed(0.0, 0) == 0
    spent, k = 6 * worst, M.retries_allowed(6 * worst, 6)
    assert spent + k * worst + M.overhead_worst_usd() <= M.BUDGET_USD


def test_out_volume_layout():
    s = 20261213
    assert M.out_seed_dir(s) == "s20261213"
    assert M.repo_result_paths(s) == ["runs_v5/s20261213/ablation", "runs_v5/s20261213/heldout_access.jsonl",
                                      "runs_v5/s20261213/logs", "splits_v5_s20261213.json"]
    assert M.out_repo_path(s, "runs_v5/s20261213/ablation") == "s20261213/rsi_pilot/runs_v5/s20261213/ablation"
    assert M.seed_done_rel(s) == "runs_v5/s20261213/ablation/SEED_DONE"
    assert M.modal_extras_rel(s).startswith("runs_v5/s20261213/")
    txt = M.seed_done_text(2712)
    assert txt.split()[1:] == ["duration_s", "2712"]       # awk '{print $3}' as in ablation_remote.sh


def test_is_seed_done(tmp_path):
    s = 20261212
    abl = tmp_path / M.out_repo_path(s, f"runs_v5/s{s}/ablation")
    abl.mkdir(parents=True)
    assert not M.is_seed_done(tmp_path, s)
    (abl / "SEED_DONE").write_text(M.seed_done_text(1))
    assert not M.is_seed_done(tmp_path, s)               # marker without ablation.json
    (abl / "ablation.json").write_text("{}")
    assert M.is_seed_done(tmp_path, s)


def test_ignore_list():
    from modal import FilePatternMatcher
    m = FilePatternMatcher(*M.IGNORE)
    for p in ("data", "data/spider/database/x/x.sqlite", ".venv/Scripts/python.exe", "runs/cache/a.json",
              "runs_v5/s20261211/cache/k/h/t.json", "rsi/__pycache__/a.pyc", ".pytest_cache/v/x",
              "runs_v6/stage1/x.json", "runs_v7/a", "figures/f.png"):
        assert m(Path(p)), p
    for p in ("rsi/ablate.py", "scripts/run_ablation.sh", "cloud/modal_ablation.py", "ablations_v5.yaml",
              "frozen_v5_s20261211.yaml", "harness_agent.yaml", "requirements.txt", "tests/test_ablate.py",
              "runs_v5/s20261211/arm_A/final.yaml", "runs_v5/s20261211/audit.json",
              "runs_v5/s20261211/heldout_access.jsonl", "runs_v5/summary.csv"):
        assert not m(Path(p)), p


def test_ignore_list_on_the_real_tree():
    """What would be uploaded from this checkout: the run's inputs, no data or venv, small."""
    from modal import FilePatternMatcher
    m = FilePatternMatcher(*M.IGNORE)
    files = [p.relative_to(REPO) for p in REPO.rglob("*") if p.is_file()]
    kept = [p for p in files if not any(m(Path(*p.parts[:i])) for i in range(1, len(p.parts) + 1))]
    names = {p.as_posix() for p in kept}
    assert "scripts/run_ablation.sh" in names and "frozen_v5_s20261216.yaml" in names
    assert not any(n.startswith(("data/", ".venv/", "runs_v6/")) for n in names)
    assert sum((REPO / p).stat().st_size for p in kept) < 200e6


def test_placement_parser():
    assert M.ollama_placement(PS_GPU) == "100% GPU" and M.fully_on_gpu(PS_GPU) is True
    assert M.ollama_placement(PS_SPLIT) == "23%/77% CPU/GPU" and M.fully_on_gpu(PS_SPLIT) is False
    assert M.fully_on_gpu(PS_CPU) is False
    assert M.fully_on_gpu(PS_OTHER) is None              # another model does not count
    assert M.fully_on_gpu(PS_EMPTY) is None and M.fully_on_gpu("") is None
    assert M.fully_on_gpu("qwen2.5:7b-instruct  abc  6.0 GB  weird  8192  Forever\n") is False


def test_dirty_tree_check():
    porcelain = "\n".join([
        " M rsi_pilot/rsi/ablate.py",
        "?? rsi_pilot/PREDICTION_run6.md",
        "?? rsi_pilot/cloud/ledger_vultr.jsonl",
        "?? rsi_pilot/frozen_v6_smoke.yaml",
        "?? rsi_pilot/cloud/modal_ablation.py",
        "R  rsi_pilot/old.yaml -> rsi_pilot/frozen_v5_s20261211.yaml",
        " M rsi_pilot/runs_v5/s20261214/arm_B/final.yaml",
        " M rsi_pilot/runs_v5/s20261214/results.md",
        ' M "rsi_pilot/scripts/run ablation.sh"',
        " M other_project/rsi/x.py",
        "",
    ])
    bad = M.dirty_used_files(porcelain, "rsi_pilot/")
    assert bad == [" M rsi_pilot/rsi/ablate.py", "?? rsi_pilot/cloud/modal_ablation.py",
                   "R  rsi_pilot/old.yaml -> rsi_pilot/frozen_v5_s20261211.yaml",
                   " M rsi_pilot/runs_v5/s20261214/arm_B/final.yaml",
                   ' M "rsi_pilot/scripts/run ablation.sh"']
    clean = "?? rsi_pilot/PREDICTION_run6.md\n?? rsi_pilot/cloud/ledger_vultr.jsonl\n?? rsi_pilot/frozen_v6_smoke.yaml\n"
    assert M.dirty_used_files(clean, "rsi_pilot/") == []
    assert M.dirty_used_files(" M rsi/ablate.py\n", "") == [" M rsi/ablate.py"]


def test_require_clean_tree_uses_git(monkeypatch):
    monkeypatch.setattr(M, "git_state", lambda repo=M.LOCAL_REPO: ("abc123", [" M rsi_pilot/rsi/x.py"]))
    with pytest.raises(M.DirtyTreeError):
        M.require_clean_tree()
    monkeypatch.setattr(M, "git_state", lambda repo=M.LOCAL_REPO: ("abc123", []))
    assert M.require_clean_tree() == "abc123"


def test_summary_lines_carry_no_numbers_but_minutes():
    res = [{"seed": 20261211, "ok": True, "duration_s": 2700, "error": "", "skipped": False},
           {"seed": 20261212, "ok": False, "duration_s": None, "error": "FunctionTimeoutError: x"}]
    lines = M.summary_lines(res)
    assert lines[0] == "seed 20261211 ok=True minutes=45.0"
    assert lines[1] == "seed 20261212 ok=False minutes=- error=FunctionTimeoutError: x"
    assert lines[-1] == "ABLATION_DONE finished: 20261211 failed: 20261212"


# ---------------- merge of fetched results ----------------

def _stage_seed(stage, s, extra=None):
    base = stage / f"s{s}" / "rsi_pilot"
    abl = base / f"runs_v5/s{s}/ablation"
    abl.mkdir(parents=True)
    (abl / "ablation.json").write_text("{}")
    (abl / "SEED_DONE").write_text(M.seed_done_text(5))
    (base / f"runs_v5/s{s}/heldout_access.jsonl").write_text("old\nnew\n")
    (base / f"splits_v5_s{s}.json").write_text("{}")
    for rel, txt in (extra or {}).items():
        (base / rel).parent.mkdir(parents=True, exist_ok=True)
        (base / rel).write_text(txt)
    return base


def test_merge_copies_and_extends(tmp_path):
    s = 20261211
    stage, repo = tmp_path / "stage", tmp_path / "repo"
    _stage_seed(stage, s, {f"runs_v5/s{s}/logs/run.log": "same"})
    (repo / f"runs_v5/s{s}/logs").mkdir(parents=True)
    (repo / f"runs_v5/s{s}/heldout_access.jsonl").write_text("old\n")
    (repo / f"runs_v5/s{s}/logs/run.log").write_text("same")
    (repo / f"runs_v5/s{s}/arm_A").mkdir()
    (repo / f"runs_v5/s{s}/arm_A/final.yaml").write_text("keep")
    copied = M.merge(stage, repo)
    assert {p.relative_to(repo).as_posix() for p in copied} == {
        f"runs_v5/s{s}/ablation/ablation.json", f"runs_v5/s{s}/ablation/SEED_DONE",
        f"runs_v5/s{s}/heldout_access.jsonl", f"splits_v5_s{s}.json"}
    assert (repo / f"runs_v5/s{s}/heldout_access.jsonl").read_text() == "old\nnew\n"
    assert (repo / f"runs_v5/s{s}/arm_A/final.yaml").read_text() == "keep"     # never deleted


def test_merge_refuses_conflicts_and_copies_nothing(tmp_path):
    s = 20261212
    stage, repo = tmp_path / "stage", tmp_path / "repo"
    _stage_seed(stage, s)
    (repo / f"runs_v5/s{s}").mkdir(parents=True)
    (repo / f"runs_v5/s{s}/heldout_access.jsonl").write_text("edited locally\n")
    with pytest.raises(RuntimeError, match="merge refused"):
        M.merge(stage, repo)
    assert not (repo / f"splits_v5_s{s}.json").exists()


def test_merge_skips_unfinished_seed(tmp_path):
    stage, repo = tmp_path / "stage", tmp_path / "repo"
    repo.mkdir()
    (stage / "s20261213" / "rsi_pilot" / "runs_v5").mkdir(parents=True)
    copies, conflicts = M.merge_plan(stage, repo)
    assert copies == [] and conflicts and "not merged" in conflicts[0]
    assert M.merge(stage, repo) == []
