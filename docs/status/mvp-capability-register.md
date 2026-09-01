# MVP Capability Register

Issue: #282

## Purpose and reading rules

This register records what the MVP can actually do, with a supporting result and a named owner
for every claim. It is a status record observed at a point in time, not a contract. It does not
redefine `SPEC/`, the API contract, or any engineering document, and a capability listed here is
only as good as the evidence in its row.

Compiled against `main` at `26d6d790`, which carries the #271 canonical path validation and the #281 regression entry point. Every command in the re-derivation section below exists on that commit and was run there to produce the classifications recorded here.

PR #350 updates the two local-provider rows owned by `@liyang6620` after synchronising with
`main@4c90e2a`. Those rows use the real local MongoDB/MinIO smoke and six-case governed RAG
evaluation recorded in `docs/status/runtime-profile-validation.md`; the other rows retain the
original #282 evidence base.

Status vocabulary is the one fixed by the Sprint 2 Week 4 baseline:

- **verified** — the named capability and environment were directly demonstrated and the
  acceptance evidence is recorded;
- **partial** — a meaningful slice works, but one or more required capabilities or conditions
  are not verified;
- **unavailable** — the selected environment cannot currently provide the capability and fails
  explicitly;
- **fixture-dependent** — behaviour is repeatable against fixtures or mocks and is not evidence
  of a live provider.

Two rules govern every row. A check that did not execute is not evidence, so a capability whose
proof requires a provider nobody contacted is not `verified`. And a demonstration is not a
production capability: `fixture-dependent` is a real, useful status, not a softer way of saying
`verified`.

## Verified

| Capability | Evidence | Owner |
| --- | --- | --- |
| Fail-closed identity boundary | #247 via merged PR #323. Normal mode rejects every repository synthetic credential with 401 before consulting a synthetic profile; developer mode is an explicit startup choice restricted to a `development`/`test` allow-list and rejected elsewhere at startup; a registered credential at the wrong actor boundary returns 403 while missing or unknown returns 401; no request header, body, or query can manufacture a principal. Demonstrated by composing the app in both modes, and independently rechecked with 57 focused tests. | @jxu316-arch |
| One authoritative Claim State transaction boundary | #237 via merged PR #288. Both implemented adapters reject a revision that is not exactly `expected_revision + 1` and any non-session change to `active_session_id`, before any write, while a stale caller still receives `RevisionConflict`. Same-claim reuse of an immutable `message` or `agent_decision` identity is rejected with the snapshot unchanged. Adapter-parametrised regressions cover each case and were confirmed to fail without the guards. | @jxu316-arch |
| Canonical scenario and evidence baseline | #241 and #251 via merged PRs #324, #348 and #312. Five canonical MVP business paths each resolve to exactly one scenario, entry baselines bind workflow, action, evidence state, claimant next step and handoff shape, and loading fails on stale or contradictory declarations. | @bdfa123 |
| Claimant/staff visibility boundary on the five MVP paths | #271. Staff see the complete canonical evidence set on every path while no retrieval identifier, `internal_only` message identifier, or internal handoff identifier reaches a claimant; a handoff the claimant requested is visible to them by design. Repeatable with `python scripts/run_canonical_path_validation.py`, and confirmed load-bearing by disabling the projection filter. | @bdfa123 |
| Runtime profile isolation and fail-closed refusal | #256 via merged PRs #332 and #335. `python scripts/validate_runtime_profiles.py` reports `isolation: verified_fail_closed`; the `fixture` profile starts ready, and `mongodb`, `cloudflare` and `aws` refuse startup with errors naming only missing capabilities, without listening on a port or assembling a fixture fallback. | @liyang6620 |
| Local MVP data composition | PR #350 verifies the explicit `local_mvp` profile against a local transaction-capable MongoDB replica set and the packaged MinIO service. `python scripts/run_local_mvp_smoke.py` proves Claim, Session, Message, Evidence metadata, Retrieval, Review Signal and Idempotency recovery after application reconstruction; protected Evidence bytes remain in MinIO; stale revisions and a conflicting retrieval bundle leave no partial write. Policy and claim history remain explicitly synthetic, so this row does not promote the provider-specific `mongodb` profile or claim Atlas conformance. | @liyang6620 |
| Knowledge retrieval against a real ingested MinIO store | PR #350 records `python scripts/verify_local_rag.py config/rag-evaluation-cases.json` passing all six governed cases against the packaged MinIO service. Applicable results retain exact document, version, section and checksum citations; wrong-insurer and untrusted-instruction cases return no result. This verifies the named local environment only, not Atlas Search, a vector index, or automatic Agent-to-RAG orchestration. | @liyang6620 |

## Fixture-dependent

| Capability | Evidence | Owner |
| --- | --- | --- |
| Canonical demo scenarios and Workbench demo queue | Seven fixture-backed checks pass through `python scripts/run_regression_entrypoints.py` on a bare clone. All records, identifiers, provider responses and outcomes are synthetic. | @bdfa123 |
| Claimant external-service experience and controlled assessor adapter | #262 and #272 via merged PRs #300, #302 and #308, recorded in `docs/archive/sprint-2/validation/day4-external-service-validation.md`. Covers clean success, consent refusal, service unavailable, timeout, retry and replay — all against the controlled adapter, not a live assessor service. | @bdfa123 |
| Structured MVP record graph on AT-02 | #251 via merged PR #348. Typed policy and claim-history retrievals, evidence, messages and a professional-review handoff connect through stable identifiers, and staff receive them through the existing claim-detail route. Synthetic records only; no provider supplied any of them. | @bdfa123 |
| Evidence object storage in the default profile | The default `object_storage_adapter` is `fixture`. Presigned addressing and claimant-safe metadata behaviour are exercised against that adapter, not against a live store, unless MinIO is configured. | @liyang6620 |
| Admin API configuration lifecycle | Merged PR #498 wires `require_administrator` to `/internal/v1/admin/configurations` and provides versioned draft, validation, publication, withdrawal, rollback, and audit behavior over the in-memory configuration repository. API tests cover the lifecycle, revision and idempotency conflicts, secret rejection, provider-neutral validation, administrator access, and non-administrator rejection. This is repeatable fixture-backed behavior, not a production identity or persistence claim. | @LLL263 |

## Partial

| Capability | Evidence and what is missing | Owner |
| --- | --- | --- |
| Live model-backed intake | #244 and merged PR #352 provide the provider-neutral gateway, an explicit `model_gateway` profile, and configuration and transport tests. The default `agent_runtime_profile` is `controlled` with an empty `model_base_url`, and `docs/model-gateway.md` states a deployment is live only after the configured endpoint is reached. No recorded run in this repository demonstrates a live model call, so the live path is configured and tested rather than verified. | @Ysoseri1224 |
| MongoDB persistence profile | `validate_runtime_profiles.py` classifies `mongodb` as `partial` with `startup_refused`, and `docs/status/runtime-profile-validation.md` records that connection primitives and a bounded probe exist but the configured Atlas probe was unavailable during that run. Persistence alone cannot supply evidence, policy/history or knowledge capabilities, so the profile is not selected at runtime. | @liyang6620 |
| Claimant-to-staff messaging | Merged PR #339 closes the #248 authority and continuity gaps: staff send requires the authoritative active session and an accepted handoff assigned to the authenticated principal, `in_reply_to` cannot cross claim or session boundaries or target internal material, and claimant visibility is filtered before keyset pagination. Issue #248 remains open, so the slice is implemented and reviewed but not declared complete by its owner. | @jxu316-arch |
| Connected evidence and canonical data journey | Merged PR #312 delivers the #261 journey and its acceptance evidence is recorded, but issue #261 remains open because the pull request used `Refs` rather than `Closes`. The behaviour is on `main`; the issue closure is outstanding. | @bdfa123 |

## Unavailable

| Capability | Evidence | Owner |
| --- | --- | --- |
| AWS data runtime profile | `validate_runtime_profiles.py` classifies `aws` as `unavailable` with `startup_refused`; services, permissions, schema, region, credentials and deployment target are unconfirmed. | @liyang6620 |
| Cloudflare data runtime profile | Classified `unavailable` with `startup_refused`; provider services, bindings, schema and credentials are unconfirmed. | @liyang6620 |
| Live MinIO object storage in an unconfigured environment | `docs/status/runtime-profile-validation.md` records `local-minio` as `verified` in an environment with the packaged MinIO service present. In a bare clone the same classification is `unavailable`, and `run_minio_fastapi_smoke.py` refuses with `Set NORTHWIND_OBJECT_STORAGE_ADAPTER=s3_compatible`. Both statements are true of different environments; the capability is verified only where that provider is actually running. | @liyang6620 |
| Persisted identity access audit | The identity contract requires every verified principal to expose non-secret metadata for an audit record, and `Principal` now carries `auth_source` and `synthetic`. No access-audit persistence exists. | @jxu316-arch |

## What this register deliberately does not claim

- No row asserts production readiness. Nothing here has been demonstrated against Northwind
  systems, real policyholder data, or a production deployment target.
- No AWS, Cloudflare, MongoDB, MinIO or model-provider capability is inferred from a
  provider-neutral contract, a passing configuration test, or a successful fixture run.
- The five canonical MVP paths are synthetic demonstrations. They prove repository behaviour and
  projection boundaries, not claim-handling outcomes.
- Coverage, test counts and green checks are inputs to a row, never a row on their own.

## How to re-derive this register

```text
python scripts/run_regression_entrypoints.py
python scripts/run_canonical_path_validation.py
python scripts/validate_runtime_profiles.py
```

The first separates fixture-backed results from provider-backed checks that did not execute. The
second produces the claimant/staff visibility matrix. The third produces the per-profile
classification quoted above. Rows sourced from merged work name their issue and pull request so
the evidence can be read at the commit that delivered it.

Update this file when a capability's status changes, and move a row out of `fixture-dependent`
or `partial` only when a recorded run demonstrates the missing condition in a named environment.
