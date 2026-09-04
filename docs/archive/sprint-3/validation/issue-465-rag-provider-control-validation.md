# Issue #465: RAG, Provider Isolation, and Control Plane Validation

## Scope

This record validates the Week 5 Day 5 outcome against `main` at
`3285183` (the merge commit for the completed data-query projection). It records
what is currently verified and does not promote an unverified MongoDB, AWS, or
Cloudflare capability.

## Acceptance evidence

### RAG sources and no-result handling

`tests/test_week5_api_rag_provider_control_integration.py` exercises one
composition root containing the API, knowledge retriever, model gateway, and
Control Plane configuration. The test verifies that:

- a matching knowledge query returns `evidence_found` with the expected chunk
  citation;
- the model receives the same cited knowledge context;
- a successful empty lookup is represented as `no_evidence` with no citations;
- a first claimant turn whose `incident_type` is still unknown does not issue a
  product-specific retrieval; and
- an identical message retry replays the first result without a second model
  call.

### Provider isolation and switching boundary

`py -3.12 scripts/validate_runtime_profiles.py` returned
`isolation=verified_fail_closed` on this exact main. The `fixture` profile was
start-capable. The `mongodb`, `aws`, and `cloudflare` profiles refused startup
with their complete missing-capability lists; no fixture adapter or second
provider was assembled as a silent fallback. The local MinIO probe was
unavailable in this run and therefore remains unverified.

The runtime tests also verify that exactly one profile is selected, mixed
provider bundles are rejected, and an injected bundle cannot hide a profile
mismatch. Provider switching therefore remains an explicit deployment/profile
selection, not an implicit fallback during a request.

### Control Plane lifecycle and binding

The integration test verifies a model configuration moving through draft,
validation, independent approval, and publication before a claimant turn uses
it. The published model request is checked for the configured model identifier,
prompt identifier, structured output, and provider-neutral RAG context.

`tests/test_admin_api.py` additionally verifies that incompatible data-profile
and object-storage combinations, unverified external profiles, plaintext
secrets, and model impact downgrades are rejected while the configuration stays
unpublished.

## Commands and results

```powershell
py -3.12 -m pytest tests/test_week5_api_rag_provider_control_integration.py tests/test_runtime_profiles.py tests/test_admin_api.py tests/test_verify_local_rag.py tests/test_verify_minio_rag_provider_failure.py -q
```

Result: `95 passed in 7.74s`.

```powershell
py -3.12 scripts/validate_runtime_profiles.py
```

Result: `isolation=verified_fail_closed`; fixture `verified`, MongoDB
`partial` (connectivity not checked), AWS and Cloudflare `unavailable`, and
local MinIO `unavailable` for this run.

## Limitations

- This is provider-neutral and controlled-fixture evidence; it is not proof of
  a live AWS, Cloudflare, or complete standalone MongoDB deployment.
- Policy and claim-history adapters remain synthetic in `local_mvp`.
- A later run with approved service bindings may update the classifications,
  but must record a new exact commit and the bounded service evidence.
