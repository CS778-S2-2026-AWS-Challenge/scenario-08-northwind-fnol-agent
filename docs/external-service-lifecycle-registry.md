# External Service Lifecycle Registry

The canonical registry is implemented in
`backend/domain/external_service_registry.py`. It is versioned as
`external-service-lifecycle.v1` and is the single vocabulary for external request
operation, recovery, and result stages.

`ExternalTaskRecord` remains the persisted record of one operation. Its existing
operation statuses map to the registry's `prepared`, `accepted`,
`retryable_failure`, `terminal_failure`, and `unknown_outcome` entries. The
registry does not add a second persisted state machine.

The assessor's `queued` and `assigned` progress is stored separately in the
authoritative `WorkingClaim.assessor_routing` result. A consumer may project that
progress only through the registry join: the external task must be `accepted`, the
service identity must be `vehicle_damage_assessment_routing`, and the task's
`provider_reference` must match the routing result's assessor or queue reference.
Without that match, the task remains `accepted`; a consumer must not infer routing
progress from the service name or Claim route.

The shared projection keeps three coordinates distinct:

- `operation_status` describes request delivery and recovery;
- `result_status` describes receipt or verification of a provider result; and
- `result_verification` preserves the persisted `unverified`, `consistent`,
  `inconsistent`, or `review_required` outcome.

The registry also derives the effective status label, detail, verification state,
pending owner, next action, and attention requirement. A received or checked result
replaces acknowledgement-only guidance because staff now own verification or an
authorised Claim decision. `unknown_outcome` is the exception: a late result remains
visible as a separate coordinate, but reconciliation guidance stays effective until
the operation identity is reconciled.

For the task/result-backed builder, `accepted`, a reference-matched `queued` or
`assigned` projection, and `unknown_outcome` may coexist with `result_received`
or `result_verified`. `result_received` requires `unverified`; `result_verified`
requires one of the three checked outcomes. `written_back` cannot be inferred
from a task and result alone because it also requires an authorised
Claim/Evidence write-back record.

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
- Capability provenance and actual request provenance are checked separately. A
  registered simulation-only capability cannot project a configured or live
  request. Workbench returns an explicit unavailable resource when stored records
  contradict this boundary; it does not guess, expose the inconsistent row, or turn
  the whole request into a generic server error.
- New `ExternalTaskRecord` writes must name a registered capability that permits
  tasks, use one of that capability's persisted statuses, and agree with its
  provenance. Historical unknown or contradictory records remain readable only as
  explicit legacy or unavailable projections.
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
Claimant and Workbench API projections expose the registry version, canonical
lifecycle status, catalogue reference, capability provenance, access form,
limitation, effective label, pending owner, and next action. Browser consumers
use those fields and must not import Python modules or recreate the mappings.
Manual entries explicitly set `uses_external_task=false` and therefore do not
create a synthetic task or enter the consent-gated Northwind-send lifecycle.
