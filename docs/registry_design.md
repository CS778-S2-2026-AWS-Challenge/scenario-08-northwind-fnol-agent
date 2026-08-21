# Registry and Dynamic FNOL Form Design

## Purpose

This document describes how Northwind can implement a controlled Registry and a
claim-specific internal FNOL information form. It is a design document, not a claim
API contract and not evidence that the Registry or dynamic branch engine is already
implemented.

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
Branch Registry      -> which claim and condition branches may exist
Rule Set             -> when registered fields and branches become active
Action Requirements  -> what the current next action needs
Lifecycle Registry   -> which claim states and transitions may exist
Follow-up and Retention Policies -> when work is followed up or removed
Claim State          -> facts, sources, statuses, branches, and unresolved work
Form Projection      -> what the Agent asks, shows, or can safely skip now
```

The Registry is not simply another database table. It is a versioned, validated
catalogue of allowed fields, branches, tags, and rules. A database may persist the
catalogue, but storage is an implementation detail. The important boundary is that
runtime code and model output can use only published definitions.

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

### Branch Registry

The Branch Registry defines the approved paths and dimensions that may be activated for
a claim:

| Branch type | Examples | Purpose |
| --- | --- | --- |
| Interruption | urgent safety, repeated human request, accessibility support | Pause ordinary collection and preserve progress |
| Claim family | motor, home, contents, unknown | Select the relevant product or incident field group |
| Incident condition | another party, witness, Police involvement, theft, conflicting evidence | Add a supported conditional group |
| Evidence state | available, missing, incomplete, unofficial, pending generation | Describe responsibility and timing without blocking unrelated work |
| Professional authority | coverage ambiguity, material conflict, review signal | Request staff attention without making the decision automatically |
| Next action | continue intake, register evidence, hand off, create claim, route | Determine the minimum information needed now |

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

### Rules and Action Requirements

Rules should be declarative and limited to a finite set of condition operators such as
`exists`, `equals`, `in`, `all`, `any`, and `not`. Configuration must not execute
arbitrary Python, JavaScript, or model-generated code.

Rules determine which registered fields, tags, and sub-branches become active. Action
requirements determine the minimum information needed for a safe current action. They
must not turn the entire field catalogue into a mandatory questionnaire.

The model may propose a classification or value, but deterministic validation controls
activation, authority, visibility, and side effects.

### Claim Lifecycle Registry

The claim lifecycle is a finite state machine, not a collection of unrelated booleans.
The Registry should define the allowed states, transition reasons, responsible party,
next-action shape, and staff visibility for each state. A starting set is:

```text
not_started
draft_saved
awaiting_customer
awaiting_external_material
ready_for_next_step
staff_review
submitted
expired
purged
```

`awaiting_customer`, `awaiting_external_material`, explicit customer withdrawal, and
timeout expiry must remain distinguishable. A session with no credible claim intent may
remain `non_claim_intent` without creating a claim at all.

Lifecycle definitions should also identify whether the state is resumable, whether it is
staff-visible, who owns the next action, and what event can move it forward. Status fields
such as `saved`, `active`, and `abandoned` may be derived for filtering, but they must not
be the competing source of truth.

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
-> claim-family branch proposal
-> approved rule activates registered fields and tags
-> conditional sub-branches activate when supported
-> current action identifies required-now and candidate fields
-> Agent asks one useful question or progresses the next safe action
-> Claim State changes cause the active form to be recalculated
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
3. propose `incident.type = motor` from supported wording;
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

Changing wording or candidate priority is not automatically a schema change, but it
still requires Agent Policy evaluation and publication. Making a field required for
claim creation, urgent handling, or another high-impact action is a controlled business
rule and requires Northwind authority.

## Progressive Implementation

### Stage 1: Static controlled catalogue

- define and validate a small published field and branch snapshot;
- support motor, unknown, urgent, and human-support paths;
- implement several conditional branches such as another party, injury, and pending
  evidence;
- replace the current fixed four-field sequence with controlled selection; and
- test irrelevant-question avoidance, required-now selection, and safe handoff.

### Stage 2: Versioned runtime snapshot

- persist Registry versions and the version used by each claim;
- preserve branch, field, source, and selection-state history;
- persist claim lifecycle state, follow-up task, retention, and Customer Memory versions
  with their source and expiry rules;
- validate snapshots before runtime activation; and
- run the same contract tests against every supported provider profile.

### Stage 3: Control Plane management

- provide editing and validation for fields, branches, tags, lifecycle states, follow-up,
  retention, and related rules;
- run scenario and regression evaluation before publication;
- require stronger approval for authority, visibility, safety, and high-impact rules;
- publish atomically and support observation, rollback, and audit; and
- keep secrets and provider credentials outside the Registry.

## Open Decisions

- Which candidate fields enter the MVP registry for motor, home, and contents claims?
- What is the approved branch and tag catalogue?
- Which rule conditions are sufficient for the first implementation?
- Which explicit claimant statements may become confirmed without another turn?
- What is the minimum field set for each safe next action and claim-creation route?
- How are multi-product incidents and corrected claim-family classifications represented?
- Which Registry changes may be published through the Control Plane without a code or
  persistence migration?
- How are in-progress claims handled when a new Registry version is published?
- Which lifecycle, follow-up, and retention changes require stronger approval?
- Which Customer Memory categories are allowed, and what evidence is required before they
  can be stored?
