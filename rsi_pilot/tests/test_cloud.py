"""Guardrails of cloud.lambda_api, without network: the API is replaced by a recorder."""
from datetime import datetime, timedelta, timezone

import pytest

from cloud import lambda_api as L

T0 = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


def _type(gpu, gpus, price, regions):
    return {"instance_type": {"name": "x", "description": "", "gpu_description": gpu,
                              "price_cents_per_hour": price, "architecture": "x86_64",
                              "specs": {"vcpus": 30, "memory_gib": 200, "storage_gib": 1400, "gpus": gpus}},
            "regions_with_capacity_available": [{"name": r, "description": ""} for r in regions]}


TYPES = {"gpu_1x_a10": _type("A10 (24 GB PCIe)", 1, 129, ["us-east-1"]),
         "gpu_1x_a100": _type("A100 (40 GB SXM4)", 1, 179, ["us-east-1"]),
         "gpu_8x_a100": _type("A100 (40 GB SXM4)", 8, 1432, ["us-east-1"])}


@pytest.fixture
def api(monkeypatch, tmp_path):
    """Fake API; returns (calls, ledger path). Clock fixed at T0 unless a test moves it."""
    calls = []

    def fake(method, path, body=None, timeout=60):
        calls.append((method, path, body))
        if path == "/instance-types":
            return {"data": TYPES}
        if path == "/instance-operations/launch":
            return {"data": {"instance_ids": ["i-new"]}}
        if path.startswith("/instances/"):
            return {"data": {"id": path.rsplit("/", 1)[1], "status": "active", "ip": "1.2.3.4"}}
        if path == "/instance-operations/terminate":
            return {"data": {"terminated_instances": []}}
        raise AssertionError(path)

    monkeypatch.setattr(L, "_request", fake)
    monkeypatch.setattr(L, "now_utc", lambda: T0)
    return calls, tmp_path / "ledger.jsonl"


def _launched(ledger, iid="i-1", price=129, at=T0):
    L.append_ledger({"event": "launch", "id": iid, "price_cents_per_hour": price,
                     "launched_at": L._iso(at),
                     "terminate_by": L._iso(at + timedelta(hours=L.cap_hours(price)))}, ledger)


# --- cap arithmetic ---------------------------------------------------------

@pytest.mark.parametrize("price,hours", [(75, 48.0), (104, 48.0), (129, 5000 / 129), (250, 20.0)])
def test_cap_is_min_of_48h_and_50_dollars(price, hours):
    assert L.cap_hours(price) == pytest.approx(hours)
    assert L.cap_hours(price) * price / 100 <= 50 + 1e-9


def test_cap_rejects_nonpositive_price():
    with pytest.raises(L.GuardrailError):
        L.cap_hours(0)


def test_cap_with_split_budget():
    # run 4: $50 over three A10s
    assert L.cap_hours(129, 50 / 3) == pytest.approx(50 / 3 * 100 / 129)
    for bad in (0, -1, 50.01):
        with pytest.raises(L.GuardrailError):
            L.cap_hours(129, bad)


def test_spend_estimate_uses_launch_price():
    lau = {"launched_at": L._iso(T0), "price_cents_per_hour": 129}
    hours, usd = L.elapsed_and_spend(lau, T0 + timedelta(hours=10))
    assert hours == pytest.approx(10) and usd == pytest.approx(12.90)


# --- terminate refusal ------------------------------------------------------

def test_terminate_refuses_id_not_in_ledger(api):
    calls, ledger = api
    _launched(ledger, "i-1")
    with pytest.raises(L.GuardrailError, match="not launched by this ledger"):
        L.terminate("i-someone-else", "author", ledger)
    assert calls == []
    assert len(L.read_ledger(ledger)) == 1


def test_terminate_refuses_empty_ledger(api):
    calls, ledger = api
    with pytest.raises(L.GuardrailError):
        L.terminate("i-1", "cap", ledger)
    assert calls == []


def test_terminate_refuses_twice_and_bad_reason(api):
    calls, ledger = api
    _launched(ledger, "i-1")
    with pytest.raises(L.GuardrailError):
        L.terminate("i-1", "bored", ledger)
    L.terminate("i-1", "job_done", ledger)
    with pytest.raises(L.GuardrailError, match="already"):
        L.terminate("i-1", "job_done", ledger)
    assert [c[1] for c in calls] == ["/instance-operations/terminate"]


def test_terminate_writes_ledger_with_spend(api, monkeypatch):
    calls, ledger = api
    _launched(ledger, "i-1", price=129)
    monkeypatch.setattr(L, "now_utc", lambda: T0 + timedelta(hours=2))
    e = L.terminate("i-1", "job_done", ledger)
    assert calls == [("POST", "/instance-operations/terminate", {"instance_ids": ["i-1"]})]
    assert e["est_spend_usd"] == pytest.approx(2.58) and L.open_instances(L.read_ledger(ledger)) == []


# --- launch guardrails ------------------------------------------------------

def test_launch_picks_1x_a10_by_specs_and_records_cap(api):
    calls, ledger = api
    e = L.launch("chiron-run4-a", "us-east-1", "laptop", "author, chat 2026-11-04", ledger=ledger)
    body = calls[-1][2]
    assert body["instance_type_name"] == "gpu_1x_a10" and body["ssh_key_names"] == ["laptop"]
    assert e["id"] == "i-new" and e["price_cents_per_hour"] == 129
    assert e["terminate_by"] == L._iso(T0 + timedelta(hours=5000 / 129))
    assert L.open_instances(L.read_ledger(ledger)) == ["i-new"]


def test_launch_refuses_at_max_open(api):
    calls, ledger = api
    for i in range(L.MAX_OPEN - 1):
        _launched(ledger, f"i-{i}")
    L.launch("chiron-run4-b", "us-east-1", "laptop", "ok", budget_usd=50 / 3, ledger=ledger)
    n = len(calls)
    with pytest.raises(L.GuardrailError, match="without a terminate"):
        L.launch("chiron-run4-c", "us-east-1", "laptop", "ok", ledger=ledger)
    assert len(calls) == n


def test_launch_records_split_budget_cap(api):
    calls, ledger = api
    e = L.launch("chiron-run4-a", "us-east-1", "laptop", "ok", budget_usd=50 / 3, ledger=ledger)
    assert e["budget_usd"] == 16.67 and e["cap_hours"] == pytest.approx(12.92, abs=1e-2)


@pytest.mark.parametrize("name,approved", [("run4-a", "ok"), ("chiron-" + "x" * 60, "ok"),
                                          ("chiron-run4-a", "  ")])
def test_launch_refuses_bad_name_or_missing_approval(api, name, approved):
    calls, ledger = api
    with pytest.raises(L.GuardrailError):
        L.launch(name, "us-east-1", "laptop", approved, ledger=ledger)
    assert calls == []


def test_launch_refuses_region_without_capacity(api):
    calls, ledger = api
    with pytest.raises(L.GuardrailError, match="capacity"):
        L.launch("chiron-run4-a", "us-west-1", "laptop", "ok", ledger=ledger)
    assert all(c[1] != "/instance-operations/launch" for c in calls)


def test_a10_type_must_be_unique():
    two = dict(TYPES, gpu_1x_a10_alt=_type("A10 (24 GB PCIe)", 1, 99, []))
    with pytest.raises(L.GuardrailError):
        L.a10_type(two)


# --- status -----------------------------------------------------------------

def test_status_flags_past_cap(api, monkeypatch):
    calls, ledger = api
    _launched(ledger, "i-1", price=129)
    monkeypatch.setattr(L, "now_utc", lambda: T0 + timedelta(hours=39))
    e = L.status("i-1", "seed 20261112", ledger)
    assert e["past_cap"] and e["est_spend_usd"] == pytest.approx(50.31)
    with pytest.raises(L.GuardrailError):
        L.status("i-other", ledger=ledger)


def test_type_exception_is_scoped_to_run7_and_its_budget(api, monkeypatch):
    calls, ledger = api
    h100 = _type("H100 (80 GB PCIe)", 1, 329, ["us-west-3"])
    monkeypatch.setitem(TYPES, "gpu_1x_h100_pcie", h100)
    ok = L.launch("chiron-run7", "us-west-3", "key", "author", budget_usd=30, ledger=ledger,
                  instance_type="gpu_1x_h100_pcie")
    assert calls[-1][2]["instance_type_name"] == "gpu_1x_h100_pcie"
    assert ok["type"] == "gpu_1x_h100_pcie" and ok["cap_hours"] == pytest.approx(3000 / 329, abs=1e-3)
    n = len(calls)
    for name, budget, itype in (("chiron-run8", 30, "gpu_1x_h100_pcie"), ("chiron-run7-b", 31, "gpu_1x_h100_pcie"),
                                ("chiron-run7-b", 30, "gpu_1x_a100")):
        with pytest.raises(L.GuardrailError):
            L.launch(name, "us-west-3", "key", "author", budget_usd=budget, ledger=ledger, instance_type=itype)
    assert not [c for c in calls[n:] if c[1] == "/instance-operations/launch"]     # nothing was launched
