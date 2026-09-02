# Approved Agent action to Claim Context command boundary

This note defines the bounded backend execution hand-off introduced for Sprint 3 Week 5 issue #366. The namespaced Agent Action Registry remains the authority for what actions exist and what each action requires. The backend command boundary does not choose Agent behaviour.

## Responsibility split

- Agent/runtime proposal logic decides which registered action to propose.
- The approved action must carry a proposer role, the authority requirement that was satisfied, and a source-preserving authority reference.
- `build_claim_context_command` validates the published action input schema, proposer role, authority requirement, lifecycle state, revision metadata, and idempotency metadata.
- The resulting command keeps a recursively immutable snapshot of the validated mapping and sequence payload so later caller mutation cannot change approved execution intent.
- A service handler may execute only the tools allow-listed on the resulting command and must continue to use the existing repository compare-and-set/idempotency transaction boundaries.
- Conversation-only, runtime-control, and external-service actions do not become Claim Context commands through this boundary. Their owners retain their existing runtime or adapter execution paths.

## Revision and retry rules

Claim mutations and handoffs require an `expected_revision` before execution, except `claim.open_draft`, which creates a new context and therefore has no prior claim revision. If a registered action already includes `expected_revision`, execution metadata must match it exactly.

Every action whose registry contract requires idempotency must carry a stable `idempotency_key`. If the registered payload already includes the key, execution metadata must match it exactly. The command preserves the registry `idempotency_policy` and `failure_policy`; handlers must not turn an unknown outcome into a second write without the reconciliation required by that policy.

A mismatch is rejected before side effects. Existing Claim Context state remains authoritative after a rejected translation, revision conflict, timeout, or unknown outcome until the relevant handler has safely reconciled the operation.

## Provider boundary

The command exposes only tools that are already allow-listed by the approved action contract. It does not create or advertise a live provider integration. In particular, a command for `claim.create` records the approved execution intent and existing `claims_service.create_claim` tool boundary; it does not claim that any new insurer, cloud, or third-party provider is configured or production-ready.

## Review evidence

`tests/test_agent_action_commands.py` covers:

- valid revision-safe and idempotent Claim Context commands;
- immutable command payload snapshots after caller-owned nested input changes;
- new-draft creation without an invented prior revision;
- rejection of unknown and non-Claim-Context actions;
- independent enforcement of proposer role and execution authority;
- closed input schemas and input types;
- required revision/idempotency execution metadata;
- preservation of the registered handoff visibility contract; and
- fail-closed handling when approved payload metadata disagrees with execution metadata.
