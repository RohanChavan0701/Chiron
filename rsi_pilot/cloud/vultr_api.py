"""Vultr Cloud GPU client, the counterpart of cloud.lambda_api, bound by the author's limits in
CLOUD_RUN_VULTR.md (a draft: its guardrail numbers are placeholders until the author sets them).

Every launch, status check and destroy appends a line to ledger_vultr.jsonl (committed; the file
is created by the first event, never empty). The guardrails are enforced here, not left to the
caller:
- at most MAX_OPEN (1) instance: launch refuses while any launch lacks a terminate line;
- plan must be in PLAN_ALLOWLIST (author-named plans only), among the live `vcg-` plans
  (`GET /plans?type=all` merged with `?type=vcg`), and in the region's `available_plans`
  (`GET /regions/{region}/availability`); label prefix `chiron-`; budget and author approval
  are required arguments and recorded on the launch line;
- cap hours = min(MAX_HOURS, whole hours the budget buys at the live hourly price) minus
  DESTROY_MARGIN_HOURS, budget_usd <= MAX_BUDGET_USD, price read from the API at launch. Whole
  hours because Vultr's minimum billing unit is one hour (CLOUD_RUN_VULTR.md, API findings);
- destroy refuses any id that this ledger did not launch;
- `check` destroys any open instance past its cap.

The API key comes from VULTR_API_KEY, else from %USERPROFILE%\\.vultr_key (Windows DPAPI, see
load_key). It is decrypted per request, lives only in memory, and only ever goes into a request
header: never into argv, the ledger, a log line or an exception message.

Usage (from rsi_pilot/):
  python -m cloud.vultr_api plans [--region ewr] | keys | balance
  python -m cloud.vultr_api register-key --name laptop --pubkey-file ~/.ssh/id_ed25519.pub
  python -m cloud.vultr_api launch --label chiron-run8 --plan vcg-a100-12c-120g-80vram \\
      --region ewr --ssh-key NAME \\
      --os-id N --budget-usd 20 --approved-by "author, 2026-11-27 chat" [--user-data FILE]
  python -m cloud.vultr_api wait-active ID [--timeout-s 900]   # prints the IP, then a check line
  python -m cloud.vultr_api status ID [--job-state running]
  python -m cloud.vultr_api destroy ID --reason job_done|cap|error|author
  python -m cloud.vultr_api check [ID] [--job-state running]   # destroys past the cap
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import json
import math
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

BASE_URL = "https://api.vultr.com/v2"
LEDGER = Path(__file__).resolve().parent / "ledger_vultr.jsonl"
KEY_ENV = "VULTR_API_KEY"
KEY_FILE = Path(os.environ.get("USERPROFILE") or Path.home()) / ".vultr_key"
PROVIDER = "vultr"

# Only the author changes the next four constants. Conservative placeholders, 2026-11-27.
MAX_HOURS = 24.0
MAX_BUDGET_USD = 30.0   # raised from 20 by the author in chat on 2026-11-27 ("have the 30 usd capp")
MAX_OPEN = 1
# GPU plan ids (from `plans`) the author has approved, with where the approval came from.
# Launch refuses every plan not listed here.
PLAN_ALLOWLIST: dict[str, str] = {
    "vcg-a100-12c-120g-80vram": 'named by the author in chat on 2026-11-27 ("lets use a100")',
}
GPU_PLAN_PREFIX = "vcg-"

# Destroy a few minutes before the last paid hour ends: the delete call and Vultr's own
# teardown take time, and a partial hour may be billed as a whole one.
DESTROY_MARGIN_HOURS = 0.1
NAME_PREFIX = "chiron-"
MAX_LABEL = 64
USER_AGENT = "chiron-rsi-pilot/0.1"
REASONS = ("job_done", "cap", "error", "author")

Transport = Callable[[str, str, "dict | None"], dict]


class VultrError(RuntimeError):
    pass


class GuardrailError(RuntimeError):
    pass


class KeyLoadError(RuntimeError):
    pass


# --- key loading ------------------------------------------------------------

class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


_CRYPTPROTECT_UI_FORBIDDEN = 0x1


def _dpapi(blob: bytes, protect: bool) -> bytes:
    """CryptProtectData / CryptUnprotectData for the current Windows user, via ctypes."""
    if sys.platform != "win32":
        raise KeyLoadError("DPAPI is Windows-only; set the key in the environment instead")
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    buf = ctypes.create_string_buffer(blob, len(blob))
    inp = _DataBlob(len(blob), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = _DataBlob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(inp), None, None, None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
        raise KeyLoadError(f"DPAPI {'protect' if protect else 'unprotect'} failed "
                           f"(Windows error {ctypes.GetLastError()})")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.memset(out.pbData, 0, out.cbData)
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))
        ctypes.memset(buf, 0, len(blob))


def _dpapi_unprotect(blob: bytes) -> bytes:
    return _dpapi(blob, protect=False)


def decode_key_file(text: str) -> str:
    """Key from the output of PowerShell `Read-Host -AsSecureString | ConvertFrom-SecureString`:
    hex of a DPAPI blob whose plaintext is the UTF-16LE secret. Errors never echo the content."""
    try:
        blob = bytes.fromhex(text.strip())
    except ValueError:
        raise KeyLoadError(f"{KEY_FILE.name} is not the hex output of ConvertFrom-SecureString") from None
    if not blob:
        raise KeyLoadError(f"{KEY_FILE.name} is empty")
    plain = _dpapi_unprotect(blob)
    try:
        key = plain.decode("utf-16-le").strip()
    except UnicodeDecodeError:
        raise KeyLoadError(f"{KEY_FILE.name} does not decrypt to UTF-16 text") from None
    if not key:
        raise KeyLoadError(f"{KEY_FILE.name} decrypts to an empty key")
    return key


def load_key() -> str:
    """VULTR_API_KEY if set, else the DPAPI file (Windows only). Called per request; the caller
    puts the result in a header and drops it."""
    key = os.environ.get(KEY_ENV, "").strip()
    if key:
        return key
    if sys.platform != "win32":
        raise KeyLoadError(f"{KEY_ENV} is not set (the DPAPI key file is Windows-only)")
    if not KEY_FILE.exists():
        raise KeyLoadError(f"{KEY_ENV} is not set and {KEY_FILE} does not exist")
    return decode_key_file(KEY_FILE.read_text(encoding="utf-8-sig"))


# --- API ------------------------------------------------------------------

def _http_request(method: str, path: str, body: dict | None = None, timeout: float = 60) -> dict:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Authorization": f"Bearer {load_key()}", "Content-Type": "application/json",
               "Accept": "application/json", "User-Agent": USER_AGENT}
    req = urllib.request.Request(BASE_URL + path, data=data, method=method, headers=headers)
    del headers
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw.strip() else {}       # DELETE answers 204, no body
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read())
            msg = err.get("error", "") if isinstance(err, dict) else ""
        except (ValueError, AttributeError):
            msg = ""
        raise VultrError(f"{method} {path}: HTTP {e.code} {str(msg)[:300]}".strip()) from None
    except urllib.error.URLError as e:
        raise VultrError(f"{method} {path}: {e.reason}") from None
    finally:
        req.remove_header("Authorization")


def _t(transport: Transport | None) -> Transport:
    return transport or _http_request


def _paged(transport: Transport | None, path: str, key: str) -> list[dict]:
    """Follow meta.links.next cursors (per_page max 500 per the docs)."""
    out, cursor = [], ""
    sep = "&" if "?" in path else "?"
    for _ in range(50):
        r = _t(transport)("GET", f"{path}{sep}per_page=500" + (f"&cursor={cursor}" if cursor else ""), None)
        out += r.get(key, [])
        cursor = (((r.get("meta") or {}).get("links") or {}).get("next") or "")
        if not cursor:
            return out
    raise VultrError(f"{path}: more than 50 pages")


def gpu_plans(transport: Transport | None = None) -> list[dict]:
    """Cloud GPU plans: ids starting `vcg-` from type=all (where the A100/A40/A16 plans live,
    as type `vdm`), merged with type=vcg (L40S), de-duplicated by id. Not filtered on
    gpu_vram_gb or gpu_type, which the live listing leaves empty."""
    out: dict[str, dict] = {}
    for path in ("/plans?type=all", "/plans?type=vcg"):
        for p in _paged(transport, path, "plans"):
            pid = p.get("id") or ""
            if pid.startswith(GPU_PLAN_PREFIX) and pid not in out:
                out[pid] = p
    return list(out.values())


def regions(transport: Transport | None = None) -> list[str]:
    return [r["id"] for r in _paged(transport, "/regions", "regions")]


def available_plans(region: str, transport: Transport | None = None) -> list[str]:
    """Plan ids deployable in region right now (no type filter: with type=vcg the live API
    returned nothing useful)."""
    return list(_t(transport)("GET", f"/regions/{region}/availability", None).get("available_plans") or [])


def ssh_keys(transport: Transport | None = None) -> list[dict]:
    return _paged(transport, "/ssh-keys", "ssh_keys")


def account(transport: Transport | None = None) -> dict:
    r = _t(transport)("GET", "/account", None)
    return r.get("account", r)


SECRET_FIELDS = ("default_password",)


def _scrub(inst: dict) -> dict:
    """Instance object without its root password (create and get responses may carry one)."""
    return {k: v for k, v in (inst or {}).items() if k not in SECRET_FIELDS}


def get_instance(instance_id: str, transport: Transport | None = None) -> dict:
    return _scrub(_t(transport)("GET", f"/instances/{instance_id}", None)["instance"])


PUBKEY_PREFIXES = ("ssh-ed25519 ", "ssh-rsa ", "ecdsa-sha2-")


def read_public_key(path: Path) -> str:
    """One-line OpenSSH public key from path; refuses anything that looks like a private key.
    Errors never echo the file content."""
    text = path.read_text(encoding="utf-8-sig").strip()
    if "PRIVATE KEY" in text or text.startswith("-----BEGIN"):
        raise GuardrailError(f"{path.name} looks like a private key; give the .pub file")
    if not text.startswith(PUBKEY_PREFIXES) or "\n" in text:
        raise GuardrailError(f"{path.name} is not a one-line ssh-ed25519 / ssh-rsa / ecdsa- public key")
    return text


def plan_price_cents(plan: dict, region: str) -> float:
    """Live hourly price in cents for this plan in this region: the higher of the plan price and
    the region's location_cost price, if both are listed."""
    prices = [plan.get("hourly_cost"), ((plan.get("location_cost") or {}).get(region) or {}).get("hourly_cost")]
    vals = [float(p) for p in prices if p is not None]
    if not vals:
        raise GuardrailError(f"{plan.get('id')} has no hourly_cost in the listing")
    return round(max(vals) * 100, 4)


def allowed_plan(plans: list[dict], plan_id: str, region: str,
                 transport: Transport | None = None) -> tuple[str, float]:
    """(plan id, live cents/hour) for an allowlisted GPU plan available in region, else refuse.
    Availability comes from /regions/{region}/availability, not the plan's `locations` (empty
    in the live listing)."""
    if plan_id not in PLAN_ALLOWLIST:
        raise GuardrailError(f"plan {plan_id!r} is not in PLAN_ALLOWLIST "
                             f"({sorted(PLAN_ALLOWLIST) or 'empty: the author has not named a plan'})")
    hits = [p for p in plans if p.get("id") == plan_id]
    if len(hits) != 1:
        raise GuardrailError(f"plan {plan_id!r} is not (exactly once) in the live Cloud GPU listing")
    if plan_id not in available_plans(region, transport):
        raise GuardrailError(f"{plan_id} is not available in {region} right now")
    return plan_id, plan_price_cents(hits[0], region)


def resolve_ssh_key(keys: list[dict], name: str) -> str:
    hits = [k["id"] for k in keys if k.get("name") == name or k.get("id") == name]
    if len(hits) != 1:
        raise GuardrailError(f"expected exactly one SSH key named {name!r}, found {len(hits)}")
    return hits[0]


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
        f.write(json.dumps({**entry, "provider": PROVIDER}) + "\n")


def cap_hours(price_cents_per_hour: float, budget_usd: float) -> float:
    """min(MAX_HOURS, whole hours the budget buys) - DESTROY_MARGIN_HOURS."""
    if not price_cents_per_hour > 0:
        raise GuardrailError(f"implausible price {price_cents_per_hour} cents/hour")
    if not 0 < budget_usd <= MAX_BUDGET_USD:
        raise GuardrailError(f"budget must be in (0, {MAX_BUDGET_USD}] dollars per launch: {budget_usd}")
    whole = math.floor(budget_usd * 100 / price_cents_per_hour + 1e-9)
    if whole < 1:
        raise GuardrailError(f"${budget_usd} does not buy one billed hour at {price_cents_per_hour} cents/hour")
    return min(MAX_HOURS, whole) - DESTROY_MARGIN_HOURS


def launches(rows: list[dict]) -> dict[str, dict]:
    return {r["id"]: r for r in rows if r["event"] == "launch"}


def open_instances(rows: list[dict]) -> list[str]:
    """Launched by this ledger and not yet terminated."""
    done = {r["id"] for r in rows if r["event"] == "terminate"}
    return [i for i in launches(rows) if i not in done]


def elapsed_and_spend(launch: dict, at: datetime) -> tuple[float, float]:
    """Hours since launch, and spend with every started hour billed (minimum one hour)."""
    hours = (at - datetime.fromisoformat(launch["launched_at"])).total_seconds() / 3600
    billed = max(1, math.ceil(hours - 1e-9))
    return hours, billed * launch["price_cents_per_hour"] / 100


# --- operations (each writes the ledger) ----------------------------------

def launch(label: str, plan: str, region: str, ssh_key: str, approved_by: str | None,
           budget_usd: float | None, os_id: int | None = None, image_id: str | None = None,
           user_data: str | None = None, ledger: Path = LEDGER,
           transport: Transport | None = None) -> dict:
    if not label.startswith(NAME_PREFIX) or len(label) > MAX_LABEL:
        raise GuardrailError(f"label must start with {NAME_PREFIX!r} and be <= {MAX_LABEL} chars: {label!r}")
    if not (approved_by or "").strip():
        raise GuardrailError("every launch needs the author's go-ahead (--approved-by)")
    if budget_usd is None:
        raise GuardrailError("every launch needs an explicit --budget-usd")
    if (os_id is None) == (image_id is None):
        raise GuardrailError("give exactly one of os_id or image_id")
    if not 0 < budget_usd <= MAX_BUDGET_USD:
        raise GuardrailError(f"budget must be in (0, {MAX_BUDGET_USD}] dollars per launch: {budget_usd}")
    still_open = open_instances(read_ledger(ledger))
    if len(still_open) >= MAX_OPEN:
        raise GuardrailError(f"{len(still_open)} instance(s) without a terminate line "
                             f"(max {MAX_OPEN}): {still_open}")
    plan_id, price = allowed_plan(gpu_plans(transport), plan, region, transport)
    hours = cap_hours(price, budget_usd)
    key_id = resolve_ssh_key(ssh_keys(transport), ssh_key)
    body = {"region": region, "plan": plan_id, "label": label, "hostname": label,
            "sshkey_id": [key_id], "tags": ["chiron"], "backups": "disabled"}
    if os_id is not None:
        body["os_id"] = int(os_id)
    else:
        body["image_id"] = image_id
    if user_data:
        body["user_data"] = base64.b64encode(user_data.encode()).decode()
    t = now_utc()          # taken before the call: billing may start before the response
    inst = _scrub(_t(transport)("POST", "/instances", body).get("instance"))   # drop default_password
    iid = inst.get("id")
    if not iid:
        raise VultrError("create instance returned no instance id; check the console for a stray instance")
    entry = {"event": "launch", "id": iid, "name": label, "type": plan_id, "region": region,
             "price_cents_per_hour": price, "launched_at": _iso(t),
             "terminate_by": _iso(t + timedelta(hours=hours)), "cap_hours": round(hours, 3),
             "budget_usd": round(budget_usd, 2), "os_id": os_id, "image_id": image_id,
             "filesystem": None, "approved_by_author": approved_by}
    append_ledger(entry, ledger)
    return entry


def status(instance_id: str, job_state: str = "", ledger: Path = LEDGER,
           transport: Transport | None = None) -> dict:
    rows = read_ledger(ledger)
    lau = launches(rows).get(instance_id)
    if lau is None:
        raise GuardrailError(f"{instance_id} is not in the ledger")
    inst = get_instance(instance_id, transport)
    t = now_utc()
    hours, spend = elapsed_and_spend(lau, t)
    entry = {"event": "check", "id": instance_id, "time": _iso(t), "status": inst.get("status"),
             "power_status": inst.get("power_status"), "server_status": inst.get("server_status"),
             "ip": inst.get("main_ip"), "hours_elapsed": round(hours, 3),
             "est_spend_usd": round(spend, 2), "job_state": job_state,
             "past_cap": t >= datetime.fromisoformat(lau["terminate_by"])}
    append_ledger(entry, ledger)
    return entry


def destroy(instance_id: str, reason: str, ledger: Path = LEDGER,
            transport: Transport | None = None) -> dict:
    if reason not in REASONS:
        raise GuardrailError(f"reason must be one of {REASONS}")
    rows = read_ledger(ledger)
    lau = launches(rows).get(instance_id)
    if lau is None:
        raise GuardrailError(f"refusing to destroy {instance_id}: not launched by this ledger")
    if instance_id not in open_instances(rows):
        raise GuardrailError(f"{instance_id} already has a terminate line")
    _t(transport)("DELETE", f"/instances/{instance_id}", None)
    t = now_utc()
    hours, spend = elapsed_and_spend(lau, t)
    entry = {"event": "terminate", "id": instance_id, "time": _iso(t), "reason": reason,
             "hours_elapsed": round(hours, 3), "est_spend_usd": round(spend, 2)}
    append_ledger(entry, ledger)
    return entry


def check(instance_id: str | None = None, job_state: str = "", ledger: Path = LEDGER,
          transport: Transport | None = None) -> list[dict]:
    """Status of one (or every open) ledger instance; destroys any past its cap or budget."""
    rows = read_ledger(ledger)
    ids = [instance_id] if instance_id else open_instances(rows)
    out = []
    for iid in ids:
        e = status(iid, job_state, ledger, transport)
        out.append(e)
        if iid in open_instances(read_ledger(ledger)) and (
                e["past_cap"] or e["est_spend_usd"] > launches(rows)[iid]["budget_usd"]):
            out.append(destroy(iid, "cap", ledger, transport))
    return out


def register_key(name: str, pubkey_file: Path, ledger: Path = LEDGER,
                 transport: Transport | None = None) -> dict:
    """POST /ssh-keys with a public key file. The ledger line holds name, id and key type only."""
    if not name.strip():
        raise GuardrailError("the SSH key needs a name")
    pub = read_public_key(Path(pubkey_file))
    if any(k.get("name") == name for k in ssh_keys(transport)):
        raise GuardrailError(f"an SSH key named {name!r} already exists on the account")
    r = _t(transport)("POST", "/ssh-keys", {"name": name, "ssh_key": pub})
    kid = (r.get("ssh_key") or {}).get("id")
    if not kid:
        raise VultrError("create SSH key returned no id")
    entry = {"event": "register_key", "id": kid, "name": name, "key_type": pub.split()[0],
             "time": _iso(now_utc())}
    append_ledger(entry, ledger)
    return entry


def wait_active(instance_id: str, timeout_s: float = 900, interval_s: float = 15,
                ledger: Path = LEDGER, transport: Transport | None = None,
                sleep: Callable[[float], None] | None = None, clock: Callable[[], float] | None = None) -> dict:
    """Poll until status is active and main_ip is assigned; then one ledger check line."""
    import time
    sleep, clock = sleep or time.sleep, clock or time.monotonic
    if instance_id not in launches(read_ledger(ledger)):
        raise GuardrailError(f"{instance_id} is not in the ledger")
    end = clock() + timeout_s
    while True:
        inst = get_instance(instance_id, transport)
        if inst.get("status") == "active" and inst.get("main_ip") not in (None, "", "0.0.0.0"):
            return status(instance_id, "active", ledger, transport)
        if clock() >= end:
            e = status(instance_id, "wait_active timeout", ledger, transport)
            raise VultrError(f"{instance_id} not active with an IP after {timeout_s:.0f} s "
                             f"(status {e['status']}, ip {e['ip']})")
        sleep(interval_s)


# --- CLI ------------------------------------------------------------------

def main(argv: list[str] | None = None, transport: Transport | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m cloud.vultr_api")
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("plans")
    pp.add_argument("--region", help="check availability in this region only (default: every region)")
    for c in ("keys", "balance"):
        sub.add_parser(c)
    pl = sub.add_parser("launch")
    pl.add_argument("--label", required=True)
    pl.add_argument("--plan", required=True)
    pl.add_argument("--region", required=True)
    pl.add_argument("--ssh-key", required=True, help="SSH key name (or id) on the account")
    pl.add_argument("--approved-by", required=True)
    pl.add_argument("--budget-usd", type=float, required=True)
    img = pl.add_mutually_exclusive_group(required=True)
    img.add_argument("--os-id", type=int)
    img.add_argument("--image-id")
    pl.add_argument("--user-data", type=Path, help="cloud-init user-data file (sent base64)")
    ps = sub.add_parser("status")
    ps.add_argument("id")
    ps.add_argument("--job-state", default="")
    pd = sub.add_parser("destroy")
    pd.add_argument("id")
    pd.add_argument("--reason", required=True, choices=REASONS)
    pc = sub.add_parser("check")
    pc.add_argument("id", nargs="?")
    pc.add_argument("--job-state", default="")
    pr = sub.add_parser("register-key")
    pr.add_argument("--name", required=True)
    pr.add_argument("--pubkey-file", type=Path, required=True)
    pw = sub.add_parser("wait-active")
    pw.add_argument("id")
    pw.add_argument("--timeout-s", type=float, default=900)
    a = p.parse_args(argv)

    if a.cmd == "plans":
        avail = {r: set(available_plans(r, transport)) for r in ([a.region] if a.region else regions(transport))}
        out = []
        for pln in gpu_plans(transport):
            price = pln.get("hourly_cost")
            out.append({"id": pln.get("id"), "hourly_cost": price,
                        "allowlisted": pln.get("id") in PLAN_ALLOWLIST,
                        "available_in": sorted(r for r, ids in avail.items() if pln.get("id") in ids),
                        "cap_hours_at_max_budget": (round(cap_hours(float(price) * 100, MAX_BUDGET_USD), 2)
                                                    if price and float(price) <= MAX_BUDGET_USD else None)})
    elif a.cmd == "keys":
        out = [{"name": k.get("name"), "id": k.get("id")} for k in ssh_keys(transport)]
    elif a.cmd == "balance":
        acc = account(transport)
        out = {k: acc.get(k) for k in ("balance", "pending_charges", "last_payment_date", "last_payment_amount")}
    elif a.cmd == "launch":
        ud = a.user_data.read_text(encoding="utf-8") if a.user_data else None
        out = launch(a.label, a.plan, a.region, a.ssh_key, a.approved_by, a.budget_usd,
                     os_id=a.os_id, image_id=a.image_id, user_data=ud, ledger=LEDGER, transport=transport)
    elif a.cmd == "status":
        out = status(a.id, a.job_state, LEDGER, transport)
    elif a.cmd == "destroy":
        out = destroy(a.id, a.reason, LEDGER, transport)
    elif a.cmd == "register-key":
        out = register_key(a.name, a.pubkey_file, LEDGER, transport)
    elif a.cmd == "wait-active":
        out = wait_active(a.id, a.timeout_s, ledger=LEDGER, transport=transport)
        print(out["ip"])                    # first line: the IP alone, for scripts
    else:
        out = check(a.id, a.job_state, LEDGER, transport)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
