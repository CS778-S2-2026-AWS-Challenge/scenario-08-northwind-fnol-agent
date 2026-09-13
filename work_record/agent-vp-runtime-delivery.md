# Complete Agent VP Runtime Delivery

Status: implementation record for the expanded PR targeting #573, #579, #606,
issues #607, #608, #627, and #628. Issue #733 remains the product-level acceptance
target; this change delivers its Agent Runtime foundation but does not claim that
the ten-scenario, live-provider, claims-adapter, metric, and Control Plane gates are
complete.

## Authority

This record follows `AGENT.md`, the repository governance skill,
`docs/product-soul.md`, `docs/frontend-and-runtime-quality-standard.md`,
`docs/agent-runtime-policy.md`, the Agent Runtime target and migration documents,
`docs/api.md`, `docs/persistence-schema.md`, the applicable `SPEC/` modules, and
`D:/personal/AWSintern/local/Agent能力总设计纲领.md`. It records the maintainer's
approved expansion in Discussion #723. It does not replace those contracts.

## Product result

The Agent must turn a claimant or staff message into a safe, explainable,
revision-checked next action. A fluent answer without an authoritative Claim
mutation, typed execution result, source attribution, and role-safe projection is
not a completed Agent turn.

The delivery is one large vertical implementation. It may change Agent-related
frontend, backend, persistence, retrieval interfaces, Runtime APIs, and
documentation together. It must not introduce an isolated parallel Claim State,
Session model, registry vocabulary, fixture runtime, or fake provider result.

## Runtime contract

Every turn follows:

```text
identity and scope
  -> bounded context
  -> TurnPlan
  -> provider-neutral ModelRequest
  -> AgentProposal
  -> schema/source/authority/revision/visibility validation
  -> ExecutionPlan and ActionEnvelope records
  -> allow-listed Tool or Claim/Staff/Human/External command
  -> typed ToolResult or action result
  -> TurnResult
  -> atomic messages, Claim State, WorkItem, trace, audit and idempotency write
  -> claimant/staff projection
```

The model may interpret, extract, cite, ask, propose, and request a registered
tool. It cannot choose identity, Claim ID, provider, revision, permission, secret,
visibility, authority, or side effect. The Runtime is the only authority that can
execute or persist a business mutation.

The target records are distinct and complete: `TurnPlan`, `AgentProposal`,
`ExecutionPlan`, `ActionEnvelope`, `ToolResult`, `TurnResult`, and `WorkItem`.
`RuntimeTraceRecord` and the deprecated eight-action transport remain compatibility
or diagnostic records; they cannot substitute for these objects.

## Claimant intake

Natural-language turns may contain multiple facts and intents. Runtime processing
must:

- map only to registered fields and content branches;
- preserve reported wording, source message references, precision, confidence,
  relation, and assertion history;
- classify equivalent repetition, refinement, explicit correction, and material
  conflict deterministically;
- retain approximate times and ranges without inventing precision;
- run fact resolution and Branch Evaluator after accepted mutation;
- persist Claim revision, Dynamic Form evaluation, WorkItems, next step, and
  idempotency atomically;
- ask only the smallest question that blocks the current safe action;
- keep internal fraud, branch, and provider reasoning out of claimant output.

The claimant right panel is a server-side claimant-safe projection of facts already
present in Claim State. It must not render empty field-registry entries,
`required_now`, `candidate_now`, `Helpful now`, `Needed now`, `Not provided yet`,
or internal branch reasons as if they were collected data.

## Staff Agent actions

Staff Agent output is always a draft. The transition is:

```text
staff question
  -> authorised context and source-linked draft
  -> explicit staff confirmation
  -> registered ActionEnvelope
  -> permission/revision/idempotency checks
  -> existing real handler
  -> result, audit, source linkage and Workbench projection
```

Drafts cannot silently send claimant messages, mutate Claim fields, change
ownership, resolve signals, or create external effects. Denied, stale, unavailable,
failed, and unknown outcomes are persisted and projected honestly.

## Tools and retrieval

Tools and actions remain separate. `claim.read` is a read Tool, not a Claim Action.
Claim mutations use registered `claim.*` actions. Retrieval tools return typed,
versioned, source-linked evidence only. Policy, history, knowledge, and evidence
results never become authority merely because the model cited them.

Existing real adapters and repository services must be reused. A missing provider
or immature external integration returns a typed unavailable result with retry
class, state effect, safe message, and trace reference. It must not return a fake
success, fixture claim number, or invented third-party response.

## Model and conversation contract

The claimant experience follows ChatGPT-style conversation semantics:

- `qwen-local` is the backend-published default;
- `nowcoding-gpt54mini` remains a backend-published selectable profile;
- the list and availability come from the Control Plane/runtime capabilities API;
- a claimant may switch model within the same conversation without creating a new
  Claim or clearing messages;
- every turn persists the actual model profile used;
- session resume uses the last selected profile as the default, but does not make
  the profile immutable;
- there is no silent provider fallback.

The previous Session-only immutable model binding in the design documents must be
updated with the API, persistence and tests. The browser never receives endpoints,
credentials, or secret references.

New chat follows conversation semantics: reuse an entirely empty draft; otherwise
create a new Claim conversation, preserve the previous conversation in server-backed
history, and restore the selected conversation from its authoritative projection.

## Scope boundaries

Control Plane UI is not part of this VP delivery. Existing published configuration
and Release Set contracts remain the source of Runtime profile truth.

Claim creation, handoff, and third-party capabilities are reused when a complete
real implementation already exists. A missing or partial capability is not invented
to make a scenario look complete; the Runtime exposes its truthful unavailable or
pending boundary and preserves accepted progress.

## Evidence and closure

The implementation must provide contract, persistence readback, Runtime integration,
provider/tool continuation, claimant and staff projection, browser journey, and
failure/recovery evidence. The final evidence covers motor, home, and contents and
the complete #733 scenario and metric requirements. Configuration, registration, a
single model response, a fixture repository, or a visible button is not completion
evidence.

Temporary self-validation fixtures and tests remain local. Committed fixtures are
allowed only where the repository fixture convention gives them a documented,
long-term contract and regression purpose.

## Delivered In This Change Set

The claimant model-gateway path now applies a revision-checked Agent mutation in the
same transaction as the claimant and Agent messages. The transaction writes Claim
form state, contents, Branch Evaluation, Agent Decision, Runtime Trace, idempotency,
Session activity, and the target Runtime record family: TurnPlan, AgentProposal,
ExecutionPlan, ActionEnvelope, ToolResult, TurnResult, and RuntimeWorkItem.

The published capability projection now exposes the backend model catalog. `qwen-local`
is the default when published, while `nowcoding-gpt54mini` remains a separately
selectable profile and unavailable profiles are rejected rather than silently replaced.
Model selection may change inside an existing conversation and the actual profile is
recorded per turn. `New chat` creates a new Claim conversation when the current one
contains work and preserves the previous conversation in server-backed history.

Claimant form projection now contains only facts that have actually been recorded or
reported. Empty Field Registry entries and internal requirement labels are not exposed
as claimant facts. The model selector uses the shared token-based menu rather than a
native select fallback.

Runtime question WorkItems are persisted with each applied claimant turn and reconciled
against the current authoritative Claim State. The staff-only Workbench endpoint projects
one current item per subject and marks it complete when the corresponding fact has been
recorded, without creating a second mutable task state or exposing the internal projection
to claimant routes.

## Evidence Added

- Focused backend runtime, model gateway, Claim API, Mongo persistence, WorkItem, and
  three-family visibility tests pass.
- Claimant component tests, lint, and production build pass for the model menu, recorded-
  fact projection, and new-chat conversation semantics.
- `py -3.12 -m compileall -q backend` and `git diff --check` pass.
- `py -3.12 scripts/export_openapi.py --check` confirms the OpenAPI snapshot matches
  the current API.
- A repository-external controlled browser run verified backend-published Qwen default,
  both projected profiles, pointer and keyboard model selection, registration redirect,
  zero empty-Claim fact cards, upload processing, new-Claim creation with preserved
  history, and no horizontal overflow at 390 px. It also verified that a provider failure
  leaves Claim facts unchanged.

Both locally configured model profiles returned typed `503 DEPENDENCY_UNAVAILABLE` during
the browser run. No successful live Agent trajectory is claimed. The remaining #733 work
includes successful Qwen and GPT provider/tool evidence, the frozen ten-scenario trajectory
and metrics package, claims-adapter outcomes, external-result reconciliation, and the
separately scoped Control Plane acceptance. These are not inferred from configuration,
fixtures, unit tests, or a visible selector.
