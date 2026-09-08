# Agent Runtime Migration

## Purpose

This document isolates the compatibility path between the implemented Agent transport and
the target runtime in [Agent Runtime Target](agent-runtime-target.md). It is temporary
migration guidance, not the target product contract.

## Current Compatibility Boundary

`POST /internal/v1/agent/turns` currently returns the eight-value `AgentDecision` shape:

```text
ASK, CLARIFY, CONFIRM, PROCEED, UPDATE,
HANDOFF, URGENT_HANDOFF, CREATE_CLAIM
```

This transport remains valid for current code, fixtures, generated OpenAPI, and contract
tests until the coordinated migration is accepted. It is a deprecated fallback boundary,
not the target Agent action model. New runtime design must not add private variants to this
enum.

The compatibility records may add source-preserving fact assertions, resolution and precision
state, question accounting, and internal discrepancy candidates without creating another action
enum or another Claim truth. These additions remain governed by the current revision-checked
message transaction. They do not satisfy the removal gate for target `TurnPlan`,
`ExecutionPlan`, `ActionEnvelope`, or `TurnResult` records.

## Target Mapping

| Compatibility value | Target direction | Migration note |
| --- | --- | --- |
| `ASK` | `conversation.ask` plus `runtime.wait_for_user` | The question is a communication move, not a Claim mutation. |
| `CLARIFY` | `conversation.clarify` plus `runtime.wait_for_user` | Any resulting fact proposal is derived and validated separately from the communication action. |
| `CONFIRM` | `conversation.confirm_material` plus `runtime.wait_for_user` | A resulting `claim.apply_fact_patch` is a separate revision-checked action, not an effect of the compatibility label itself. |
| `UPDATE` | `conversation.answer`, `conversation.explain`, or `conversation.summarise`, plus `runtime.continue` or `runtime.wait_for_user` | Status communication has no inherent Claim mutation; any real mutation is represented and authorised separately. |
| `PROCEED` | `runtime.continue` | Claim or external actions are derived from their validated underlying proposals, not from the control label. |
| `HANDOFF` | `human.create_handoff` plus `runtime.pause_for_review` | Handoff context and claimant projection remain separate. |
| `URGENT_HANDOFF` | `human.create_handoff` plus `runtime.interrupt_urgent` | Urgent handling interrupts ordinary intake without adding diagnosis or emergency authority. |
| `CREATE_CLAIM` | `claim.prepare_creation`, then `claim.create`, plus `runtime.continue` or `runtime.wait_for_external` | External creation remains revision-checked, idempotent, authorised, and provider-neutral. |

The mapping is a compatibility aid. It must not be used to claim that the target schemas
or namespaced actions are already implemented. The mapping preserves semantic dimensions:
conversation labels do not create business side effects, runtime labels do not grant tool
authority, and material actions remain separate validated proposals.

The mapping structure and namespace boundaries are checked by:

```powershell
py -3.12 scripts/check_agent_runtime_mapping.py
```

## Removal Gate

The fallback may be removed only after one coordinated change set has:

1. versioned target request, response, action, result, and error schemas;
2. persistence records and repository methods for target turns, actions, results, and
   WorkItems;
3. claimant and Workbench consumers using the target projections;
4. generated OpenAPI and API contract tests updated;
5. fixtures covering success, rejection, failure, visibility, idempotency, and resume;
6. trajectory evidence for MVP capabilities and a documented rollout/rollback plan; and
7. an explicit removal decision recorded against the owning migration issue.

Until all gates pass, the current API documentation and tests must continue to describe
the compatibility transport as valid. Once the target runtime is accepted, remove the
fallback from code, API documentation, fixtures, and tests together; do not leave a
permanent legacy vocabulary in the target contract.

## Authority Invariants During Migration

- Claim State remains the only authoritative claim truth in both layers.
- The compatibility adapter may translate a target proposal at the boundary, but it may
  not bypass deterministic validation, staff authority, revision checks, visibility, or
  idempotency.
- A failed target or compatibility operation preserves accepted Claim progress.
- Target documentation may lead implementation; current API documentation must describe
  only what the running transport supports.
