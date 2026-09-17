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
| Provider-neutral Model Gateway | implemented | `docs/model-gateway.md`, issue #204 and current adapter tests | Per-invocation latency, provider usage, and size-only request composition are observable; streaming, qualified fallback, durable rich usage analytics, and trajectory records remain out of scope. |
| Same-conversation model selection | implemented | message `model_profile_id`, published capabilities, per-turn Runtime provenance, `tests/test_namespaced_runtime.py` | The catalog remains publication/health governed; a profile without a working provider must be exposed as unavailable, never faked. |
| v7 one-call ordinary path | implemented | `backend/services/model_request_planner.py`, `backend/services/model_agent.py`, and `tests/test_agent_context_runtime_v7.py` | Ordinary turns are tool-free and bounded; live P50/P95 remains provider/deployment evidence. |
| Fragmented Prompt Pack and deterministic routing | implemented | `backend/prompts/v7/`, `backend/services/turn_router.py`, `backend/services/prompt_composer.py`, and focused v7 tests | Fixture and contract evidence do not establish production answer quality. |
| Stable Request Profiles, narrow schemas, and provider capabilities | implemented | v7 registries, OpenAI strict-schema, Bedrock forced-output, and Gemini native structured-output/function-continuation tests | Bedrock lookup continuation remains unavailable and fails compatibility before transport; Gemini PDF input remains disabled. |
| Budgeted Context Planner and cache layout | implemented | context/cache planners, persisted v7 trace fields, and focused budget/cache tests | Provider token usage and cache metrics remain unknown when the endpoint does not report them. |
| Verified rolling summary and lazy history | implemented | Fixture/Mongo immutable summary persistence, background compaction, older-message resolver, and focused parity tests | Compaction is post-response and v7-release-gated; wrong-scope, unverified, and Claim-conflicting summaries are omitted. |
| Isolated PDF, multi-Evidence, and cross-Claim review | implemented | isolated executor and v7 focused tests | Each request receives only its task-scoped references and media; results are sourced read-only summaries and cannot mutate Claim State, consent, or external services. |
| Applied Runtime turn persistence | implemented (claimant path) | `RuntimeTraceRecord` plus atomic `TurnPlanRecord`, `AgentProposalRecord`, `ExecutionPlanRecord`, `ActionEnvelopeRecord`, `ToolResultRecord`, `TurnResultRecord`, fixture/Mongo readback and idempotency replay | Workbench exposes reconciled claimant Runtime WorkItems; admin trace projection and external-outcome reconciliation remain open. |
| Deprecated legacy model action rejection | implemented | `backend/services/messages.py`, model gateway contract tests | Existing controlled-agent compatibility routes still expose historical actions; they are not a fallback for the target model path and require later migration/removal. |
| Namespaced Agent Action Registry | implemented | `backend/domain/agent_action_registry.py` and `tests/test_agent_action_registry.py`, issue #365 | The registry defines the target vocabulary and validation boundaries; only actions with an existing real handler are executable in this claimant Runtime. |
| Published Agent turn policy | implemented | `backend/services/runtime_agent_policy.py`, `tests/test_runtime_agent_policy.py`, and `docs/agent-runtime-policy.md` | One Runtime Snapshot governs instructions, tool/action restrictions, controlled branch rules, feature switches, model selection, knowledge selection, and persisted revision provenance. Broader external action policy and evaluation remain separate work. |
| Three-family Dynamic Form and requirements | implemented | `backend/domain/branch_registry.py`, `backend/services/branching.py`, and three-family API/registry tests | Bounded VP field sets and typed contents records are implemented; broader catalogue candidates require separate type, visibility, and record-boundary decisions. |
| Fact resolution and correction history | implemented | `backend/services/fact_resolution.py` and claim/model API regression tests | Form and contents assertions preserve equivalent, refinement, correction, and conflict history. Evidence-to-item association remains separate work. |
| Session question-effort accounting | implemented | `SessionRecord` question fields plus resume, claimant, and Workbench API tests | The nine-question default is a VP policy value; production thresholds require published policy authority. |
| Bounded context lookup and re-plan | implemented | v7 turn-scoped resolver, Policy/RAG, Claim/Evidence/message loaders, and focused gateway regressions | One authorised lookup and one re-plan are enforced; IDs and customer scope are server-owned. Additional action tools remain separate Runtime work. |
| One authoritative Claim State | implemented rule | `SPEC/04-claim-state-and-data.md`, `docs/persistence-schema.md`, issue #237 | Target claimant turn records and question WorkItems are persisted; broader external WorkItem lifecycle remains open. |
| Source-preserving fact resolution | implemented | `backend/services/fact_resolution.py`, message/form mutation paths, and `tests/test_fact_resolution.py`, issue #670 | Runtime preserves assertion history, resolves explicit correction and material conflict, and retrieves full source messages only for unresolved fields. Character spans and staff resolution actions remain future work. |
| Claim-trajectory question accounting | implemented | `SessionRecord`, resume/Workbench projections, and `tests/test_fact_resolution.py`, issue #670 | Nine-question accounting persists across resumed sessions and records repetition; scenario-level response-quality tuning remains separate evaluation work. |
| Discrepancy candidate boundary | implemented | `AgentDecisionRecord.discrepancy_candidates` and `tests/test_fact_resolution.py`, issue #670 | Candidates are internal and do not create fraud-review signals. Calibrated signal creation and precision evaluation remain separate work. |
| Multi-intent `TurnPlan` | implemented (claimant record) | `backend/domain/runtime.py`, message transaction, fixture/Mongo turn readback | Intent classification is bounded to the current VP turn; trajectory evaluation and richer multi-intent scoring remain required. |
| Source-preserving `AgentProposal` | implemented | `docs/model-gateway.md`, assertion records, and model/API tests | The same proposal is persisted in the target Runtime record family; provider and external action limitations remain explicit. |
| Validated `ExecutionPlan` and `ActionEnvelope` | implemented (claimant record) | `backend/domain/runtime.py`, atomic message transaction and repository persistence | Broader external action envelopes and staff/admin projections remain required. |
| `TurnResult` and failure recovery | implemented (claimant record) | `backend/domain/runtime.py`, atomic transaction and idempotency replay | Unknown external-outcome reconciliation remains required for external providers. |
| Independent `WorkItem` lifecycle | implemented (claimant questions and Workbench projection) | `RuntimeWorkItemRecord`, cross-turn reconciliation, and the staff-only Runtime WorkItem route | External owner, service-level, retention, and unknown-outcome WorkItems remain separate work. |
| Bounded staff `@Agent` assistance | implemented (draft execution slice) | Staff-owned sessions, explicit Claim scope, saved drafts, confirmed registered handlers, immutable execution readback, and API/repository tests | Additional external provider actions remain unavailable until their real handlers exist. |
| Claimant/staff context contract | implemented | `docs/agent-context-contract.md`, issue #596, bounded context tests, and persisted claimant TurnPlans | Runtime context remains bounded by the selected profile; broader retrieval and external-action context requires its own registered capability. |
| Six behaviour/action brief | implemented | `docs/agent-behaviour-action-brief.md`, issue #597, and action/authority tests | The brief feeds prompts and validation; additional target action handlers still require their own delivery. |
| Staff session-bound model selection | implemented | `backend/domain/staff_agent.py`, `backend/services/staff_agent.py`, and Staff Agent API tests | Published profile availability and provider connectivity remain deployment concerns. |
| Staff draft-to-action Runtime evidence | implemented | `StaffAgentExecutionRecord`, atomic Fixture/Mongo writes, staff-scoped readback, and Staff Agent/Mongo tests | Only drafts mapped to an existing registered Workbench handler can execute; unavailable external actions remain non-executable. |
| Claimant external-service lifecycle context | implemented | `backend/services/agent_external_lifecycle.py`, bounded Model Gateway context, persisted TurnPlan coordinates, and lifecycle projection tests | Reads and validates claim-scoped tasks/results plus reference-matched assessor routing, including distinct result stage and verification outcome; registry-derived effective guidance reaches the model and the exact operation coordinate reaches TurnPlan. It does not execute external tools or provide Staff Agent context. Real provider actions remain #777 work. |
| Claimant Evidence history Agent boundary | implemented (proposal and persisted execution boundary) | `evidence.history`, proposal and confirmed action contracts, `backend/services/agent_tools.py`, `backend/services/agent_evidence_actions.py`, and focused contract tests | History remains claimant-scoped and read-only. Confirmed Runtime actions validate scope, provenance, confirmation, revision, and idempotency and preserve five typed outcomes. The repository-backed Evidence API now persists reuse links and governed removal with Claim revision, Branch Evaluation, and audit evidence. |

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
