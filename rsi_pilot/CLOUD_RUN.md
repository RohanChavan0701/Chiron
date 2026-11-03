# Running run 4 on a Lambda instance launched by an agent session

Status: plan only. Nothing here has been run, and the Lambda API details marked "verify" were not
checked against Lambda's docs (docs.lambda.ai was not reachable from the session that wrote this).

## Guardrails (set by the author, 2026-11-03)

- **Instance:** one A10 (1x A10 type; confirm the exact type name from the instance-types endpoint).
- **Time cap:** 48 hours wall clock from launch.
- **Spend cap:** $50. Effective cap = min(48 h, 5000 / live `price_cents_per_hour` hours), using the
  price the API reports at launch, not a remembered price.
- **Scope:** the agent terminates only instances it launched, matched by the instance id recorded
  in `cloud/ledger.jsonl` at launch, never by name or type alone. Instances already in the account
  (e.g. the author's own A10) are never touched.
- **Name prefix:** `chiron-run4-` for anything the agent launches.
- **Termination:** at job completion or at the cap, whichever is first. Termination must not depend
  on one session staying alive: schedule a one-shot terminate at `terminate_by` when launching, and
  check on each session wake as well.
- **One at a time:** no second launch while the ledger has an instance not marked terminated.

## Ledger (`rsi_pilot/cloud/ledger.jsonl`, committed)

One line per event: `launch` (id, type, region, price_cents_per_hour, launched_at, terminate_by,
cap_reason), `check` (time, status, est_spend), `terminate` (time, reason, est_spend). Estimated
spend = hours since launch x launch price. The author can audit spend from git history alone.

## Job on the instance

Run 4 seeds in pre-registered order, one at a time, pushing results after each seed so a cap hit
loses at most the seed in progress:

```bash
cd rsi_pilot && for s in 20261111 20261112 20261113; do scripts/run_v4.sh $s 4 && <push runs_v4/s$s>; done
```

Throughput is unknown (3 arms in parallel, 1.5B student and 32B proposer/critic on one 24 GB card).
Expect 48 hours to cover two seeds, possibly three. Time seed 1 and decide before seed 3 starts.
E2 (poison audit) does not fit in this budget; it needs these three seeds as its clean control.

Push only run outputs (`runs_v4/s<SEED>/` minus `cache/`, `splits_v4_s<SEED>.json`,
`frozen_v4_s<SEED>.yaml`), to a branch, not `main`.

## Needed before launch

1. `LAMBDA_API_KEY` as a network secret or environment variable, and `cloud.lambda.ai`,
   `cloud.lambdalabs.com`, `docs.lambda.ai` in the environment's allowed domains. New session.
2. **Data on the instance.** Spider (dev, train, `database/`), BIRD Mini-Dev SQLite, Spider
   test-suite databases. Not in git. Either a Lambda persistent filesystem that already holds
   `rsi_pilot/data/` from runs 1-3 (attach at launch; verify the field name), or download URLs
   the author confirms.
3. **A way to get results back.** The session cannot reach the instance except through the Lambda
   API (raw TCP is blocked; SSH through the HTTPS proxy is unverified). Options: a fine-grained
   GitHub token scoped to this repo with contents:write and a short expiry, used by the instance to
   push; or the author pulls results manually. Author's call; a token placed in a startup script is
   visible in the instance's metadata.
4. **Models:** `ollama pull qwen2.5:1.5b-instruct` and `qwen2.5:32b-instruct` on the instance
   (about 20 GB for the 32B).

## Verify in the next session, before spending anything

- Launch request fields: instance name, startup script (`user_data` or equivalent), filesystem
  attachment, SSH key requirement.
- Whether shutting down the OS stops billing, or only the terminate endpoint does. Assume only
  terminate does until confirmed.
- Whether the proxy allows SSH to an instance IP. If not, the instance must configure and run
  itself from its startup script.
- Live A10 price and availability by region.
