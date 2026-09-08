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
| Namespaced Agent Action Registry | implemented | `backend/domain/agent_action_registry.py` and `tests/test_agent_action_registry.py`, issue #365 | The registry defines the target vocabulary and validation boundaries; Runtime execution, target turn persistence, and transport migration remain separate work. |
| Published Agent turn policy | implemented | `backend/services/runtime_agent_policy.py`, `tests/test_runtime_agent_policy.py`, and `docs/agent-runtime-policy.md` | One Runtime Snapshot governs instructions, tool/action restrictions, controlled branch rules, feature switches, model selection, knowledge selection, and persisted revision provenance. Complete target execution records and policy evaluation remain separate work. |
| Three-family Dynamic Form and requirements | implemented | `backend/domain/branch_registry.py`, `backend/services/branching.py`, and three-family API/registry tests | Bounded VP field sets and typed contents records are implemented; broader catalogue candidates require separate type, visibility, and record-boundary decisions. |
| Fact resolution and correction history | implemented | `backend/services/fact_resolution.py` and claim/model API regression tests | Form and contents assertions preserve equivalent, refinement, correction, and conflict history. Evidence-to-item association remains separate work. |
| Session question-effort accounting | implemented | `SessionRecord` question fields plus resume, claimant, and Workbench API tests | The nine-question default is a VP policy value; production thresholds require published policy authority. |
| Bounded context lookup and re-plan | implemented | `KnowledgeGroundedAgent`, Message service tool orchestration, and model-gateway regressions | One knowledge, policy, or claim-history lookup and one re-plan are enforced. Additional action tools remain target work. |
| One authoritative Claim State | implemented rule | `SPEC/04-claim-state-and-data.md`, `docs/persistence-schema.md`, issue #237 | Target turn records and complete WorkItem persistence still require coordinated migration. |
| Source-preserving fact resolution | implemented | `backend/services/fact_resolution.py`, message/form mutation paths, and `tests/test_fact_resolution.py`, issue #670 | Runtime preserves assertion history, resolves explicit correction and material conflict, and retrieves full source messages only for unresolved fields. Character spans and staff resolution actions remain future work. |
| Claim-trajectory question accounting | implemented | `SessionRecord`, resume/Workbench projections, and `tests/test_fact_resolution.py`, issue #670 | Nine-question accounting persists across resumed sessions and records repetition; scenario-level response-quality tuning remains separate evaluation work. |
| Discrepancy candidate boundary | implemented | `AgentDecisionRecord.discrepancy_candidates` and `tests/test_fact_resolution.py`, issue #670 | Candidates are internal and do not create fraud-review signals. Calibrated signal creation and precision evaluation remain separate work. |
| Multi-intent `TurnPlan` | specified | `docs/design/agent-runtime/agent-runtime-target.md` | Needs target schema, trajectory fixture, and repeatable non-repetition measurement. |
| Source-preserving `AgentProposal` | implemented compatibility boundary | `docs/model-gateway.md`, assertion records, and model/API tests | The compatibility proposal preserves claimant wording, source-linked retrieval context, precision, correction, and conflicts; target namespaced proposal persistence remains incomplete. |
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
