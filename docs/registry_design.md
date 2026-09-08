# Registry and Dynamic FNOL Form Design

## Purpose

This document defines the controlled Registry and claim-specific First Notification of Loss
(FNOL) information-form design. It also identifies the bounded Validation Prototype (VP)
implementation; `docs/api.md`, `docs/persistence-schema.md`, and exact-head tests remain the
implementation evidence and transport authority.

The central rule is:

> The Registry defines what the system is allowed to use. Claim State records what is
> true or unresolved for one claim. The dynamic form is a projection calculated from
> both, not a second source of truth.

The design supports natural claimant conversation while keeping the internal
information model complete, bounded, and reviewable.

## Core Model

The implementation should use a controlled field catalogue, declarative branch rules,
and a recalculable Claim State rather than a large hard-coded `if-else` tree.

```text
Field Registry       -> which fields may exist
Content Branch Registry -> which incident-content branches may exist
Rule Set             -> when registered fields and branches become active
Lifecycle Registry   -> which claim states and transitions may exist
Action Registry      -> which conversation, Claim, human, external, and runtime actions may exist
Tool Registry        -> which bounded application operations may be requested or executed
Staff Capability Registry -> which capabilities staff may combine through natural language
Model Profile Registry -> which model capabilities and data terms are verified for each purpose
Error Registry       -> which stable failures, retry classes, and state effects may exist
Follow-up and Retention Policies -> when work is followed up or removed
Claim State          -> facts, sources, statuses, branches, and unresolved work
Form Projection      -> what the Agent asks, shows, or can safely skip now
```

Registry is not one database table. It is a set of independently versioned and validated
finite contracts. A database may persist their published snapshots, but storage is an
implementation detail. Runtime code and model output may reference only published
definitions, and Registry never stores what is currently true for one Claim.

## Registry Responsibilities

### Field Registry

The Field Registry defines every field that the application may store, validate,
display, or use in a rule. A field definition should include at least:

```text
code
value_type
allowed_values
visibility
allowed_sources
confirmation_policy
validation
sensitivity
claimant_label
staff_label
```

Examples include `vehicle.registration`, `vehicle.drivable`,
`incident.injury_or_danger`, and `authorities.police_report_reference`.

The existence of a field in the catalogue does not mean that it is mandatory for every
claim, claimant-supplied, or required before claim creation.

### Content Branch Registry

The Content Branch Registry defines the approved information dimensions that may be
activated for a Claim. Content branches answer what information and rules apply to the
incident. They do not store lifecycle states such as draft, waiting, review, or created.

| Dimension | Examples | Purpose |
| --- | --- | --- |
| Claim family | motor, home, contents, unknown | Select the relevant product or incident field group |
| Incident type | collision, theft, fire, water, weather, accidental damage | Add applicable incident facts and evidence rules |
| Participant | another party, witness, Police, repairer, assessor | Add supported participant and coordination information |
| Safety and support | injury, continuing danger, distress, accessibility | Supply an interruption signal and change the support approach without becoming a lifecycle state |
| Evidence state | available, missing, incomplete, unofficial, pending generation | Describe responsibility and timing without blocking unrelated work |
| Professional authority | coverage ambiguity, material conflict, review signal | Request staff attention without making the decision automatically |

A claim may have one primary claim-family branch and several simultaneous conditional
branches. For example:

```text
motor
+ another_party
+ police_report_pending
+ evidence_incomplete
+ professional_review_required
```

One route label must not erase an independent injury, evidence, responsibility, or
review dimension.

Each content-branch definition includes its stable code and version, dimension,
activation and exit conditions, conflict group, fields, tags, rules, and tools it may
add, confirmation policy, visibility, and resume policy. The model proposes a candidate
with supporting facts and provenance. The rule engine alone controls
`proposed -> active -> suspended -> exited/corrected`.

### Rules and Current-action Requirements

Rules should be declarative and limited to a finite set of condition operators such as
`exists`, `equals`, `in`, `all`, `any`, and `not`. Configuration must not execute
arbitrary Python, JavaScript, or model-generated code.

Rules determine which registered fields, tags, and sub-branches become active. Action
requirements determine the minimum information needed for a safe current action. They
must not turn the entire field catalogue into a mandatory questionnaire.

The model may propose a classification or value, but deterministic validation controls
activation, authority, visibility, and side effects.

### Lifecycle Registry and WorkItems

The Claim lifecycle is a finite state machine, not a collection of unrelated booleans.
It answers where the work is, who owns it, and what it is waiting for. The Registry
defines allowed states, transitions, responsibilities, resume behaviour, recovery,
expiry, and visibility. A starting set is:

```text
no_claim
draft_active
waiting_customer
waiting_external
staff_support
professional_review
ready_to_create
creating
created
withdrawn
expired
purged_or_anonymised
```

`waiting_customer`, `waiting_external`, explicit customer withdrawal, and
timeout expiry must remain distinguishable. A session with no credible claim intent may
remain `non_claim_intent` without creating a claim at all.

Lifecycle definitions should also identify whether the state is resumable, whether it is
staff-visible, who owns the next action, and what event can move it forward. Status fields
such as `saved`, `active`, and `abandoned` may be derived for filtering, but they must not
be the competing source of truth.

A Claim may have several independent `WorkItem` records while holding one lifecycle
state. Each WorkItem records its type, status, owner, exact action blocked, due time when
authoritatively known, source references, and completion evidence. A Police document may
therefore remain outstanding while unrelated Claim creation work continues.

### Action Registry

The Action Registry defines finite actions across five namespaces:

| Namespace | Meaning |
| --- | --- |
| `conversation` | Communication such as answering, explaining, asking, clarifying, or summarising, with no business side effect |
| `claim` | Revision-checked proposals or changes to facts, evidence, WorkItems, draft progress, and Claim creation |
| `human` | Support handoff, professional review, approval, and staff-decision actions |
| `external` | Preparation, authority, submission, tracking, verification, reconciliation, and recovery for third-party work |
| `runtime` | One primary directive controlling whether the turn continues, waits, pauses, interrupts, stops, or fails safely |

Every action definition records its input schema, preconditions, state effect, authority,
visibility, idempotency need, permitted tools, response obligation, failure policy, and
prohibited outcomes. The model may propose only registered actions; a schema-valid
proposal is not execution authority.

### Tool Registry

The Tool Registry defines provider-neutral application capabilities, not provider SDK
methods. Each tool has one bounded purpose, typed input and output, required scopes,
allowed Agent purposes, side-effect class, idempotency support, retry and timeout policy,
minimum disclosure rules, and audit requirements. A tool result proves only the result it
reports; requesting a tool never proves that the action completed.

### Staff Capability Registry

The Staff Capability Registry describes problems the Agent may help authorised staff
solve, including Claim summary, gap explanation, evidence comparison, policy retrieval,
next-step proposals, communication drafts, handoff inspection, and external-request
preparation. `@Agent` selects and combines these capabilities from ordinary language; it
is not a fixed command language.

Each capability defines allowed roles, maximum Claim projection, allowed tools and
actions, output schema, execution policy, and evaluation scenarios. Read-only capability
does not grant mutation, send, disclosure, or high-impact decision authority.

### Model Profile Registry

The Model Profile Registry stores adapter and endpoint references, real provider model
identity, secret references, verified capabilities, data terms, permitted privacy classes
and purposes, qualified fallback group, evaluation evidence, and lifecycle status. It
does not store FNOL permissions or business rules. A model that returns text but lacks
strict structured output cannot be used for a purpose that requires structured Claim or
side-effect proposals.

### Error Registry

The Error Registry supplies stable codes for model, tool, Claim State, retrieval,
external, authentication, and runtime failures. Each entry defines retry class, state
effect, safe role-facing message, diagnostic reference rules, and any provider-code
mapping. A timeout after an external side effect can be `unknown_outcome`; it must be
reconciled before retry rather than treated as a simple failure.

### Follow-up and Retention Policies

Follow-up and retention are policy modules in the Registry, not hard-coded Agent side
effects. A policy should define:

```text
policy_id
trigger_state
responsible_party
follow_up_due_after
allowed_channels
maximum_attempts
expiry_after
purge_or_anonymise_action
retention_hold_requirements
```

The Agent or staff may create a follow-up task only when the approved policy permits the
channel, timing, consent, frequency, and authority. Expiry makes a record eligible for a
retention job; it does not allow an Agent turn to delete data directly.

Claim-specific content may be deleted or anonymised after expiry. A small, source-linked,
time-limited Customer Memory record may survive if it has an explicit product purpose,
visibility rule, correction path, and expiry. A previous interruption must not become a
permanent reliability, fraud, or service-priority label.

## Dynamic Form Behaviour

The claimant starts with a natural account rather than a pre-expanded questionnaire.
The system builds a claim-specific form through the following sequence:

```text
natural claimant account
-> explicit facts and bounded classification proposals
-> safety and human-support interruption checks
-> content-branch candidates with sources
-> approved rule activates registered fields and tags
-> conditional sub-branches activate when supported
-> current action identifies required-now and candidate fields
-> TurnPlan may combine communication, form patches, lookups, and the next step
-> Runtime validates an ExecutionPlan and applies only authorised effects
-> Claim State changes cause branches, WorkItems, lifecycle, and form to be recalculated
```

The form is dynamic because its active subset changes for each claim. Its schema is
controlled because every field, tag, branch, selection state, and rule reference must
already exist in a published contract. A model or client cannot create an arbitrary
field name, tag, branch, mandatory condition, or high-impact outcome.

### Field Selection States

For the current claim and next action, each predefined field may be classified as:

| State | Meaning |
| --- | --- |
| Required now | Missing information blocks the current safe action under an approved rule |
| Candidate now | Relevant information may help, but does not justify extra claimant effort yet |
| Pending later | Relevant to a known later action or unavailable evidence, but not a current blocker |
| Inactive | Not supported by the active claim and condition branches |
| System-owned | Supplied by identity, lookup, workflow, integration, staff, or audit rather than by a claimant question |

These are selection states. They do not replace stored field states such as `proposed`,
`confirmed`, `disputed`, `missing`, or `pending_generation`.

`Core FNOL` also does not mean globally mandatory. A core field may remain unknown while
an urgent handoff, evidence registration, support transfer, or another safe action
proceeds.

### Question Selection

The Agent and orchestration layer select the next question by:

1. handling an explicit safety or support interruption first;
2. reusing authenticated, retrieved, confirmed, or clearly claimant-supplied information;
3. excluding inactive, system-owned, already confirmed, and later-stage fields;
4. identifying fields required for the current next action;
5. resolving one material ambiguity or conflict when it blocks selection;
6. asking one focused question with the highest current value; and
7. progressing without another question when the next action is safe.

The field catalogue is not a reason to complete every possible field in one interaction.
The internal form reduces repeated questions and staff reconstruction; it must not force
the claimant to learn or audit the insurer's internal workflow.

## Motor Branch Example

For a statement such as:

> Another car hit the rear of mine at Queen Street. Nobody was injured.

the system should:

1. save the natural account and its source;
2. evaluate injury, danger, human-support, and accessibility signals;
3. propose `claim.product_family = motor` from supported wording and, when the event
   meaning is also supported, propose `incident.type = collision` independently;
4. activate the approved motor branch and its registered fields;
5. activate `another_party`, Police, evidence, towing, or property sub-branches only when
   supported by the claim context;
6. treat the explicit statement that nobody was injured as claimant-supplied instead of
   asking the same question again;
7. make only information needed for the current safe action `required now`; and
8. recalculate the next action after each accepted fact, correction, evidence update, or
   handoff.

If later information shows that the incident is a home or contents claim, active
branches are recalculated. The original account, source history, and prior decisions are
not silently rewritten or deleted.

## Value Sources and Confirmation

The same value has different authority depending on its source:

| Source | Treatment |
| --- | --- |
| Explicit claimant statement | Record as claimant-supplied; ask again only for ambiguity, conflict, declaration, or consequential uncertainty |
| Model interpretation | Keep proposed when material and retain the source message |
| Evidence extraction | Keep proposed with evidence provenance until the required claimant or staff decision |
| Structured provider result | Preserve its typed source and limitations; do not convert it into a high-impact conclusion |
| System or staff result | Record actor and authority and expose only the role-appropriate projection |

The internal form can translate natural language into professional structure, but it
must not change meaning or make the claimant review every low-impact field.

## Tags and Review Signals

Tags are useful for branch selection, filtering, routing, and workbench views, but they
are not substitutes for formal field values or professional decisions.

Every tag or review signal requires a predefined code, source, purpose, visibility,
lifecycle, and rule reference. Examples include:

| Example | Role |
| --- | --- |
| `motor` | Claim-family or workflow branch indicator |
| `police_report_pending` | Evidence state |
| `awaiting_customer_evidence` | Workflow responsibility |
| `fraud_review_required` | Staff-only review signal, not a fraud finding |

Internal-only tags never enter the claimant projection. A branch or tag may support
selection and routing, but it cannot represent coverage, liability, fraud, approval,
rejection, or another high-impact conclusion without the separate authorised decision.
Changing a branch must not silently erase a staff decision or audit history.

## Claim State and Form Projection

The dynamic form must not become a second copy of the claim. The authoritative state is
Claim State, including facts, sources, field statuses, active branches, evidence state,
unresolved work, and current action.

```text
published Registry version
+ Claim State
+ active branches
+ current next action
= current claimant and staff form projections
```

The claimant projection contains friendly labels and only the information needed for
their current action. The staff projection can include structured facts, sources,
pending work, internal signals, and the complete message references needed to verify the
handoff packet.

On resume or branch correction, active branches are recalculated from the latest
authoritative Claim State rather than from a fixed questionnaire or stale session copy.
Confirmed values, source history, unresolved work, evidence state, and prior commitments
survive resume and correction.

Claim lifecycle fields and Customer Memory are not ordinary dynamic form fields. The
former belong to Claim State and workflow; the latter belongs to a separate customer-level
record. Both may influence which form projection is shown, but neither should be exposed
as an unfiltered claimant questionnaire field.

## Versioning and Publication

Registry definitions should be published as immutable snapshots. A published definition
is never edited in place; a change creates a new draft and a new version.

Each published snapshot should identify:

```text
registry_id
version
status
author
change_reason
approver_when_required
effective_time
previous_version
rollback_target
validation_result
```

Each claim should retain the Registry version used to calculate its current form. The
initial implementation may load one validated static snapshot at startup. Later, the
Control Plane can provide draft, validation, approval, publication, observation, and
rollback without changing the meaning of an in-progress claim unexpectedly.

## Contract Boundaries

Adding a field code, changing its type or visibility, changing stored status semantics,
or exposing a field through claimant or staff APIs is a shared contract change. It
requires coordinated updates to the field model, API contract, domain validation,
persistence mapping, projections, fixtures, and tests.

Adding or changing a Content Branch, Lifecycle, Action, Tool, Staff Capability, Model
Profile, or Error Registry entry requires the same impact analysis for every consumer of
its semantics. A wording-only change may avoid a storage migration, but a change to
authority, visibility, side effects, retry, state transition, or output schema is a shared
contract change.

Changing wording or candidate priority is not automatically a schema change, but it
still requires Agent Policy evaluation and publication. Making a field required for
claim creation, urgent handling, or another high-impact action is a controlled business
rule and requires Northwind authority.

## Progressive Implementation

## VP Branch Evaluation Contract

The VP contract is implemented in `backend/domain/branch_registry.py` as a checked-in,
provider-neutral Field Registry snapshot (`4`), branch-rule snapshot
(`vp-dynamic-form-branch-rules-v1`), and pure `BranchRuleEvaluator`. The evaluator does not call a
model, provider SDK, or repository and does not mutate Claim State. It returns an evaluation for
the supplied Claim revision. The message service supplies a pre-effect result to the Agent turn
context, validates proposals against its allowed fields, then recomputes the applied result from
the resulting Claim snapshot. Persistence adapters atomically store that immutable result with
the Claim mutation.

This section records the agreed contract for the Sprint 3 Validation Prototype branch
engine. It is the implementation baseline for the complete three-path design; it is not a
claim that every component below already exists in the repository.

### Family selection and shared fields

The three claim-family branches are mutually exclusive for one working claim:

```text
family.motor XOR family.home XOR family.contents
```

One draft claim may select only one family at a time and one formal claim may be submitted
for only that selected family. A claimant may correct an unsubmitted family classification.
The correction suspends or exits the previous family candidates, preserves the original
message and source history, and recalculates the form. After formal claim creation, a family
change is not a silent route switch; it requires the approved correction or professional-
review path.

Family exclusivity does **not** make all fields family-specific. Shared fields retain one
canonical representation and remain available under whichever family is selected. Examples
include `incident.description`, `incident.occurred_at`, `incident.location`,
`incident.cause`, `loss.description`, claimant context, policy reference, and bounded
safety/support signals. Conditional branches such as collision, another party, Police,
pending evidence, human support, and professional review may be active alongside exactly one
family branch.

For example:

```text
family.motor
+ incident.collision
+ participant.another_party
+ authority.police
+ evidence.pending
```

This is additive branch state, not one flattened route label. Shared fields are never copied
into `motor.*`, `home.*`, or `contents.*` variants merely because a family was selected.

The evaluator reconciles the existing top-level `WorkingClaim.incident_type` compatibility
projection with the source-aware `claim.product_family` form field. A request-supplied top-level
value selects the current family. A confirmed form value can also select it, and matching
authoritative values coalesce. Conflicting authoritative values produce an unresolved family
conflict instead of silently choosing one. A `proposed` or `disputed` form value remains only a
family candidate until it crosses the applicable confirmation boundary. `incident.type` is
independent: it records an event subtype such as `collision`, `fire`, `water`, `theft`, or
`weather`, and it can activate an additive conditional branch but never selects a product family.

### Two independent field-state dimensions

The evaluator must keep field selection state separate from stored value state.

**Selection state** answers where a field sits in the current claim and current action:

| Selection state | Meaning |
| --- | --- |
| `required_now` | The field is missing and a published rule says the current safe action cannot proceed without it. |
| `candidate_now` | The field is relevant to the active branches, but missing it does not block the current safe action. |
| `pending_later` | The field or material belongs to a later action, or its evidence is not yet available. |
| `inactive` | The field is not supported by the current family or conditional branches. |
| `system_owned` | The authoritative source is identity, provider lookup, workflow, integration, staff, or audit; it must not be collected as an ordinary claimant question. |

**Value state** answers whether the information itself is present and authoritative:

| Value state | Meaning |
| --- | --- |
| `missing` | No usable value has been accepted. |
| `proposed` | A model, evidence extractor, claimant message, or other source proposed a value that still needs the applicable confirmation or authority. |
| `confirmed` | The value passed the applicable confirmation or authoritative-source boundary. |
| `disputed` | The value conflicts with another source or has been explicitly challenged. |
| `pending_generation` | The value depends on material that is expected but has not yet been generated. |

`system_owned` does not mean “already collected”. It describes the authority of the field's
source. A claimant-supplied field remains claimant-sourced with `proposed` or `confirmed`
value state; it must not be relabelled `system_owned` merely because the Agent structured it.
For example:

```text
vehicle.drivable:
  selection_state: required_now
  value_state: missing

vehicle.drivable:
  selection_state: required_now
  value_state: proposed

vehicle.drivable:
  selection_state: required_now
  value_state: confirmed

claim.created_at:
  selection_state: system_owned
  value_state: confirmed
  source: system
```

### BranchRuleEvaluator contract

`BranchRuleEvaluator` is a provider-neutral, deterministic application component. It does
not call a model, provider SDK, database, or external service, and it does not directly
mutate Claim State.

It receives:

- the latest authoritative `WorkingClaim` snapshot and Claim revision;
- accepted facts and their source references;
- current proposed, disputed, missing, and pending values;
- the latest claimant message or other trigger context;
- the registered Field and Content Branch catalogue;
- the current action and open WorkItems;
- Evidence, Handoff, Consent, Review, and Integration records relevant to the purpose;
- the active policy and Registry versions; and
- the set of fields and branches that are actually registered and executable.

It returns a deterministic `BranchEvaluationResult` containing:

- exactly one selected family, or an unresolved family conflict;
- active, candidate, suspended, and exited branches with rule IDs and source references;
- the registered fields each branch adds to the active projection;
- selection state for every relevant field;
- the current `required_now`, `candidate_now`, `pending_later`, `inactive`, and `system_owned`
  sets;
- proposed creation or update intents for WorkItem, Handoff, Evidence, Review, Consent, or
  Integration records;
- the primary runtime interruption/control signal when safety or support takes precedence;
- the rule-set and registry versions used for evaluation;
- the Claim revision against which the result was calculated; and
- a bounded recomputation reason.

The result is an evaluation proposal and evidence record. Runtime decides whether it can be
applied under the current revision, authority, visibility, confirmation, idempotency, and
side-effect rules.

### Evaluation order

The evaluator applies the following precedence while retaining additive branch state:

1. Explicit injury, continuing danger, or emergency safety signals.
2. Repeated human requests, distress, accessibility needs, and the configured first-request
   human-support rule.
3. Family classification for `motor`, `home`, or `contents`; unresolved conflict remains a
   candidate/clarification state and cannot activate two families.
4. Incident and participant dimensions such as collision, theft/burglary, another party,
   witness, and Police.
5. Evidence and mitigation dimensions such as pending materials, towing, emergency repair,
   or temporary accommodation.
6. Professional-review conditions such as material conflict or coverage ambiguity.
7. Field-selection promotion for the current action.

The first two steps determine the primary Runtime control directive. Later steps may still
produce useful fact, evidence, or WorkItem proposals without overriding that directive.

### BranchEvaluationRecord

The VP uses an immutable `BranchEvaluationRecord` for every material branch/form
recalculation. It records why a particular Dynamic Form projection existed at a particular
point in the claim's history without becoming a second Claim State.

The record contains at least:

```text
evaluation_id
claim_id
session_id or turn_id
evaluated_against_claim_revision
resulting_claim_revision (when applied)
field_registry_version
branch_rules_version
selected_family or unresolved_family_conflict
branch_results[]
field_selection_results[]
work_item_intents[]
handoff/review/evidence/consent/integration intents[]
interruption_result
recomputation_reason
status (evaluated | applied | stale | superseded)
created_at
```

`branch_results[]` retains active, candidate, suspended, and exited branch states. Each
state carries its rule ID and supporting source references. `field_selection_results[]`
retains the selection state independently from the stored field's value state. A record may
also retain bounded rule diagnostics, but never secrets, raw provider payloads, hidden model
reasoning, or unrestricted Claim State.

Each material recalculation compares the new Claim snapshot with the latest valid applied
evaluation. A conditional branch that was active or candidate and then loses support is retained
in the new evaluation as `suspended` or `exited` according to its registered correction rule. The
transition retains the original rule and source references and adds the source coordinate for the
correction. Branches that have never been supported are not manufactured as conditional exits.

The bounded current claimant message is also evaluated for explicit human-support,
accessibility, and distress signals before ordinary field selection. A shared deterministic
classifier supplies the same signal to the controlled Agent and branch evaluator. Negated requests
and ordinary references to another person do not create a support branch. A qualifying signal
produces a source-linked handoff intent and takes precedence over ordinary questioning; after the
handoff mutation, authoritative Claim State activates the same branch in the applied evaluation.

The authority relationship is:

```text
Claim State
  = current business facts, values, sources, lifecycle, and WorkItems

BranchEvaluationRecord
  = immutable evidence of one rule evaluation against one Claim revision

Dynamic Form
  = projection of Claim State + latest valid branch evaluation
```

The evaluation record never becomes a competing source of current facts. If the Claim revision
changes from 12 to 13 before an evaluation calculated against revision 12 is applied, the result
cannot be attached to revision 13 and must be recomputed. The old record remains immutable audit
evidence but no longer qualifies as the current Dynamic Form projection. A future status event
may describe it as stale or superseded, but must not rewrite the calculation payload.

### Runtime and Agent integration

The Agent does not read this Markdown directly. The intended runtime path is:

```text
published Field / Content Branch Registry snapshot
        ↓
BranchRuleEvaluator
        ↓
BranchEvaluationRecord
        ↓
Dynamic Form controller
        ↓
bounded AgentTurnContext
        ↓
Model Gateway / Agent proposal
        ↓
proposal validation against active branches and field selection
        ↓
ExecutionPlan and revision-checked Runtime effects
        ↓
Claim State mutation
        ↓
new BranchEvaluationRecord and updated Dynamic Form projection
```

The Agent receives only the bounded result needed for the current turn, including active
branches, allowed registered fields, selection states, required-now fields, pending work,
permitted actions/tools, and safe interruption information. It may propose a branch
candidate, field patch, question, lookup, or handoff action, but it cannot activate a branch,
make an unregistered field valid, write Claim State, or perform a side effect by itself.

The Dynamic Form controller consumes the evaluator result to:

- expose only active and permitted fields;
- exclude inactive and system-owned fields from claimant questions;
- avoid asking for confirmed or clearly claimant-supplied facts again;
- choose the smallest useful question when a `required_now` answer is needed;
- preserve pending evidence and unrelated safe progress;
- accept multiple facts from one natural-language message;
- recalculate after material facts, corrections, evidence updates, resume, and handoff; and
- reject model proposals for unknown, inactive, or unauthorised fields.

The complete three-path catalogue in `docs/fnol-field-model.md` is design authority, not a generic
write allowlist. The executable registry contains only field codes that already have compatible
domain, API, persistence, and visibility contracts. Candidate fields and separate Evidence,
Participant, Contents Item, WorkItem, Handoff, Consent, and Integration records remain outside
`WorkingClaim.form` until their owning typed contracts and consumers land together.

### VP implementation boundary and ownership

The agreed VP build includes the registry, deterministic evaluator, immutable evaluation
record, field-selection logic, Dynamic Form control integration, Agent context injection,
branch-aware proposal validation, and focused tests for the three paths and their important
conditional branches. It is not limited to a presentation-only mock.

The implementation may initially load a checked-in, versioned registry/rule snapshot through
a local adapter, provided that the application-facing port remains replaceable. A later
Control Plane publication can supply the active snapshot without changing Agent code.

`Ysoseri1224` owns the construction of these capabilities, including domain, API,
persistence, Dynamic Form, Agent integration, fixtures, and tests. `liyang6620` is not an
implementation dependency for this work; he is expected to be informed of the field and data
impact, validate the API/domain/repository/database mapping, and review the resulting PR.

Any new field code, branch, selection state, `BranchEvaluationRecord` persistence, API
projection, visibility rule, or revision behavior is a shared contract change. The same PR
or coordinated implementation set must update affected API documentation, persistence
contracts, domain validation, repositories/adapters, claimant/staff projections, fixtures,
and tests. No independent second concurrency counter or competing Claim State may be
introduced.

### Explicit non-goals

- Do not make `motor`, `home`, and `contents` simultaneously active for one formal claim.
- Do not duplicate shared fields under each family namespace.
- Do not use `system_owned` as a synonym for “value collected”.
- Do not let the Agent or model activate branches or write Claim State directly.
- Do not turn the complete field catalogue into a fixed questionnaire or mark every field
  `required_now`.
- Do not flatten Evidence, Handoff, WorkItem, Review, Consent, or Integration records into
  ordinary form strings.
- Do not add a separate branch database or concurrency authority without evidence that the
  immutable evaluation-record contract cannot satisfy the VP audit and resume requirements.
- Do not represent candidate fields as current runtime capability until their shared contract,
  consumers, and tests exist.

### Implemented VP baseline

- The executable Field and Content Branch snapshots support mutually exclusive motor, home, and
  contents families plus collision, participant, Police, pending-evidence, theft, safety,
  mitigation, professional-review, and human-support conditions.
- The deterministic evaluator produces versioned branch, field-selection, current-action
  requirement, tool/action permission, and interruption results from authoritative Claim State.
- Applied evaluations are persisted with form, confirmation, message, resume, evidence, handoff,
  consent, and integration mutations and drive claimant Dynamic Form projections.
- The Agent receives the bounded evaluation, may propose only registered fields and tools, and
  cannot declare readiness or mutate Claim State directly.
- Regression tests cover out-of-order facts, corrections, conflicts, pending evidence,
  non-repetition, three-family claim creation, and role-safe projections.

### Remaining target-runtime migration

- persist Registry versions and the version used by each claim;
- preserve branch, field, source, and selection-state history;
- persist TurnPlan, AgentProposal, ExecutionPlan, ActionEnvelope, ToolResult, and
  TurnResult history without merging their statuses;
- persist claim lifecycle state, follow-up task, retention, and Customer Memory versions
  with their source and expiry rules;
- validate snapshots before runtime activation; and
- run the same contract tests against every supported provider profile.

### Control Plane management

- provide editing and validation for fields, branches, tags, lifecycle states, follow-up,
  retention, and related rules;
- run scenario and regression evaluation before publication;
- require stronger approval for authority, visibility, safety, and high-impact rules;
- publish atomically and support observation, rollback, and audit; and
- keep secrets and provider credentials outside the Registry.

## Open Decisions

- Which additional candidate fields enter the executable registry after the VP baseline?
- What is the approved branch and tag catalogue?
- What is the minimum approved Action, Tool, Staff Capability, Model Profile, and Error
  catalogue for the MVP?
- Which rule conditions are sufficient for the first implementation?
- Which explicit claimant statements may become confirmed without another turn?
- Which production-authorised requirement sets replace or extend the VP claim-creation baseline?
- How are multi-product incidents and corrected claim-family classifications represented?
- Which Registry changes may be published through the Control Plane without a code or
  persistence migration?
- How are in-progress claims handled when a new Registry version is published?
- Which lifecycle, follow-up, and retention changes require stronger approval?
- Which Customer Memory categories are allowed, and what evidence is required before they
  can be stored?
- How long must legacy Agent Decisions remain readable, and when may the eight-action API
  mapping be removed?
