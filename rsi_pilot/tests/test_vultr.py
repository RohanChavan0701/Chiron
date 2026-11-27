"""Guardrails of cloud.vultr_api, without network: the API is a fake transport and urlopen is
blocked. No real key is read: the env var is replaced by a dummy or removed, and KEY_FILE points
into tmp_path."""
import io
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

from cloud import vultr_api as V

T0 = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)
DUMMY = "DUMMY-NOT-A-KEY-0000"
PASSWORD = "pw-SENTINEL-0000"
PLAN = "vcg-a100-12c-120g-80vram"
A40 = "vcg-a40-24c-120g-48vram"
L40S = "vcg-l40s-16c-180g-48vram"


def _plan(pid, hourly, ptype="vdm", location_hourly=None, region="ewr"):
    """Shaped like the live listing (2026-11-27): empty locations, gpu fields empty."""
    p = {"id": pid, "type": ptype, "vcpu_count": 12, "ram": 122880, "disk": 1400,
         "hourly_cost": hourly, "gpu_type": "", "gpu_vram_gb": "", "locations": []}
    if location_hourly is not None:
        p["location_cost"] = {region: {"hourly_cost": location_hourly}}
    return p


# type=all: the A100/A40/A16 plans as type vdm, plus non-GPU plans that must be dropped
PLANS = [_plan(PLAN, 2.397), _plan(A40, 1.712), _plan("vcg-a16-6c-60g-16vram", 0.471),
         _plan("vc2-1c-1gb", 0.007, ptype="vc2"), _plan("vhf-8c-32gb", 0.26, ptype="vhf")]
VCG_PLANS = [_plan(L40S, 1.671, ptype="vcg"), _plan(A40, 1.712)]          # overlap on purpose
AVAILABILITY = {"ewr": [PLAN, "vc2-1c-1gb"], "lax": [A40], "lhr": [A40]}


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    """Every test: no network, no real key."""
    def no_net(*a, **k):
        raise AssertionError("network call attempted")
    monkeypatch.setattr(urllib.request, "urlopen", no_net)
    monkeypatch.delenv(V.KEY_ENV, raising=False)
    monkeypatch.setattr(V, "KEY_FILE", tmp_path / "no_such_key_file")
    monkeypatch.setattr(V, "now_utc", lambda: T0)
    monkeypatch.setattr(V, "LEDGER", tmp_path / "cli_ledger_vultr.jsonl")   # the CLI never writes the real one


@pytest.fixture
def api(tmp_path):
    """Fake transport; returns (calls, ledger path, transport)."""
    calls = []

    def fake(method, path, body=None):
        calls.append((method, path, body))
        if path.startswith("/plans?type=all"):
            return {"plans": PLANS, "meta": {"total": len(PLANS), "links": {"next": "", "prev": ""}}}
        if path.startswith("/plans?type=vcg"):
            return {"plans": VCG_PLANS, "meta": {"links": {"next": ""}}}
        if path.startswith("/regions?"):
            return {"regions": [{"id": r} for r in ("ewr", "lax", "lhr", "ams")], "meta": {"links": {"next": ""}}}
        if path.startswith("/regions/") and path.endswith("/availability"):
            return {"available_plans": AVAILABILITY.get(path.split("/")[2], [])}
        if method == "GET" and path.startswith("/ssh-keys"):
            return {"ssh_keys": [{"id": "key-uuid-1", "name": "laptop"}], "meta": {"links": {"next": ""}}}
        if method == "POST" and path == "/instances":
            return {"instance": {"id": "inst-new", "status": "pending", "main_ip": "0.0.0.0",
                                 "default_password": PASSWORD}}
        if method == "POST" and path == "/ssh-keys":
            return {"ssh_key": {"id": "key-uuid-new", "name": body["name"], "ssh_key": body["ssh_key"]}}
        if method == "GET" and path.startswith("/instances/"):
            return {"instance": {"id": path.rsplit("/", 1)[1], "status": "active",
                                 "power_status": "running", "server_status": "ok", "main_ip": "192.0.2.7"}}
        if method == "DELETE" and path.startswith("/instances/"):
            return {}
        if path == "/account":
            return {"account": {"balance": -250.0, "pending_charges": 3.1}}
        raise AssertionError(path)

    return calls, tmp_path / "ledger_vultr.jsonl", fake


def _allow(monkeypatch, *plans):
    monkeypatch.setattr(V, "PLAN_ALLOWLIST", {p: "test" for p in plans})


def _launched(ledger, iid="inst-1", price=171.2, budget=20.0, at=T0):
    h = V.cap_hours(price, budget)
    V.append_ledger({"event": "launch", "id": iid, "price_cents_per_hour": price, "budget_usd": budget,
                     "launched_at": V._iso(at), "terminate_by": V._iso(at + timedelta(hours=h))}, ledger)


def _go(transport, ledger, **kw):
    args = dict(label="chiron-run8", plan=PLAN, region="ewr", ssh_key="laptop",
                approved_by="author, 2026-11-27 chat", budget_usd=20.0, os_id=2284,
                ledger=ledger, transport=transport)
    args.update(kw)
    return V.launch(**args)


# --- cap arithmetic ---------------------------------------------------------

@pytest.mark.parametrize("price,budget,hours", [
    (171.2, 20, 11 - V.DESTROY_MARGIN_HOURS),     # 20 / 1.712 = 11.68 -> 11 whole hours
    (47.1, 20, 24 - V.DESTROY_MARGIN_HOURS),      # 42 hours affordable, MAX_HOURS binds
    (239.7, 5, 2 - V.DESTROY_MARGIN_HOURS),
    (239.7, 10, 4 - V.DESTROY_MARGIN_HOURS),      # A100 at $2.397: $10 / 2.397 = 4.17 -> 4 whole hours
    (239.7, 20, 8 - V.DESTROY_MARGIN_HOURS),      # 8.34 -> 8
    (100, 20, 20 - V.DESTROY_MARGIN_HOURS)])      # exact division
def test_cap_is_whole_affordable_hours_capped_at_max(price, budget, hours):
    h = V.cap_hours(price, budget)
    assert h == pytest.approx(hours)
    assert V.math.ceil(h) * price / 100 <= budget + 1e-9


@pytest.mark.parametrize("price,budget", [(0, 10), (-5, 10), (171.2, 0), (171.2, -1),
                                          (171.2, V.MAX_BUDGET_USD + 0.01), (2500, 20)])
def test_cap_refuses_bad_price_budget_or_less_than_one_hour(price, budget):
    with pytest.raises(V.GuardrailError):
        V.cap_hours(price, budget)


def test_spend_estimate_bills_started_hours():
    lau = {"launched_at": V._iso(T0), "price_cents_per_hour": 171.2}
    assert V.elapsed_and_spend(lau, T0 + timedelta(minutes=5))[1] == pytest.approx(1.712)
    hours, usd = V.elapsed_and_spend(lau, T0 + timedelta(hours=2, minutes=1))
    assert hours == pytest.approx(2 + 1 / 60) and usd == pytest.approx(3 * 1.712)


def test_price_takes_higher_of_plan_and_location_cost():
    assert V.plan_price_cents(_plan("p", 1.0, location_hourly=1.25, region="lax"), "lax") == 125
    assert V.plan_price_cents(_plan("p", 1.5, location_hourly=1.25, region="lax"), "lax") == 150
    assert V.plan_price_cents(_plan("p", 1.5, location_hourly=9.0, region="lax"), "ewr") == 150
    with pytest.raises(V.GuardrailError):
        V.plan_price_cents({"id": "p"}, "lax")


# --- plan listing and availability ------------------------------------------

def test_gpu_plans_merge_type_all_and_vcg_by_id_prefix(api):
    calls, ledger, t = api
    ids = [p["id"] for p in V.gpu_plans(t)]
    assert ids == [PLAN, A40, "vcg-a16-6c-60g-16vram", L40S]       # vc2/vhf dropped, A40 once
    assert [c[1] for c in calls] == ["/plans?type=all&per_page=500", "/plans?type=vcg&per_page=500"]


def test_availability_comes_from_the_region_endpoint(api):
    calls, ledger, t = api
    assert V.available_plans("ewr", t) == [PLAN, "vc2-1c-1gb"] and V.available_plans("ams", t) == []
    assert calls[0] == ("GET", "/regions/ewr/availability", None)
    plans = V.gpu_plans(t)
    assert V.allowed_plan(plans, PLAN, "ewr", t) == (PLAN, pytest.approx(239.7))
    with pytest.raises(V.GuardrailError, match="not available in lax"):
        V.allowed_plan(plans, PLAN, "lax", t)


def test_empty_locations_do_not_block_an_available_plan(api):
    calls, ledger, t = api
    assert all(p["locations"] == [] for p in V.gpu_plans(t))
    assert V.allowed_plan(V.gpu_plans(t), PLAN, "ewr", t)[0] == PLAN


# --- launch guardrails ------------------------------------------------------

def test_empty_allowlist_refuses_every_plan(api, monkeypatch):
    calls, ledger, t = api
    monkeypatch.setattr(V, "PLAN_ALLOWLIST", {})
    with pytest.raises(V.GuardrailError, match="PLAN_ALLOWLIST"):
        _go(t, ledger)
    assert not [c for c in calls if c[0] == "POST"] and not ledger.exists()


def test_only_the_author_named_plan_is_allowlisted(api):
    calls, ledger, t = api
    assert list(V.PLAN_ALLOWLIST) == [PLAN] and "lets use a100" in V.PLAN_ALLOWLIST[PLAN]
    with pytest.raises(V.GuardrailError, match="PLAN_ALLOWLIST"):
        _go(t, ledger, plan=A40, region="lax")                 # available, but not allowlisted
    assert not [c for c in calls if c[0] == "POST"]


def test_module_constants_ship_as_set():
    """Read from the source, not the (possibly patched) module."""
    import ast
    tree = ast.parse(open(V.__file__, encoding="utf-8").read())
    consts = {t.id if isinstance(t, ast.Name) else t.target.id: n.value
              for n in tree.body if isinstance(n, (ast.Assign, ast.AnnAssign))
              for t in ([n] if isinstance(n, ast.AnnAssign) else n.targets)
              if isinstance(t, ast.Name) or isinstance(t, ast.AnnAssign)}
    assert list(ast.literal_eval(consts["PLAN_ALLOWLIST"])) == [PLAN]
    assert ast.literal_eval(consts["MAX_OPEN"]) == 1
    assert ast.literal_eval(consts["MAX_HOURS"]) == 24.0
    assert ast.literal_eval(consts["MAX_BUDGET_USD"]) == 20.0


def test_launch_records_live_price_cap_and_provider(api):
    calls, ledger, t = api
    e = _go(t, ledger, user_data="#!/bin/sh\necho hi\n", budget_usd=10.0)
    method, path, body = calls[-1]
    assert ("GET", "/regions/ewr/availability", None) in calls
    assert (method, path) == ("POST", "/instances")
    assert body["plan"] == PLAN and body["region"] == "ewr" and body["sshkey_id"] == ["key-uuid-1"]
    assert body["label"] == "chiron-run8" and body["os_id"] == 2284 and "image_id" not in body
    assert V.base64.b64decode(body["user_data"]).decode() == "#!/bin/sh\necho hi\n"
    assert e["price_cents_per_hour"] == pytest.approx(239.7) and e["cap_hours"] == pytest.approx(3.9)
    assert e["terminate_by"] == V._iso(T0 + timedelta(hours=3.9))
    rows = V.read_ledger(ledger)
    assert len(rows) == 1 and rows[0]["provider"] == "vultr" and rows[0]["event"] == "launch"
    assert rows[0]["approved_by_author"] == "author, 2026-11-27 chat" and rows[0]["budget_usd"] == 10.0
    assert V.open_instances(rows) == ["inst-new"]


def test_launch_uses_live_price_not_a_remembered_one(api, monkeypatch):
    calls, ledger, t = api
    _allow(monkeypatch, PLAN)
    monkeypatch.setitem(PLANS[0], "hourly_cost", 4.0)
    e = _go(t, ledger)
    assert e["price_cents_per_hour"] == 400 and e["cap_hours"] == pytest.approx(5 - V.DESTROY_MARGIN_HOURS)


def test_launch_refuses_while_any_instance_is_open(api, monkeypatch):
    calls, ledger, t = api
    _allow(monkeypatch, PLAN)
    _launched(ledger, "inst-old")
    with pytest.raises(V.GuardrailError, match="without a terminate"):
        _go(t, ledger)
    assert calls == []


@pytest.mark.parametrize("kw", [dict(label="run8"), dict(label="chiron-" + "x" * 60),
                                dict(approved_by=""), dict(approved_by="   "), dict(approved_by=None),
                                dict(budget_usd=None), dict(budget_usd=0),
                                dict(budget_usd=V.MAX_BUDGET_USD + 1),
                                dict(os_id=None), dict(image_id="img")])
def test_launch_refuses_bad_label_missing_approval_or_budget(api, monkeypatch, kw):
    calls, ledger, t = api
    _allow(monkeypatch, PLAN)
    with pytest.raises(V.GuardrailError):
        _go(t, ledger, **kw)
    assert calls == [] and not ledger.exists()


def test_launch_refuses_plan_missing_from_live_listing_or_region(api, monkeypatch):
    calls, ledger, t = api
    _allow(monkeypatch, PLAN, "vcg-gone")
    with pytest.raises(V.GuardrailError, match="live Cloud GPU listing"):
        _go(t, ledger, plan="vcg-gone")
    for region in ("lax", "ams"):
        with pytest.raises(V.GuardrailError, match="not available"):
            _go(t, ledger, region=region)
    assert not [c for c in calls if c[0] == "POST"]


def test_launch_refuses_unknown_ssh_key(api, monkeypatch):
    calls, ledger, t = api
    _allow(monkeypatch, PLAN)
    with pytest.raises(V.GuardrailError, match="SSH key"):
        _go(t, ledger, ssh_key="someone-else")
    assert not [c for c in calls if c[0] == "POST"]


def test_cli_launch_requires_budget_and_approval(api, monkeypatch):
    calls, ledger, t = api
    base = ["launch", "--label", "chiron-x", "--plan", PLAN, "--region", "ewr", "--ssh-key", "laptop",
            "--os-id", "1"]
    for missing in (["--approved-by", "ok"], ["--budget-usd", "5"]):
        with pytest.raises(SystemExit):
            V.main(base + missing, transport=t)
    assert calls == []


# --- destroy and check ------------------------------------------------------

def test_destroy_refuses_id_not_in_ledger(api):
    calls, ledger, t = api
    _launched(ledger, "inst-1")
    with pytest.raises(V.GuardrailError, match="not launched by this ledger"):
        V.destroy("inst-someone-else", "author", ledger, t)
    with pytest.raises(V.GuardrailError):
        V.destroy("inst-1", "bored", ledger, t)
    assert calls == [] and len(V.read_ledger(ledger)) == 1


def test_destroy_refuses_empty_ledger(api):
    calls, ledger, t = api
    with pytest.raises(V.GuardrailError):
        V.destroy("inst-1", "cap", ledger, t)
    assert calls == [] and not ledger.exists()


def test_destroy_writes_terminate_line_once(api, monkeypatch):
    calls, ledger, t = api
    _launched(ledger, "inst-1")
    monkeypatch.setattr(V, "now_utc", lambda: T0 + timedelta(hours=2, minutes=30))
    e = V.destroy("inst-1", "job_done", ledger, t)
    assert calls == [("DELETE", "/instances/inst-1", None)]
    assert e["event"] == "terminate" and e["est_spend_usd"] == pytest.approx(3 * 1.712, abs=0.01)
    assert V.read_ledger(ledger)[-1]["provider"] == "vultr" and V.open_instances(V.read_ledger(ledger)) == []
    with pytest.raises(V.GuardrailError, match="already"):
        V.destroy("inst-1", "job_done", ledger, t)
    assert len(calls) == 1


def test_status_writes_check_line_and_refuses_unknown(api, monkeypatch):
    calls, ledger, t = api
    _launched(ledger, "inst-1")
    monkeypatch.setattr(V, "now_utc", lambda: T0 + timedelta(hours=1))
    e = V.status("inst-1", "seed 1", ledger, t)
    assert e["event"] == "check" and e["ip"] == "192.0.2.7" and e["status"] == "active"
    assert not e["past_cap"] and e["est_spend_usd"] == pytest.approx(1.71)
    with pytest.raises(V.GuardrailError):
        V.status("inst-other", ledger=ledger, transport=t)


def test_check_before_cap_does_not_destroy(api, monkeypatch):
    calls, ledger, t = api
    _launched(ledger, "inst-1")
    monkeypatch.setattr(V, "now_utc", lambda: T0 + timedelta(hours=10))
    out = V.check(ledger=ledger, transport=t)
    assert [e["event"] for e in out] == ["check"] and not [c for c in calls if c[0] == "DELETE"]


def test_check_past_cap_destroys(api, monkeypatch):
    calls, ledger, t = api
    _launched(ledger, "inst-1")                          # cap 10.9 h at 171.2 cents, $20
    monkeypatch.setattr(V, "now_utc", lambda: T0 + timedelta(hours=10, minutes=55))
    out = V.check(ledger=ledger, transport=t)
    assert [e["event"] for e in out] == ["check", "terminate"]
    assert out[0]["past_cap"] and out[1]["reason"] == "cap"
    assert ("DELETE", "/instances/inst-1", None) in calls
    assert V.open_instances(V.read_ledger(ledger)) == []
    assert V.check(ledger=ledger, transport=t) == []     # nothing open, nothing called


def test_check_ignores_ids_launched_elsewhere(api):
    calls, ledger, t = api
    with pytest.raises(V.GuardrailError):
        V.check("inst-not-ours", ledger=ledger, transport=t)
    assert calls == []


def test_ledger_not_created_until_first_event(api):
    calls, ledger, t = api
    assert V.read_ledger(ledger) == [] and not ledger.exists()
    assert not V.LEDGER.exists() or V.LEDGER.read_text(encoding="utf-8").strip()


# --- key handling -----------------------------------------------------------

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_key_goes_only_into_the_header(monkeypatch):
    monkeypatch.setenv(V.KEY_ENV, DUMMY)
    seen = {}

    def fake_urlopen(req, timeout=60):
        seen["auth"] = req.get_header("Authorization")
        seen["url"] = req.full_url
        return _Resp(b"")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert V._http_request("DELETE", "/instances/x") == {}
    assert seen["auth"] == f"Bearer {DUMMY}" and DUMMY not in seen["url"]


def test_key_never_in_http_error_text(monkeypatch):
    monkeypatch.setenv(V.KEY_ENV, DUMMY)

    def fail(req, timeout=60):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {},
                                     io.BytesIO(json.dumps({"error": "Invalid API token.", "status": 401}).encode()))
    monkeypatch.setattr(urllib.request, "urlopen", fail)
    with pytest.raises(V.VultrError) as ei:
        V._http_request("GET", "/account")
    assert DUMMY not in str(ei.value) and "401" in str(ei.value)
    assert ei.value.__cause__ is None and ei.value.__suppress_context__


def test_key_never_in_ledger_lines(api, monkeypatch):
    calls, ledger, t = api
    monkeypatch.setenv(V.KEY_ENV, DUMMY)
    _allow(monkeypatch, PLAN)
    seen = []

    def keyed(method, path, body=None):            # what the real transport would see
        seen.append(V.load_key())
        return t(method, path, body)
    e = _go(keyed, ledger)
    monkeypatch.setattr(V, "now_utc", lambda: T0 + timedelta(hours=11))
    V.check(ledger=ledger, transport=keyed)
    assert seen and all(k == DUMMY for k in seen)
    text = ledger.read_text(encoding="utf-8")
    assert DUMMY not in text and len(text.splitlines()) == 3 and e["id"] == "inst-new"


def test_missing_key_error_names_no_secret(monkeypatch):
    with pytest.raises(V.KeyLoadError, match=V.KEY_ENV):
        V.load_key()


def test_key_file_decode_with_dpapi_mocked(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    blob = b"\x01\x00\x00\x00fake-dpapi-blob"
    got = {}

    def fake_unprotect(b):
        got["blob"] = b
        return "dummy-secret".encode("utf-16-le")
    monkeypatch.setattr(V, "_dpapi_unprotect", fake_unprotect)
    f = tmp_path / ".vultr_key"
    f.write_text(blob.hex() + "\r\n", encoding="utf-8")
    monkeypatch.setattr(V, "KEY_FILE", f)
    assert V.load_key() == "dummy-secret" and got["blob"] == blob


def test_env_var_wins_over_key_file(monkeypatch, tmp_path):
    monkeypatch.setenv(V.KEY_ENV, DUMMY)
    monkeypatch.setattr(V, "_dpapi_unprotect", lambda b: pytest.fail("file path used"))
    assert V.load_key() == DUMMY


@pytest.mark.parametrize("content", ["not hex at all", "", "zz"])
def test_bad_key_file_errors_do_not_echo_content(monkeypatch, content):
    monkeypatch.setattr(V, "_dpapi_unprotect", lambda b: pytest.fail("should not decrypt"))
    with pytest.raises(V.KeyLoadError) as ei:
        V.decode_key_file(content)
    assert not content.strip() or content not in str(ei.value)


def test_non_windows_supports_env_only(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    f = tmp_path / ".vultr_key"
    f.write_text("00", encoding="utf-8")
    monkeypatch.setattr(V, "KEY_FILE", f)
    with pytest.raises(V.KeyLoadError, match="Windows-only"):
        V.load_key()


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_dpapi_round_trip_on_a_dummy_string(monkeypatch, tmp_path):
    """Real DPAPI, dummy secret only: protect 'not-a-key' as ConvertFrom-SecureString would."""
    blob = V._dpapi("not-a-key".encode("utf-16-le"), protect=True)
    f = tmp_path / ".vultr_key"
    f.write_text(blob.hex(), encoding="utf-8")
    monkeypatch.setattr(V, "KEY_FILE", f)
    assert V.load_key() == "not-a-key"


# --- read-only commands -----------------------------------------------------

def test_plans_keys_balance_commands(api, capsys, monkeypatch):
    calls, ledger, t = api
    V.main(["plans"], transport=t)
    plans = {p["id"]: p for p in json.loads(capsys.readouterr().out)}
    assert {i: p["allowlisted"] for i, p in plans.items()} == {
        PLAN: True, A40: False, "vcg-a16-6c-60g-16vram": False, L40S: False}
    assert plans[PLAN]["available_in"] == ["ewr"] and plans[A40]["available_in"] == ["lax", "lhr"]
    assert plans[L40S]["available_in"] == [] and plans[PLAN]["hourly_cost"] == 2.397
    assert plans[PLAN]["cap_hours_at_max_budget"] == pytest.approx(7.9)
    assert sum(c[1].endswith("/availability") for c in calls) == 4            # one per region
    n = len(calls)
    V.main(["plans", "--region", "lax"], transport=t)
    one = {p["id"]: p["available_in"] for p in json.loads(capsys.readouterr().out)}
    assert one[A40] == ["lax"] and one[PLAN] == []
    assert [c[1] for c in calls[n:] if c[1].startswith("/regions")] == ["/regions/lax/availability"]
    V.main(["keys"], transport=t)
    assert json.loads(capsys.readouterr().out) == [{"name": "laptop", "id": "key-uuid-1"}]
    V.main(["balance"], transport=t)
    assert json.loads(capsys.readouterr().out)["pending_charges"] == 3.1
    assert all(c[0] == "GET" for c in calls)


def test_paging_follows_cursor():
    pages = iter([{"plans": [{"id": "vcg-a"}], "meta": {"links": {"next": "CUR"}}},
                  {"plans": [{"id": "vcg-b"}, {"id": "vc2-x"}], "meta": {"links": {"next": ""}}},
                  {"plans": [{"id": "vcg-a"}], "meta": {"links": {"next": ""}}}])
    paths = []

    def t(method, path, body=None):
        paths.append(path)
        return next(pages)
    assert [p["id"] for p in V.gpu_plans(t)] == ["vcg-a", "vcg-b"]
    assert paths == ["/plans?type=all&per_page=500", "/plans?type=all&per_page=500&cursor=CUR",
                     "/plans?type=vcg&per_page=500"]


# --- default password, register-key, wait-active ------------------------------

def test_launch_never_stores_or_prints_default_password(api, capsys):
    calls, ledger, t = api
    V.main(["launch", "--label", "chiron-ablation", "--plan", PLAN, "--region", "ewr", "--ssh-key", "laptop",
            "--os-id", "1743", "--budget-usd", "20", "--approved-by", "author, 2026-11-27 chat"],
           transport=lambda m, p, b=None: t(m, p, b))
    out = capsys.readouterr().out
    assert "inst-new" in out and PASSWORD not in out and "default_password" not in out
    assert "inst-new" in V.LEDGER.read_text(encoding="utf-8")
    assert PASSWORD not in V.LEDGER.read_text(encoding="utf-8")


def test_launch_entry_and_ledger_have_no_password(api):
    calls, ledger, t = api
    e = _go(t, ledger)
    assert PASSWORD not in json.dumps(e) and PASSWORD not in ledger.read_text(encoding="utf-8")
    assert V._scrub({"id": "x", "default_password": "p"}) == {"id": "x"}


@pytest.fixture
def pub(tmp_path):
    f = tmp_path / "id_ed25519.pub"
    f.write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDUMMYDUMMYDUMMY user@laptop\n", encoding="utf-8")
    return f


def test_register_key_posts_public_key_and_logs_no_material(api, pub):
    calls, ledger, t = api
    e = V.register_key("chiron-laptop", pub, ledger, t)
    assert calls[-1] == ("POST", "/ssh-keys", {"name": "chiron-laptop",
                                               "ssh_key": pub.read_text(encoding="utf-8").strip()})
    assert e["event"] == "register_key" and e["id"] == "key-uuid-new" and e["key_type"] == "ssh-ed25519"
    text = ledger.read_text(encoding="utf-8")
    assert "AAAAC3Nza" not in text and '"provider": "vultr"' in text
    assert V.open_instances(V.read_ledger(ledger)) == []          # not mistaken for a launch


def test_register_key_refuses_existing_name(api, pub):
    calls, ledger, t = api
    with pytest.raises(V.GuardrailError, match="already exists"):
        V.register_key("laptop", pub, ledger, t)
    assert not [c for c in calls if c[0] == "POST"] and not ledger.exists()


@pytest.mark.parametrize("content", [
    "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n-----END OPENSSH PRIVATE KEY-----\n",
    "-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----\n",
    "ssh-dss AAAAB3NzaC1kc3M user", "not a key", "",
    "ssh-ed25519 AAAA one\nssh-ed25519 AAAA two"])
def test_register_key_refuses_private_or_odd_files(api, tmp_path, content):
    calls, ledger, t = api
    f = tmp_path / "k"
    f.write_text(content, encoding="utf-8")
    with pytest.raises(V.GuardrailError) as ei:
        V.register_key("new", f, ledger, t)
    assert calls == [] and not ledger.exists()
    assert "b3BlbnNzaC1" not in str(ei.value) and "MIIE" not in str(ei.value)


def test_cli_register_key(api, pub, capsys, monkeypatch, tmp_path):
    calls, ledger, t = api
    V.main(["register-key", "--name", "chiron-laptop", "--pubkey-file", str(pub)], transport=t)
    assert json.loads(capsys.readouterr().out)["id"] == "key-uuid-new"


def _seq_transport(t, states):
    """Wrap the fake so GET /instances/{id} walks through states, then stays on the last."""
    it = iter(states)
    last = {}

    def tr(method, path, body=None):
        if method == "GET" and path.startswith("/instances/"):
            last.update(next(it, last))
            return {"instance": {"id": path.rsplit("/", 1)[1], "default_password": PASSWORD, **last}}
        return t(method, path, body)
    return tr


def test_wait_active_polls_until_active_with_ip(api):
    calls, ledger, t = api
    _launched(ledger, "inst-1")
    tr = _seq_transport(t, [{"status": "pending", "main_ip": "0.0.0.0"},
                            {"status": "active", "main_ip": "0.0.0.0"},
                            {"status": "active", "main_ip": "192.0.2.9"}])
    slept = []
    e = V.wait_active("inst-1", 600, 5, ledger, tr, sleep=slept.append, clock=lambda: 0)
    assert e["ip"] == "192.0.2.9" and e["event"] == "check" and slept == [5, 5]
    text = ledger.read_text(encoding="utf-8")
    assert PASSWORD not in text and len(text.splitlines()) == 2


def test_wait_active_times_out_and_refuses_unknown(api):
    calls, ledger, t = api
    with pytest.raises(V.GuardrailError):
        V.wait_active("inst-x", 10, 1, ledger, t, sleep=lambda s: None)
    _launched(ledger, "inst-1")
    tr = _seq_transport(t, [{"status": "pending", "main_ip": "0.0.0.0"}])
    clock = iter(range(0, 1000, 5))
    with pytest.raises(V.VultrError, match="not active") as ei:
        V.wait_active("inst-1", 20, 5, ledger, tr, sleep=lambda s: None, clock=lambda: next(clock))
    assert PASSWORD not in str(ei.value)
    assert V.read_ledger(ledger)[-1]["job_state"] == "wait_active timeout"


def test_cli_wait_active_prints_ip_first(api, capsys, monkeypatch):
    calls, ledger, t = api
    _launched(ledger, "inst-1")
    monkeypatch.setattr(V, "LEDGER", ledger)
    V.main(["wait-active", "inst-1", "--timeout-s", "60"], transport=t)
    assert capsys.readouterr().out.splitlines()[0] == "192.0.2.7"