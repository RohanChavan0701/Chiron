"""Run 5 four-arm summary: checks scripts/arm_stats.py against the committed runs_v5 files."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs_v5"

pytestmark = pytest.mark.skipif(not (RUNS / "summary.csv").exists(), reason="runs_v5 not present")


@pytest.fixture(scope="module")
def stats():
    spec = importlib.util.spec_from_file_location("arm_stats", ROOT / "scripts" / "arm_stats.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, mod.compute(RUNS)


def r2(x):
    return round(x, 2)


def test_raw_held_out_mean_sd(stats):
    _, r = stats
    want = {"baseline": (46.42, 1.69), "arm_A": (58.17, 1.51),
            "arm_B": (58.42, 1.36), "arm_C": (58.83, 2.29)}
    for h, (m, sd) in want.items():
        assert (r2(r["arms"][h]["H"][0]), r2(r["arms"][h]["H"][1])) == (m, sd), h


def test_testsuite_corrected_mean_sd(stats):
    _, r = stats
    want = {"baseline": (35.00, 1.61), "arm_A": (44.33, 5.44),
            "arm_B": (47.25, 1.81), "arm_C": (46.75, 4.26)}
    for h, (m, sd) in want.items():
        assert (r2(r["arms"][h]["H_ts"][0]), r2(r["arms"][h]["H_ts"][1])) == (m, sd), h


def test_false_positive_share(stats):
    _, r = stats
    want = {"baseline": 24.6, "arm_A": 23.8, "arm_B": 19.1, "arm_C": 20.5}
    for h, v in want.items():
        assert round(r["arms"][h]["fp_share"], 1) == v, h
        assert r["arms"][h]["gold_empty"] == 0, h


def test_paired_differences(stats):
    _, r = stats
    d = r["diffs"]
    assert (r2(d[("arm_A", "arm_C")]["H"]["mean"]), r2(d[("arm_A", "arm_C")]["H"]["sd"])) == (-0.67, 1.86)
    assert (r2(d[("arm_B", "arm_C")]["H"]["mean"]), r2(d[("arm_B", "arm_C")]["H"]["sd"])) == (-0.42, 2.91)
    assert (r2(d[("arm_B", "arm_A")]["H"]["mean"]), r2(d[("arm_B", "arm_A")]["H"]["sd"])) == (0.25, 1.64)
    assert (r2(d[("arm_A", "arm_C")]["H_ts"]["mean"]), r2(d[("arm_A", "arm_C")]["H_ts"]["sd"])) == (-2.42, 6.89)
    assert (r2(d[("arm_B", "arm_C")]["H_ts"]["mean"]), r2(d[("arm_B", "arm_C")]["H_ts"]["sd"])) == (0.50, 4.84)


def test_p_values_match_seed_level(stats):
    _, r = stats
    # runs_v5/seed_level.md: arm_A vs arm_C on H p = 0.531, arm_B vs arm_A on H p = 0.844
    assert round(r["diffs"][("arm_A", "arm_C")]["H"]["p"], 3) == 0.531
    assert round(r["diffs"][("arm_B", "arm_A")]["H"]["p"], 3) == 0.844


def test_committed_markdown_is_current(stats):
    mod, r = stats
    assert (RUNS / "arm_stats.md").read_text(encoding="utf-8") == mod.render(r)
