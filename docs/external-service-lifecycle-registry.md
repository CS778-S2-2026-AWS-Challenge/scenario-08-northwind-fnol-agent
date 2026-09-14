# External Service Lifecycle Registry

The canonical registry is implemented in
`backend/domain/external_service_registry.py`. It is versioned as
`external-service-lifecycle.v1` and is the single vocabulary for external request
operation, recovery, and result stages.

`ExternalTaskRecord` remains the persisted record of one operation. Its existing
operation statuses map to the registry's `prepared`, `accepted`,
`retryable_failure`, `terminal_failure`, and `unknown_outcome` entries. The
registry does not add a second persisted state machine.

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

## Registered access forms

| Service identity | Catalogue | Form | Provenance |
| --- | --- | --- | --- |
| `vehicle_damage_assessment_routing` | `P3-ASSESSOR` | Controlled assessor simulation | `simulated` |
| `repairer_information_or_link` | `P3-REPAIRER` | Claimant-provided link or staff-mediated request | `manual` |
| `police_guidance_or_official_link` | `P3-POLICE` | Official link, phone guidance, or staff-mediated path | `manual` |

The machine-readable definitions include claimant, staff, and Agent meanings,
terminality, allowed next transitions, recovery, and Claim State effects. Consumer
surfaces should retrieve these definitions rather than defining local labels or
transitions.
