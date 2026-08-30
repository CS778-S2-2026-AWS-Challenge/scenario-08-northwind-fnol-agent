# Agent Runtime Policy

## Status and Authority

This document defines the provider-neutral runtime policy that constrains how the
Northwind FNOL Agent interprets context, chooses an action, uses tools, communicates
with a claimant, and requests human authority.

It implements the product intent in [Agent Behaviour](../SPEC/03-agent-behaviour.md) and
the authority boundary in
[Safety and Governance](../SPEC/06-safety-and-governance.md). It does not redefine the
API contract, approve Northwind business rules, or replace insurance policy wording. In
this document, **Agent Policy** means rules for Agent behaviour; **insurance policy**
means contractual coverage evidence.

The predefined information areas, dynamic form, and branch-selection boundary are
defined in the [FNOL Information Model and Field Taxonomy](fnol-field-model.md).
The target object catalogue, FNOL problem mapping, and delivery levels are recorded in
[Agent Runtime Target](design/agent-runtime/agent-runtime-target.md). The compatibility path is
recorded in [Agent Runtime Migration](design/agent-runtime/agent-runtime-migration.md). Current
implementation evidence is tracked in [Agent Runtime Progress](status/agent-runtime-progress.md).

The current repository has a legacy static eight-action registry and deterministic
proposal validation. The target contract in
[Agent Runtime Target](design/agent-runtime/agent-runtime-target.md)
replaces that flat enum with multidimensional turn plans and namespaced actions, but the
compatibility migration is not yet implemented. A first provider-neutral Model Gateway is implemented with a
minimal `ModelRequest` and `ModelResponse`, an OpenAI-compatible adapter, structured
proposal validation, bounded context projection, server-rendered claimant responses, and
normalised failure mapping. It does not yet implement the complete Instruction Compiler,
Model Profile Registry, namespaced action schemas, tool execution, qualified fallback,
usage persistence, or trajectory records defined here. The repository also does not yet
have a dynamically loaded policy bundle, Control Plane publication flow, or persisted
runtime policy version. Those capabilities must not be claimed until their
implementation, API, storage, audit, and tests change together.
The current field registry contains 18 allowed field codes, while controlled intake
actively sequences only incident description, incident location, loss description, and
incident type. It does not yet implement policy-driven dynamic branches.

## Policy Is Not a Prompt

A system prompt is one model-specific rendering of part of the Agent Policy. It is not
the authoritative policy and cannot grant itself more authority.

```text
Product requirements and approved operating rules
-> versioned Agent Runtime Policy
-> model instructions, tool manifest, and context limits
-> model or controlled logic produces an AgentProposal
-> deterministic schema, Registry, authority, state, visibility, and idempotency checks
-> validated ExecutionPlan
-> tools and state changes produce a TurnResult
-> persist proposals, decisions, actual outcomes, and the role-safe response
```

Changing the model provider, compatible API, relay, custom endpoint, or local model must
not change this sequence or the namespaced Agent action semantics.

## Policy Layers

| Layer | Examples | Primary enforcement | Change authority |
| --- | --- | --- | --- |
| Non-overridable safety and access | claimant data isolation, internal-signal filtering, prohibited high-impact decisions, tool allow-list | server code, schemas, projections, and authority checks | reviewed code and security controls |
| Controlled business rules | urgent triggers, branch activation, current-action field requirements, first human-request behaviour, claim-creation criteria, routing thresholds | versioned deterministic rules plus staff authority where required | approved Northwind role |
| Interaction policy | focused questions, material confirmation, plain language, acknowledgement, non-repetition | Agent instructions, state-aware orchestration, response validation, and evaluation | approved Agent Policy publisher |
| Model and tool configuration | provider adapter, model identifier, structured-output capability, enabled tools, token budget | provider-neutral gateway and configuration validation | approved technical or operational role |
| Claim context | current facts, unresolved questions, recent messages, cited evidence, prior commitments | claim-scoped context builder and access control | derived from authorised claim state; not a policy change |

No lower layer may weaken a higher layer. A prompt, model response, retrieved document,
tool result, or claim-specific preference cannot override safety, access, or decision
authority.

## Policy Bundle

A future machine-readable policy bundle must identify at least:

- `policy_id`, semantic version, lifecycle status, and effective time;
- author, change reason, approver when required, and previous version;
- supported TurnPlan, AgentProposal, action-envelope, tool, and model-request contract
  versions;
- compatible Field, Content Branch, Lifecycle, Action, Tool, Staff Capability, Model
  Profile, and Error Registry versions;
- interaction, confirmation, handoff, tool, context, response, and failure rules;
- controlled business-rule references rather than copied private provider logic;
- enabled tool references and permitted purposes, never plaintext secrets;
- required evaluation scenarios, acceptance thresholds, and validation result; and
- rollback target and immutable publication record.

Individual rules need a stable rule ID, scope, condition, required or prohibited effect,
enforcement class, claimant-response requirement, evidence source, and lifecycle state.
Published policy versions are immutable. Editing a published version creates a new draft.

This section defines the required contract for future implementation. It does not claim
that these records are currently exposed by an Admin API or persisted by the prototype.

## Turn Policy

For each Agent turn, orchestration must:

1. authenticate the caller and verify claim ownership or role;
2. load the active, valid policy version for the runtime environment;
3. run deterministic interruption checks for explicit injury, continuing danger,
   repeated human requests, accessibility needs, and explicit UI controls before a model
   sees private context;
4. assemble only the authorised, bounded Claim State, content branches, lifecycle,
   WorkItems, messages, sources, and prior commitments needed for the current purpose;
5. evaluate approved content-branch rules and identify active, required-now, candidate,
   pending, inactive, and system-owned fields;
6. calculate the actions, staff capabilities, and tools permitted for the role, purpose,
   Claim scope, and current state;
7. perform a deterministic read-only lookup first when it can satisfy the purpose,
   otherwise obtain a schema-valid `AgentProposal` through Model Gateway;
8. validate the proposal against Registry versions, provenance, state, permissions,
   visibility, confirmation, idempotency, and side-effect rules outside the model;
9. produce an `ExecutionPlan` that records approved and rejected action envelopes,
   ordering, preconditions, required authority, and cancellation or reconciliation needs;
10. execute only authorised effects and update Claim State, WorkItems, and lifecycle from
    real tool results;
11. produce `TurnResult`, then correct the response draft so proposed, requested, queued,
    or unknown work is not described as completed; and
12. persist the policy and Registry versions, proposals, authority results, actual state
    effects, source references, limitations, usage, latency, and role-safe response.

The current implementation performs only part of this sequence. Until policy loading is
implemented, static action definitions and deterministic validation remain the enforceable
runtime boundary.

## Interaction Rules

### Natural intake

- Accept incomplete, informal, emotional, and non-linear descriptions.
- Acknowledge the claimant's situation before asking for more information.
- Convert the account into internal structure without making the claimant learn the
  insurer's form or workflow.
- Record a clear claimant statement as claimant-supplied without mechanically asking for
  it again. Never silently change meaning, fill an unknown fact as known, or present a
  model interpretation as claimant-confirmed.

### Questions and confirmation

- Ask only for information needed for the current safe action.
- Do not repeat a confirmed question unless a later contradiction makes it material.
- Ask one focused question when one answer can unblock the next action.
- Confirm only a material interpretation, conflict, declaration, customer-controlled
  decision, or fact whose error could change the next consequential action.
- Do not require the claimant to audit the complete internal form. Show the structured
  form when requested or when it is the clearest way to correct a material issue.
- Stop questioning when the current action can progress safely.

### Field and branch selection

- Begin with the smallest generally applicable field set and expand it only through
  predefined, versioned content branches.
- A model may propose a claim family, condition, field value, or tag, but an approved rule
  controls which registered fields and sub-branches become active.
- Treat fields as required now, candidate now, pending later, inactive, or system-owned
  for the current action. `Core FNOL` does not mean globally mandatory.
- Activate motor, home, contents, other-party, witness, Police, injury, theft, evidence,
  and other conditional groups only when supported by the claim context.
- Do not ask a claimant for system-generated fields or information owned by authenticated
  customer context, provider lookup, workflow, integration, or authorised staff when it
  is already available.
- Do not ask home or contents claimants vehicle-only questions, or motor claimants
  property-only questions, unless the incident genuinely activates that additional
  branch.
- Keep content branches separate from lifecycle. Content branches determine applicable
  information and tools; lifecycle and WorkItems determine where work is, who owns it,
  and what specific action is blocked.
- Recalculate active fields after a material fact, correction, evidence update, resume,
  or handoff. Preserve prior values, branch history, and source history when a content
  branch changes.
- Never create an unregistered field, tag, branch, or mandatory condition from model
  output.

### Next-step-ready progress

- Distinguish information needed now from evidence needed for a later action.
- Record missing, incomplete, unofficial, or not-yet-generated evidence honestly.
- Do not block unrelated safe work because later evidence is unavailable.
- State what can proceed, what remains outstanding, who is responsible, and any timing
  that is actually known.

### Human support and professional judgement

- Treat a request for a person as a support need, not an error or adversarial prompt.
- Do not repeatedly resist transfer. Repeated requests, urgent conditions, distress, or
  accessibility needs transfer immediately.
- Apply the configured first-request rule transparently; the production rule remains open
  until Northwind approves it.
- Transfer a structured packet containing confirmed facts, sources, gaps, responsibility,
  prior commitments, and the specific requested staff action. A transcript alone is not
  a sufficient handoff.
- Preserve complete messages under authorised staff access and include relevant message
  references in the packet so staff can verify source wording without reading the full
  transcript first.
- Coverage ambiguity, conflicting material evidence, fraud-review signals, liability,
  approval, rejection, and other high-impact judgement remain with deterministic or
  authorised professional authority.

### Urgent conditions

- Explicit injury, continuing danger, or another approved safety signal interrupts
  ordinary intake.
- Give concise, bounded guidance and create the urgent handoff before returning to
  ordinary questions.
- Never diagnose injury or claim that emergency services, staff, or another participant
  were contacted unless the relevant service confirms it.

## Action and Authority Rules

A turn may include several conversation moves and several command proposals, but it has
one primary Runtime control directive. The action system has five namespaces:

| Namespace | Responsibility | Representative registered actions |
| --- | --- | --- |
| `conversation` | communicate without a business side effect | acknowledge, answer, explain, ask, clarify, confirm material content, summarise, present options, state a limitation |
| `claim` | prepare or make revision-checked Claim changes | open or resume a draft, propose/apply/correct facts, recompute the form, register evidence, update WorkItems, save progress, prepare creation, create |
| `human` | obtain support, professional judgement, or approval | offer support, create handoff, request professional review, request approval, record decision |
| `external` | coordinate a third-party request through its full lifecycle | discover capability, load requirements, prepare, classify, check authority, submit, track, verify, reconcile, retry, cancel, escalate failure |
| `runtime` | control execution of the turn | continue, wait for user, wait for external work, pause for review, interrupt urgently, stop without a Claim, fail safely |

The old `ASK`, `CLARIFY`, `CONFIRM`, `PROCEED`, `UPDATE`, `HANDOFF`,
`URGENT_HANDOFF`, and `CREATE_CLAIM` values are a migration mapping for the current API,
not the new canonical model.

Every auditable action uses an `ActionEnvelope` with a stable action ID, namespace,
registered name, target, proposer, reason and source references, validated inputs,
preconditions, authority requirement, expected effects, idempotency key when relevant,
visibility, and actual status. A model may propose an envelope but cannot redefine its
semantics or invent a private equivalent that bypasses validation.

| Behaviour | Required enforcement | Model responsibility |
| --- | --- | --- |
| Claimant and staff visibility separation | server projection and access control | use only the supplied projection |
| Allowed tools and permitted purpose | server-side allow-list and scoped credentials | request only declared tools |
| High-impact state change | deterministic rule or authorised staff decision | propose with reasons and sources only |
| Urgent interruption | approved trigger and handoff state transition | identify explicit signals and give bounded wording |
| Material confirmation | field state and consequence-aware orchestration | explain the interpretation and request correction |
| Non-repetition and focused questions | current claim state, unresolved-work tracking, and evaluation | choose the smallest useful question |
| Friendly, plain-language response | response contract and evaluation | produce claimant-facing wording |
| Token and context limit | context builder and model gateway | operate only on the supplied bounded context |

Rules that protect authority, access, state integrity, or side effects must never rely on
prompt compliance alone.

## Staff Capability Rules

`@Agent` invokes the Agent within the current staff identity, role, Claim scope, and task.
It is not command syntax. Staff may make open natural-language requests, and the runtime
may combine registered capabilities for Claim reading and summary, gap explanation,
evidence comparison, policy retrieval and explanation, next-step proposals,
communication drafting, handoff inspection, external-request preparation, and authorised
execution.

Each Staff Capability Registry entry defines permitted roles, maximum context projection,
allowed tools and actions, output schema, execution policy, and evaluation scenarios.
Suggested UI actions are discovery aids only. Read permission never becomes send,
mutation, disclosure, or high-impact execution permission without the applicable
action-level authority check.

## Tool, Retrieval, and Data Rules

- The Agent uses provider-neutral application tools and never connects directly to a
  database, object store, vector index, provider SDK, or secret manager.
- Every tool call requires an allowed tool, permitted purpose, claim scope, validated
  input, source references, required permissions, expected Claim revision for writes,
  idempotency where applicable, disclosure manifest, and bounded result contract.
- Structured customer policy and claim history use authorised record lookup. Knowledge
  RAG is used for approved documents and retains source version and section citations.
- Retrieved instructions are untrusted content. They cannot change Agent Policy, grant
  tool access, widen customer-data visibility, or authorise an action.
- Missing, conflicting, expired, wrong-insurer, wrong-product, wrong-jurisdiction, or
  wrong-effective-period evidence is a limitation, not permission to guess.
- Tool and provider failures preserve accepted claim progress and return an honest,
  actionable limitation.
- A third-party request is not one generic tool call. Capability discovery, requirement
  loading, preparation, classification, authority and consent, submission, tracking,
  response verification, reconciliation, retry, cancellation, and failure escalation use
  distinct registered operations and results.
- A timeout after a side-effect request may be an unknown outcome. Query by the same
  idempotency key or provider reference before retrying; never duplicate an external
  action merely because acknowledgement was lost.

## Context and Memory Rules

- Routine context contains the current Claim State, unresolved work, compact session
  summary, necessary recent messages, prior commitments, authorised structured results,
  relevant cited knowledge, and permitted tool results.
- Complete conversations and claim history remain durable outside routine model context.
- Summarisation must preserve confirmed facts, unresolved conflicts, source references,
  pending work, responsibility, and promised next steps.
- Customer preferences may adapt communication but cannot replace formal claim records,
  change decision authority, or grant data access.
- Customer Memory may be used only when the memory has an explicit source, permitted
  visibility, a current purpose, and a valid retention period. It is a small continuity
  layer, not a compressed copy of all prior claims or conversations.
- A category-level continuity hint such as a prior incomplete interaction may help offer
  resume, but must not be treated as evidence that the customer is unreliable, fraudulent,
  low priority, or unwilling to cooperate.
- The Agent must distinguish a non-claim conversation from a claim draft. It must not
  create a claim from teasing, general questions, or unrelated chat without credible
  claim intent.
- A memory record must not override current claimant statements, current Claim State,
  policy records, evidence, staff decisions, or explicit correction by the customer.
- The Agent must not receive secrets, raw provider payloads, unrelated customer records,
  complete history without a permitted purpose, or unbounded conversation history.

## Response Rules

Each claimant-facing response must:

- answer or acknowledge the latest message before moving to the next task;
- distinguish known facts, proposed interpretations, limitations, and decisions;
- use plain, professional language without exposing internal labels or infrastructure;
- state the next useful action and responsible party when applicable;
- avoid invented timing, certainty, coverage, contact, or completion claims; and
- remain consistent with the persisted claimant-safe state after execution.

The final response is produced from `TurnResult`, not directly from the model proposal.
It must distinguish proposed, approved, executing, succeeded, failed, rejected, and
unknown outcomes whenever that distinction affects the user's next step.

The response must not expose hidden reasoning, full prompts, internal fraud indicators,
staff-only notes, credentials, provider internals, or another customer's data.

## Failure and Fallback Rules

- Invalid structured output, unsupported tool use, or an unauthorised state change is
  blocked and recorded; it is never repaired into a side effect by guessing intent.
- Structured Claim or side-effect proposals must not be recovered by parsing free text
  when the model profile lacks the required output capability.
- A model timeout or unavailable provider preserves claim state and produces a bounded
  retry, status update, or handoff according to the current action.
- A fallback model may be used only when it satisfies the same required capabilities,
  policy version, data terms, tool boundary, and evaluation threshold.
- The system must not silently switch data runtime profiles or use a fixture as a
  production fallback.
- When no safe automated action remains, preserve context and transfer the specific
  unresolved work rather than continuing an unproductive question loop.
- Errors are normalised by layer, retry class, state effect, safe message, and diagnostic
  reference. Provider error text cannot become a claimant response or an action rule.

## Publication and Rollback

The Control Plane policy lifecycle is:

```text
draft -> validate -> approve when required -> publish -> observe -> supersede or roll back
```

- Validation uses the policy's required scenarios against every supported model profile.
- High-impact business rules, tool permissions, data access, and model changes require
  the configured stronger approval.
- Publication is atomic: one runtime sees one complete active policy version.
- Rollback activates an approved prior version without deleting intervening history.
- New non-safety rules should normally begin in observation or shadow mode before
  enforcement. Existing safety, access, and authority boundaries remain enforced and
  cannot be downgraded to observation-only.
- Secret values are never stored in the policy bundle; only approved secret references
  may be configured.

## Audit and Evaluation

Once runtime policy loading is implemented, each turn must retain the active policy and
Registry versions, `TurnPlan`, `AgentProposal`, approved and rejected action envelopes,
`ExecutionPlan`, requested and executed tools, authority results, `TurnResult`, state
effects, response, model-profile identity, usage, latency, limitations, and time. Logs
must follow the same privacy and visibility rules as the underlying claim data.

Policy evaluation must include:

- multidimensional trajectories that distinguish conversation, Claim commands, human
  actions, external work, runtime control, and actual execution results;
- urgent, human-request, professional-review, pending-evidence, resume, and creation paths;
- incomplete-claim resume, non-claim intent, customer-memory expiry, and memory correction;
- motor, home, contents, and conditional branch activation without irrelevant cross-branch
  questions;
- dynamic required-now and candidate-field selection without treating the field model as
  one mandatory questionnaire;
- unsupported coverage and fraud conclusions;
- material confirmation and non-repetition;
- tool allow-list, prompt-injection, and data-visibility attacks;
- RAG citation support and wrong-source rejection;
- model, tool, and data-provider failure;
- malformed, incomplete, refused, and capability-incompatible model results;
- unknown external outcomes, status-before-retry, and duplicate-side-effect prevention;
- open-ended staff requests, read-versus-execute authority, and safe communication drafts;
- claimant clarity, handoff completeness, token use, and avoidable staff effort.

A build pass does not prove policy compliance. Policy publication requires recorded
scenario results and acceptance thresholds appropriate to the changed rule.

## Open Decisions

- Northwind's production urgent, first human-request, claim-creation, routing, coverage,
  severity, and fraud-review rules.
- Policy ownership roles and which changes require two-person approval.
- The machine-readable policy schema, storage mapping, Admin API, and runtime cache.
- The executable field, tag, and branch catalogues and their relationship to policy
  publication and code-level schema migration.
- Required evaluation datasets and thresholds for each supported model profile.
- Whether policy selection varies by product, jurisdiction, channel, locale, or controlled
  experiment, and how conflicts are prevented.
- Observation, enforcement, emergency-disable, and rollback service-level requirements.
