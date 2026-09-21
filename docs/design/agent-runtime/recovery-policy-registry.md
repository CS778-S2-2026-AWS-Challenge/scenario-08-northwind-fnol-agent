# Recovery Policy Registry

The claimant Runtime uses the typed registry in
`backend/domain/recovery_policy_registry.py` to map provider-neutral failures
to preservation, responsibility, claimant projection, resume entrypoint and
audit behavior. The registry is a policy mapping layer; Claim State, Session,
ExternalTask, WorkItem, handoff and audit records remain the authorities for
their own data.

The first published rule is `claimant_turn.model_dependency_failure`.
Before a model-dependent turn is attempted, an accepted inbound message and
checkpoint must be preserved. A provider failure cannot create a fact, an
external request or a success response. The original HTTP idempotency key
replays the historical result, refreshing only `current_claim` and `current_claim_revision`
from the authoritative Claim without invoking the model, reducer or dispatcher. An explicit retry uses the existing
`submit_message` entrypoint with a new attempt identity and reloads authoritative
records. No retry endpoint or second lifecycle is introduced.

If Runtime detects a safety or human-support interrupt, the shared handoff mutation must
also commit before the provider call. Its failure is a hard request failure, not a recovery
success. If the provider then fails, the recovery response includes a deterministic Agent
notice with safety guidance and confirmation that support has been notified. The notice
carries recovery metadata and does not hide explicit Retry. It neither applies failed
model facts nor switches the turn to ControlledAgent.

Unknown recovery triggers fail closed. The complete external reconciliation,
tool-unavailable, revision-conflict and high-impact review matrix remains
tracked by issue #779.

## Remaining #779 policy evidence

The following distinguishes this delivered slice from the broader issue. Existing subsystem
behavior does not mean that its corresponding registry migration or end-to-end proof is done.

| Requested #779 entry | Status of this delivery |
| --- | --- |
| `recovery.model_timeout` | Covered by the shared claimant model-dependency rule, including persist-first and explicit retry. |
| `recovery.model_malformed_response` | Covered by that same rule; no duplicate registry lifecycle is introduced. |
| `recovery.tool_unavailable` | Existing tool failure behavior retained; full policy migration/evidence remains #779 work. |
| `recovery.external_not_submitted_retryable` | Existing external retry authority retained; not implemented as a new recovery rule here. |
| `recovery.external_submitted_unknown` | Existing operation identity/reconciliation retained; complete registry migration remains open. |
| `recovery.external_terminal_failure` | Existing staff resolution remains authoritative; broader policy evidence remains open. |
| `recovery.revision_conflict` | CAS/stale-checkpoint protections are exercised here; a general conflict-recovery policy is not delivered. |
| `recovery.high_impact_review_required` | Existing human-review authority retained; broader controlled resume matrix remains open. |

This PR references #779 and must not close it. The supplied claimant rule and its concrete
tests do not establish the remaining tool, external or high-impact recovery loops.

Claim creation also fails closed when branch evaluation still contains recorded
facts: the API returns `CONFIRMATION_REQUIRED` and lists the fields that must be
confirmed before the creation command can be prepared. This is a Claim creation
boundary response, not a provider failure and not an implicit retry.
