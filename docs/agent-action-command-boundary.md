# Approved Agent action to Claim Context command boundary

This note defines the bounded backend execution hand-off introduced for Sprint 3 Week 5 issues #366 and #406. The namespaced Agent Action Registry remains the authority for what actions exist and what each action requires. The backend command boundary does not choose Agent behaviour.

## Responsibility split

- Agent/runtime proposal logic decides which registered action to propose.
- The approved action must carry a proposer role, the authority requirement that was satisfied, and a source-preserving authority reference.
- `build_claim_context_command` validates the published action input schema, proposer role, authority requirement, lifecycle state, revision metadata, and idempotency metadata.
- The resulting command keeps a recursively immutable snapshot of the validated mapping and sequence payload so later caller mutation cannot change approved execution intent.
- `execute_claim_context_command` re-resolves the authoritative Claim immediately before execution and rejects a command whose workflow state or expected revision is stale.
- Execution uses an explicit action-to-handler binding. The bound internal tool must be present in the command's registry-derived `permitted_tools`; a mismatched or unsupported handler is rejected before execution.
- Action-specific handlers continue to own their existing compare-and-set/idempotency transaction boundaries. The execution gate does not duplicate Claim, handoff, evidence, staff, or external-service persistence logic.
- After a handler reports success, the execution gate re-reads authoritative Claim State and verifies that the reported revision was actually persisted. A Claim mutation or handoff must advance the Claim revision; a non-mutating Claim proposal must not advance it unexpectedly.
- Conversation-only, runtime-control, and external-service actions do not become Claim Context commands through this boundary. Their owners retain their existing runtime or adapter execution paths.

## Execution result and failure handling

The internal `ClaimContextExecutionResult` is deliberately smaller than the target Agent Runtime `TurnResult`. It records the action code, `applied` / `rejected` / `failed` status, Claim identity when applicable, resulting authoritative revision when known, a bounded reason code, retryability, and the registry failure policy for non-applied outcomes.

The execution gate rejects stale workflow state, stale revision, unsupported actions, tool allow-list mismatches, missing Claim scope, repository conflicts, and invalid handler outcomes without presenting them as completed work. Expected dependency or service failures become bounded `failed` results rather than provider-specific exceptions. Unexpected programming errors are not swallowed by this boundary.

This issue does **not** introduce the coordinated target `ExecutionPlan` / `TurnResult` persistence or public transport migration. It also does not publish a new API route or compose every namespaced action into one runtime entry point. Day 4 integration work may consume this internal boundary while the existing action-specific services remain authoritative for concrete writes.

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

`tests/test_agent_action_execution.py` covers:

- a valid allow-listed handler persisting exactly one authoritative revision transition;
- stale revision and stale workflow-state rejection before handler execution;
- handler/tool allow-list enforcement;
- bounded repository revision-conflict handling;
- bounded dependency failure without false completion;
- rejection of a handler that reports success without the matching persisted revision; and
- fail-closed handling for an unsupported action.
