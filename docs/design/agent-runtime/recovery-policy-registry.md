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
replays the original result; an explicit retry uses the existing
`submit_message` entrypoint with a new attempt identity and reloads authoritative
records. No retry endpoint or second lifecycle is introduced.

Unknown recovery triggers fail closed. The complete external reconciliation,
tool-unavailable, revision-conflict and high-impact review matrix remains
tracked by issue #779.
