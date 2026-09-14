# External Service Lifecycle Registry

The canonical registry is implemented in
`backend/domain/external_service_registry.py`. It is versioned as
`external-service-lifecycle.v1` and is the single vocabulary for external request
operation, recovery, and result stages.

`ExternalTaskRecord` remains the persisted record of one operation. Its existing
operation statuses map to the registry's `prepared`, `accepted`,
`retryable_failure`, `terminal_failure`, and `unknown_outcome` entries. The
registry does not add a second persisted state machine.

The shared projection keeps three coordinates distinct:

- `operation_status` describes request delivery and recovery;
- `result_status` describes receipt or verification of a provider result; and
- `result_verification` preserves the persisted `unverified`, `consistent`,
  `inconsistent`, or `review_required` outcome.

For the task/result-backed builder, only `accepted` and `unknown_outcome` may
coexist with `result_received` or `result_verified`. `result_received` requires
`unverified`; `result_verified` requires one of the three checked outcomes.
`written_back` cannot be inferred from a task and result alone because it also
requires an authorised Claim/Evidence write-back record.

## Safety rules

- `unknown_outcome` requires reconciliation by operation identity or provider
  reference before another side effect; it is not an ordinary retry.
- `accepted` and `assigned` mean acknowledgement or allocation only. Neither
  means the service completed or verified a result.
- Result receipt, result verification, and Claim/Evidence write-back are
  separate registry stages and require the existing revision and provenance
  rules.
- Manual, unavailable, and simulation-only access forms never describe a live
  provider success.
- `submitting` is an observable transient status. It is declared separately
  from persisted/projectable task statuses and never appears in an
  `ExternalTaskRecord` projection.

## State and transition requirements

Each lifecycle definition separates `state_invariants`, which must already be
true for the current state, from `transition_preconditions`, which must be
satisfied to leave it. In particular, a prepared `ExternalTaskRequest` has its
request identity, authorisation, disclosed fields, and `prepared_at`, but no
`operation_id` or `dispatch_reserved_at`. Those two fields arise when dispatch
is reserved, at the prepared-to-submitting boundary; the API `idempotency_key`
is also required for that side-effecting transition.

## Registered access forms

| Service identity | Catalogue | Form | Provenance |
| --- | --- | --- | --- |
| `vehicle_damage_assessment_routing` | `P3-ASSESSOR` | Controlled assessor simulation | `simulated` |
| `repairer_information_or_link` | `P3-REPAIRER` | Claimant-provided link or staff-mediated request | `manual` |
| `police_105_reporting_guidance` | `P3-NZP-REPORT` | Official 105 link or phone guidance | `manual` |
| `police_traffic_crash_report_guidance` | `P3-NZP-TCR` | Official TCR request guidance or staff-mediated path | `manual` |

The machine-readable definitions include claimant, staff, and Agent meanings,
terminality, allowed next transitions, state invariants, transition
preconditions, recovery, and Claim State effects. Consumer surfaces should
retrieve these definitions rather than defining local labels or transitions.
This PR exposes the registry to backend consumers; browser-facing consumers
must use a later API projection and must not import Python modules directly.
Manual entries explicitly set `uses_external_task=false` and therefore do not
create a synthetic task or enter the consent-gated Northwind-send lifecycle.
