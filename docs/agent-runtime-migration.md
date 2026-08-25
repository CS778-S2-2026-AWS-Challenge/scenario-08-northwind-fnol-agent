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

## Target Mapping

| Compatibility value | Target direction | Migration note |
| --- | --- | --- |
| `ASK` | `conversation.ask` plus a runtime wait directive | The question is a communication move, not a claim mutation. |
| `CLARIFY` | `conversation.clarify` plus proposed fact context | Confirmation and source rules remain server-controlled. |
| `CONFIRM` | `conversation.confirm` and a validated Claim command where applicable | Confirmation changes Claim State only through the revision boundary. |
| `UPDATE` | `claim.propose_update` | A proposal is not a confirmed fact. |
| `PROCEED` | `runtime.continue` with validated Claim or external actions | Safe continuation depends on current WorkItems and authority. |
| `HANDOFF` | `human.request_handoff` | Handoff context and claimant projection remain separate. |
| `URGENT_HANDOFF` | `human.urgent_handoff` plus `runtime.interrupt` | Urgent handling interrupts ordinary intake. |
| `CREATE_CLAIM` | `claim.create` after explicit authority and validated prerequisites | External creation remains idempotent and provider-neutral. |

The mapping is a compatibility aid. It must not be used to claim that the target schemas
or namespaced actions are already implemented.

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
