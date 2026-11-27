"""Offline checks of cloud/modal_qb_sweep.py: no Modal token, no network."""
import ast
import re
import warnings
from pathlib import Path

import pytest

modal = pytest.importorskip("modal")

from cloud import modal_qb_sweep as Q  # noqa: E402

SRC = Path(Q.__file__).read_text(encoding="utf-8")


def _decorators():
    out = {}
    for node in ast.parse(SRC).body:
        if isinstance(node, ast.FunctionDef):
            for d in node.decorator_list:
                if isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "function":
                    out[node.name] = {k.arg: k.value for k in d.keywords}
    return out


def test_imports_and_registers_without_credentials():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assert set(Q.app.registered_functions) == {"run_sweep"}
        assert set(Q.app.registered_entrypoints) == {"main"}


def test_function_settings_pin_the_gpu_timeout_and_no_retries():
    decs = _decorators()
    assert set(decs) == {"run_sweep"}
    kw = decs["run_sweep"]
    assert "retries" not in kw
    assert ast.literal_eval(kw["max_containers"]) == 1
    assert Q.GPU == "A100-40GB"
    assert Q.EXPECTED_GPU[Q.GPU] == ("A100", 39000)
    assert Q.MAX_MINUTES == 100 and Q.STARTUP_MINUTES == 5


def test_cost_guard_fits_five_dollars_and_refuses_more():
    p = Q.check_budget()
    assert p["worst_case"] < 5.0
    assert abs(p["worst_case"] - (105 * 60 * (0.000583 + 4 * 0.0000131 + 16 * 0.00000222))) < 1e-6
    with pytest.raises(Q.CostGuardError):
        Q.check_budget(minutes=130)
    with pytest.raises(Q.CostGuardError):
        Q.check_budget(gpu="H100")
    # the A10 would also fit, cheaper
    assert Q.check_budget(gpu="A10")["worst_case"] < p["worst_case"]


def test_patch_is_committed_and_used():
    assert Q.PATCH_LOCAL.is_file()
    assert "cloud/qb_load_sweep.patch" in Q.USED_PATTERNS
    assert Q.dirty_used_files(" M rsi_pilot/cloud/qb_load_sweep.patch\n") == [" M rsi_pilot/cloud/qb_load_sweep.patch"]
    assert Q.dirty_used_files(" M rsi_pilot/README.md\n?? rsi_pilot/cloud/other.py\n") == []
    assert Q.dirty_used_files('?? "rsi_pilot/cloud/modal_qb_sweep.py"\n') != []


def test_gpu_check():
    assert Q.gpu_ok("NVIDIA A100-SXM4-40GB, 40960\n")
    assert Q.gpu_ok("NVIDIA A100-PCIE-40GB, 40536\n")
    assert not Q.gpu_ok("NVIDIA A10, 23028\n")
    assert not Q.gpu_ok("NVIDIA A100-SXM4-40GB, nope\n")


def test_summary_and_errors_carry_no_benchmark_numbers():
    lines = Q.summary_lines({"run_id": "20261127T000000Z", "ok": True, "duration_s": 3000})
    assert all(re.search(r"tok/s|ms|throughput", ln) is None for ln in lines)
    assert "chiron-qb-out" in lines[1]
    for name in ("output_throughput", "median_ttft", "request_throughput"):
        assert name not in SRC


def test_secret_and_volumes_declared():
    assert Q.HF_SECRET_NAME == "huggingface"
    assert "Secret.from_name(HF_SECRET_NAME)" in SRC
    assert "chiron-qb-out" in SRC and "chiron-hf-cache" in SRC
