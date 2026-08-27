# Agent Runtime Progress

## Purpose and Status

This is the current evidence ledger for the Agent Runtime target. It records what has been
specified, implemented, configured, degraded, or unavailable. It does not redefine product
requirements or API schemas. Update a row only with repeatable evidence from the exact
commit under review.

## Evidence Rules

- `specified`: target contract exists, but no implementation proof is claimed.
- `implemented`: code and contract tests exist for the stated boundary.
- `fixture`: deterministic or synthetic path is repeatable; it is not a provider claim.
- `configured`: an adapter is composed, without claiming remote connectivity or quality.
- `degraded`: the path works with an explicit limitation or unavailable dependency.
- `unavailable`: the required dependency or capability is not wired.
- `production-integrated`: use only after the provider, permissions, data, and deployment
  evidence are independently verified.

## Current Ledger

| Capability | Status | Evidence entry | Remaining proof or limitation |
| --- | --- | --- | --- |
| Compatibility `AgentDecision` transport | implemented | `docs/api.md` and current API/contract tests | Deprecated fallback until the migration removal gate passes. |
| Provider-neutral Model Gateway | implemented | `docs/model-gateway.md`, issue #204 and its merged implementation | Streaming, qualified fallback, usage persistence, and trajectory records remain out of scope. |
| One authoritative Claim State | implemented rule | `SPEC/04-claim-state-and-data.md`, `docs/persistence-schema.md`, issue #237 | Target turn records and complete WorkItem persistence still require coordinated migration. |
| Multi-intent `TurnPlan` | specified | `docs/design/agent-runtime/agent-runtime-target.md` | Needs target schema, trajectory fixture, and repeatable non-repetition measurement. |
| Source-preserving `AgentProposal` | specified/partial gateway support | `docs/model-gateway.md` and target contract | Target proposal schema, provenance coverage, and consumer migration are incomplete. |
| Validated `ExecutionPlan` and `ActionEnvelope` | specified | `docs/design/agent-runtime/agent-runtime-target.md` and `docs/agent-runtime-policy.md` | Tool Registry, execution records, idempotency, and contract tests are not complete. |
| `TurnResult` and failure recovery | specified/partial error boundary | `docs/api.md` and `docs/model-gateway.md` | Complete target result persistence and unknown external-outcome reconciliation remain. |
| Independent `WorkItem` lifecycle | specified | `SPEC/04-claim-state-and-data.md` and `docs/persistence-schema.md` | Current persistence must migrate before this is claimed as an implemented runtime record. |
| Bounded staff `@Agent` assistance | specified | `SPEC/05-workbench-and-handoff.md`, issues #259 and #269 | Connected suggestion, accept/ignore, and claimant-send proof remains required. |

## Required Evidence Entry

For every promoted capability, add:

```text
Capability:
Status:
Issue and PR:
Exact commit:
Contract or source:
Acceptance scenario:
Failure case:
Authority and visibility check:
Command and result:
Known limitation:
```

Do not copy evidence from an earlier branch or commit. A successful model response or build
does not prove a complete claimant or staff trajectory.
