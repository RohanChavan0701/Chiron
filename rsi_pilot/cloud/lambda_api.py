"""Lambda Cloud client for run 4 and the poisoning audit, bound by the author's limits in
CLOUD_RUN.md.

Every launch, status check and termination appends a line to ledger.jsonl (committed). The
guardrails are enforced here, not left to the caller:
- at most MAX_OPEN instances: launch refuses while that many launches lack a terminate;
- 1x A10 only, name prefix `chiron-`, author approval recorded on the launch line;
- cap hours = min(48, budget_usd * 100 / live price_cents_per_hour), budget_usd <= $50, price
  read from the API at launch;
- terminate refuses any id that this ledger did not launch.

The API key is read from LAMBDA_API_KEY and only ever goes into a request header. Module named
lambda_api (not lambda.py as in the plan) because `lambda` is a Python keyword and cannot be
imported.

Usage (from rsi_pilot/):
  python -m cloud.lambda_api types | keys | filesystems | instances
  python -m cloud.lambda_api launch --name chiron-run4-a --region us-east-1 --ssh-key NAME \
      --approved-by "author, 2026-11-04 chat" [--filesystem FS] [--user-data FILE]
  python -m cloud.lambda_api status ID [--job-state running]
  python -m cloud.lambda_api terminate ID --reason job_done|cap|error|author
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_URL = "https://cloud.lambda.ai/api/v1"
LEDGER = Path(__file__).resolve().parent / "ledger.jsonl"

MAX_HOURS = 48.0
MAX_USD = 50.0
# Author, 2026-11-03: up to 3 run-4 A10s at once besides the adopted run-5 instance, run 4
# total $50, so each run-4 launch gets budget_usd = 50 / 3.
MAX_OPEN = 4
NAME_PREFIX = "chiron-"
# Lambda's Cloudflare front blocks urllib's default User-Agent (error 1010, HTTP 403).
USER_AGENT = "chiron-rsi-pilot/0.1"
REASONS = ("job_done", "cap", "error", "author")


class LambdaError(RuntimeError):
    pass


class GuardrailError(RuntimeError):
    pass


# --- API ------------------------------------------------------------------

def _request(method: str, path: str, body: dict | None = None, timeout: float = 60) -> dict:
    key = os.environ.get("LAMBDA_API_KEY")
    if not key:
        raise LambdaError("LAMBDA_API_KEY is not set")
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE_URL + path, data=data, method=method, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        "Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read()).get("error", {})
        except (ValueError, AttributeError):
            err = {}
        raise LambdaError(f"{method} {path}: HTTP {e.code} {err.get('code', '')} "
                          f"{err.get('message', '')} {err.get('suggestion', '')}".strip()) from None


def instance_types() -> dict:
    return _request("GET", "/instance-types")["data"]


def ssh_keys() -> list[dict]:
    return _request("GET", "/ssh-keys")["data"]


def filesystems() -> list[dict]:
    return _request("GET", "/filesystems")["data"]


def instances() -> list[dict]:
    return _request("GET", "/instances")["data"]


def a10_type(types: dict) -> tuple[str, int, list[str]]:
    """(type name, live price in cents/hour, regions with capacity) for the single 1x A10 type.
    Matched on the specs, not a remembered name; fails if there is not exactly one."""
    hits = [(name, t) for name, t in types.items()
            if "A10" in t["instance_type"]["gpu_description"].split()
            and t["instance_type"]["specs"]["gpus"] == 1]
    if len(hits) != 1:
        raise GuardrailError(f"expected exactly one 1x A10 type, found {[n for n, _ in hits]}")
    name, t = hits[0]
    return (name, int(t["instance_type"]["price_cents_per_hour"]),
            [r["name"] for r in t["regions_with_capacity_available"]])


# --- ledger and cap arithmetic --------------------------------------------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).isoformat(timespec="seconds")


def read_ledger(ledger: Path = LEDGER) -> list[dict]:
    if not ledger.exists():
        return []
    return [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_ledger(entry: dict, ledger: Path = LEDGER) -> None:
    with ledger.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def cap_hours(price_cents_per_hour: int, budget_usd: float = MAX_USD) -> float:
    if price_cents_per_hour <= 0:
        raise GuardrailError(f"implausible price {price_cents_per_hour} cents/hour")
    if not 0 < budget_usd <= MAX_USD:
        raise GuardrailError(f"budget must be in (0, {MAX_USD}] dollars per launch: {budget_usd}")
    return min(MAX_HOURS, budget_usd * 100 / price_cents_per_hour)


def launches(rows: list[dict]) -> dict[str, dict]:
    return {r["id"]: r for r in rows if r["event"] == "launch"}


def open_instances(rows: list[dict]) -> list[str]:
    """Launched by this ledger and not yet terminated."""
    done = {r["id"] for r in rows if r["event"] == "terminate"}
    return [i for i in launches(rows) if i not in done]


def elapsed_and_spend(launch: dict, at: datetime) -> tuple[float, float]:
    hours = (at - datetime.fromisoformat(launch["launched_at"])).total_seconds() / 3600
    return hours, hours * launch["price_cents_per_hour"] / 100


# --- operations (each writes the ledger) ----------------------------------

def launch(name: str, region: str, ssh_key: str, approved_by: str,
           filesystem: str | None = None, user_data: str | None = None,
           budget_usd: float = MAX_USD, ledger: Path = LEDGER) -> dict:
    if not name.startswith(NAME_PREFIX) or len(name) > 64:
        raise GuardrailError(f"name must start with {NAME_PREFIX!r} and be <= 64 chars: {name!r}")
    if not approved_by.strip():
        raise GuardrailError("every launch needs the author's go-ahead (--approved-by)")
    still_open = open_instances(read_ledger(ledger))
    if len(still_open) >= MAX_OPEN:
        raise GuardrailError(f"{len(still_open)} instances without a terminate line "
                             f"(max {MAX_OPEN}): {still_open}")
    type_name, price, regions = a10_type(instance_types())
    if region not in regions:
        raise GuardrailError(f"no {type_name} capacity in {region}; available: {regions}")
    hours = cap_hours(price, budget_usd)
    body = {"region_name": region, "instance_type_name": type_name, "ssh_key_names": [ssh_key],
            "name": name}
    if filesystem:
        body["file_system_names"] = [filesystem]
    if user_data:
        body["user_data"] = user_data
    ids = _request("POST", "/instance-operations/launch", body)["data"]["instance_ids"]
    t = now_utc()
    entry = {}
    for iid in ids:
        entry = {"event": "launch", "id": iid, "name": name, "type": type_name, "region": region,
                 "price_cents_per_hour": price, "launched_at": _iso(t),
                 "terminate_by": _iso(t + timedelta(hours=hours)), "cap_hours": round(hours, 3),
                 "budget_usd": round(budget_usd, 2),
                 "filesystem": filesystem, "approved_by_author": approved_by}
        append_ledger(entry, ledger)
    if len(ids) != 1:
        raise GuardrailError(f"expected one instance, API launched {ids}; terminate the extras")
    return entry


def status(instance_id: str, job_state: str = "", ledger: Path = LEDGER) -> dict:
    lau = launches(read_ledger(ledger)).get(instance_id)
    if lau is None:
        raise GuardrailError(f"{instance_id} is not in the ledger")
    inst = _request("GET", f"/instances/{instance_id}")["data"]
    t = now_utc()
    hours, spend = elapsed_and_spend(lau, t)
    entry = {"event": "check", "id": instance_id, "time": _iso(t), "status": inst.get("status"),
             "ip": inst.get("ip"), "hours_elapsed": round(hours, 3),
             "est_spend_usd": round(spend, 2), "job_state": job_state,
             "past_cap": t >= datetime.fromisoformat(lau["terminate_by"])}
    append_ledger(entry, ledger)
    return entry


def terminate(instance_id: str, reason: str, ledger: Path = LEDGER) -> dict:
    if reason not in REASONS:
        raise GuardrailError(f"reason must be one of {REASONS}")
    rows = read_ledger(ledger)
    lau = launches(rows).get(instance_id)
    if lau is None:
        raise GuardrailError(f"refusing to terminate {instance_id}: not launched by this ledger")
    if instance_id not in open_instances(rows):
        raise GuardrailError(f"{instance_id} already has a terminate line")
    _request("POST", "/instance-operations/terminate", {"instance_ids": [instance_id]})
    t = now_utc()
    hours, spend = elapsed_and_spend(lau, t)
    entry = {"event": "terminate", "id": instance_id, "time": _iso(t), "reason": reason,
             "hours_elapsed": round(hours, 3), "est_spend_usd": round(spend, 2)}
    append_ledger(entry, ledger)
    return entry


# --- CLI ------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m cloud.lambda_api")
    sub = p.add_subparsers(dest="cmd", required=True)
    for c in ("types", "keys", "filesystems", "instances"):
        sub.add_parser(c)
    pl = sub.add_parser("launch")
    pl.add_argument("--name", required=True)
    pl.add_argument("--region", required=True)
    pl.add_argument("--ssh-key", required=True)
    pl.add_argument("--approved-by", required=True)
    pl.add_argument("--filesystem")
    pl.add_argument("--user-data", type=Path, help="cloud-init user-data file")
    pl.add_argument("--budget-usd", type=float, default=MAX_USD)
    ps = sub.add_parser("status")
    ps.add_argument("id")
    ps.add_argument("--job-state", default="")
    pt = sub.add_parser("terminate")
    pt.add_argument("id")
    pt.add_argument("--reason", required=True, choices=REASONS)
    a = p.parse_args(argv)

    if a.cmd == "types":
        name, price, regions = a10_type(instance_types())
        out = {"a10_type": name, "price_cents_per_hour": price, "cap_hours": round(cap_hours(price), 2),
               "regions_with_capacity": regions}
    elif a.cmd == "keys":
        out = [k["name"] for k in ssh_keys()]
    elif a.cmd == "filesystems":
        out = [{k: f.get(k) for k in ("name", "region", "bytes_used", "is_in_use", "mount_point")}
               for f in filesystems()]
    elif a.cmd == "instances":
        out = [{k: i.get(k) for k in ("id", "name", "status", "region")} for i in instances()]
    elif a.cmd == "launch":
        ud = a.user_data.read_text(encoding="utf-8") if a.user_data else None
        out = launch(a.name, a.region, a.ssh_key, a.approved_by, a.filesystem, ud, a.budget_usd)
    elif a.cmd == "status":
        out = status(a.id, a.job_state)
    else:
        out = terminate(a.id, a.reason)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
