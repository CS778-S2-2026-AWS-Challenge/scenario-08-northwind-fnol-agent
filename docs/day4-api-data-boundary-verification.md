# Day 4 API, Data Boundary, and Adapter Verification

## Scope

This record documents `liyang6620`'s independent verification for D4-T07
(#46) on 14 August 2026. The tests ran against merged `main` commit
`c987be410aa2f5223b82a377f44caeaf4249fe55`. All records, credentials, provider
responses, and storage references used by the checks are synthetic.

The verification covers the assigned data and adapter ownership:

- claimant, staff, and integration-service access boundaries;
- exclusion of internal signals, workbench fields, evidence provenance, and
  logical storage details from claimant responses;
- traceability of material state changes through revision, actor, decision,
  idempotency, and audit records; and
- compatibility of fixture repositories and replaceable adapters with the
  same provider-neutral domain models.

It complements the route, validation, error, and permission evidence already
recorded by `jxu316-arch` on #46.

## Command and result

The following focused suite was run from the repository root with Python 3.12:

```powershell
python -m pytest `
  tests/test_api_boundaries.py `
  tests/test_api_fixture_examples.py `
  tests/test_config.py `
  tests/test_errors.py `
  tests/test_integrations.py `
  tests/test_repository.py `
  tests/test_day3_scenarios.py::test_fixture_public_api_never_exposes_logical_storage_keys `
  tests/test_day3_scenarios.py::test_claimant_and_staff_projections_share_state_without_leaking_internal_signal `
  tests/test_workbench_api.py::test_workbench_claim_list_rejects_claimant_credentials `
  tests/test_workbench_api.py::test_workbench_rejects_claimant_and_invalid_credentials `
  tests/test_workbench_api.py::test_claimant_projections_do_not_expose_workbench_only_data `
  -vv
```

Result: **42 passed**. No #46-scoped defect was found.

## Verification findings

### 1. Claimant APIs exclude internal signals and storage details

- Claimant projections omit `fraud_signal`, signal decisions, internal-only
  messages, workbench state, evidence provenance, and staff-only records.
- Public fixture responses exclude logical DynamoDB keys and provider/storage
  names, including nested fields.
- Validation rejects attempted internal or storage fields without echoing
  their submitted values into an error response.
- Staff projections can read the authorised internal context required for
  review without changing the claimant boundary.

### 2. Material changes remain traceable

- Claim, message, evidence, Agent-turn, integration, and staff mutations use
  revision checks and idempotency records.
- A validated Agent turn is persisted as one consistent unit containing the
  claimant message, Agent response, decision, resulting claim revision, and
  optional handoff or evidence record.
- Claim creation and assessor routing require an explicit authorised decision;
  severity alone cannot authorise assessor routing.
- Replays return the recorded result, while changed payloads using the same
  provider or idempotency reference are rejected instead of overwriting state.

### 3. Fixtures and replaceable adapters share the domain boundary

- `PersistenceRepository` defines provider-neutral claim, session, message,
  evidence, decision, handoff, staff-action, customer-update, and signal
  operations.
- The in-memory fixture repository implements ownership, revision,
  idempotency, and logical access patterns without placing provider keys in
  public API models.
- Claims, assessor, and evidence mocks implement typed adapter protocols using
  domain request and result models.
- A replaceable claims adapter can be supplied without changing the public API
  response schema, and provider-specific request fields are rejected.

## Acceptance mapping

| #46 acceptance criterion | Evidence |
|---|---|
| Claimant APIs exclude internal signals. | Projection, fixture-leakage, workbench-auth, and validation tests passed. |
| Material changes remain traceable. | Revision, atomic Agent-turn, explicit-authority, idempotency, replay, and conflict tests passed. |
| Fixtures and AWS adapters implement the same domain boundary. | Fixture repository and replaceable mock-adapter tests use the same provider-neutral protocols and domain models. |

## Boundary

This verifies the Sprint 1 provider-neutral boundary and its current fixture
and mock implementations. It does not claim that a physical AWS account,
DynamoDB table, S3 bucket, IAM policy, insurer integration, production token,
region, throughput target, or production retention policy has been configured
or validated. Those implementation details remain intentionally outside the
current evidence.
