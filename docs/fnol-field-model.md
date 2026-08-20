# FNOL Information Model and Field Taxonomy

## Status and Authority

This document is the field-level logical model that complements
[Data Architecture](data-architecture.md). It defines the information that may arise
during FNOL, how that information is classified, and how a controlled branch selects a
dynamic subset for one claim.

The model is derived from the
[FNOL As-Is Process and Reporting Fields research](User_Research_and_Pain_Points/FNOL_As-Is_Process_and_Reporting_Fields_Concise_Research_Report_EN.md).
Research provenance explains why a field group is considered; this document defines its
architectural position. Neither source is an approved Northwind production form.

A field appearing in this model does not mean that it is implemented, mandatory for
every claim, claimant-supplied, or required before the next safe action. Current API and
runtime support remains limited to the explicitly registered fields and separate domain
records identified below.

## Core Model

The claimant starts with a natural account, not a pre-expanded form. The system builds a
claim-specific information form by activating only predefined fields and tags through
controlled branch rules.

```text
natural claimant account
-> explicit facts and bounded classification proposals
-> safety and support interruption checks
-> claim-family branch proposal, such as motor, home, or contents
-> approved rule activates registered field groups and tags
-> conditional sub-branches activate when supported by claim facts
-> current-action requirements identify required-now and candidate fields
-> Agent asks one useful question or progresses the next safe action
-> the form and active branches are recalculated after every material change
```

The resulting form is dynamic because its active subset changes with the claim. Its
schema is controlled because every field, tag, branch, state, and rule reference must
already exist in an approved contract. A model cannot invent a field code, private tag,
branch, mandatory condition, or high-impact outcome.

## Field Categories

| Category | Meaning | Collection rule |
| --- | --- | --- |
| Core FNOL | Information commonly relevant to initial notification | Consider for most claims, but collect only when missing and needed for the current safe action |
| Conditional | Information relevant only when incident facts trigger it | Keep inactive until a supported condition activates it |
| Claim-Specific | Information associated with a product or incident family | Activate only for an applicable motor, home, contents, or later approved branch |
| System-Generated | Information produced by the service, insurer, or authorised staff | Never ask the claimant to manufacture it |
| Later-Stage | Information normally produced during assessment, settlement, or payment | Keep outside current FNOL collection unless a later product contract introduces it |

`Core FNOL` is not a global mandatory flag. A core field may remain unknown while an
urgent handoff, evidence registration, support transfer, or another safe action proceeds.

## Logical Field Model

| Information area | Examples | Classification | Current architectural position |
| --- | --- | --- | --- |
| Reporter and customer | identity, relationship to policyholder, phone, email, contact preference | Core FNOL | Partly represented; authenticated customer context should supply known identity rather than cause repeated questions |
| Policy | policy number, product, policyholder match, alternative identification | Core FNOL | Policy number is registered; product and customer matching belong behind structured policy lookup |
| Incident | type, natural account, initial cause, sequence | Core FNOL | Type, description, and cause are registered; only a bounded subset participates in current intake |
| Date and time | loss time, discovery time, report time | Core or Conditional | Occurrence time is registered; report time is system-generated; discovery time is a candidate concept |
| Location | incident place, road or intersection, property address | Core FNOL with claim-specific shape | Incident location and property address are registered; branch context selects the applicable representation |
| Damage and loss | damaged, lost, or stolen property, initial extent, continued usability | Core FNOL | General loss, vehicle damage, vehicle drivability, and property-area fields are partly registered |
| Safety and mitigation | injury or danger, emergency assistance, towing, temporary repair, loss mitigation | Conditional | Injury or danger and emergency-contact status are registered; other mitigation details remain candidates |
| Evidence | images, video, receipts, invoices, Police documents, estimates | Conditional | Owned by separate Evidence records and APIs, not embedded into form fields or messages |
| Vehicle | registration, year, make, model, use, drivability, towing location | Motor-specific | Registration, damage description, and drivability are registered; remaining concepts are candidates |
| Driver | identity, contact, insured relationship, permission, licence | Motor-specific | Candidate; no current registered field contract |
| Other party | identity, contact, vehicle, insurer, affected property or people | Conditional and often motor-specific | Represented only by a bounded current field; a detailed structure requires a shared contract change |
| Witness | existence, identity, phone, email | Conditional | Candidate; no current registered field contract |
| Police and authorities | reported status, file reference, station or officer, emergency response | Conditional | Police reference and emergency-contact status are registered; other concepts remain candidates |
| Injury | whether anyone is injured, bounded safety status, emergency response | Conditional | Current field records injury or danger without defining medical or identity detail |
| Road and weather | road condition, weather, lighting, direction of travel | Motor-specific | Candidate; no current registered field contract |
| Property and home | property address, affected areas, habitability, emergency repair, occupancy | Home-specific | Address and affected areas are registered; habitability, occupancy, and repair detail remain candidates |
| Contents and items | item description, brand, model, serial, purchase date, initial value, ownership evidence | Contents-specific | Candidate; evidence remains separate even when related to an item |
| Theft and burglary | discovery time, missing items, entry method, alarm, Police reference | Event-specific | Candidate except for reusable registered Police and loss fields |
| Declaration and consent | factual declaration, privacy acknowledgement, representative authority | Core or Conditional | Requires an explicit identity, consent, and declaration contract; not implied by ordinary field confirmation |
| Claim administration | received time, channel, claim number, status, assigned route | System-Generated | Owned by Claim State, workflow, integration results, and audit records rather than claimant form input |
| Assessment and settlement | final repair report, approved quote, liability, bank account, settlement method | Later-Stage | Outside the current FNOL product boundary and not an Agent decision authority |

## Current Registered Field Coverage

The current implementation recognises these 18 form field codes:

| Group | Registered fields |
| --- | --- |
| Policy and claimant | `policy.policy_number`, `claimant.role`, `claimant.contact_preference` |
| Incident | `incident.type`, `incident.occurred_at`, `incident.location`, `incident.description`, `incident.injury_or_danger`, `incident.cause` |
| Loss and parties | `loss.description`, `parties.other_parties` |
| Authorities | `authorities.police_report_reference`, `authorities.emergency_services_notified` |
| Motor | `vehicle.registration`, `vehicle.damage_description`, `vehicle.drivable` |
| Property | `property.address`, `property.affected_areas` |

The current controlled intake actively sequences only incident description, incident
location, loss description, and incident type. It does not yet implement the dynamic
branch and field-selection model defined here. This limitation must remain visible until
the registry, rules, orchestration, API, consumers, fixtures, and tests are updated
together.

## Dynamic Branch Model

### Branch types

The decision structure is a graph rather than one irreversible questionnaire path:

| Branch type | Examples | Behaviour |
| --- | --- | --- |
| Interruption | urgent safety, repeated human request, accessibility support | May interrupt any ordinary branch and preserve its progress |
| Claim family | motor, home, contents, unknown | Activates the relevant predefined field group and collection rules |
| Incident condition | another party, witness, Police involvement, theft, conflicting evidence | Adds only the applicable conditional fields, tags, evidence needs, and follow-up rules |
| Evidence state | available, missing, incomplete, unofficial, pending generation | Changes evidence responsibility without silently making unrelated fields mandatory |
| Professional authority | coverage ambiguity, material conflict, review signal | Creates a bounded staff request and does not turn the signal into a decision |
| Next action | continue intake, register evidence, hand off, create claim, route | Defines which active fields are required now and which may remain candidates |

A claim may have a primary family branch and several simultaneous conditional branches.
For example, a motor incident may also involve injury, another party, damaged property,
pending Police evidence, and a professional-review need. One label must not erase another
dimension.

### Branch activation

- Explicit claimant facts may satisfy a condition directly when the statement is clear
  and the rule permits claimant-supplied confirmation.
- A model may propose a claim family, condition, field value, or tag from natural
  language. A proposal remains bounded by source, status, and confirmation policy.
- Versioned deterministic rules decide which registered fields, tags, and sub-branches
  become active. Model confidence alone cannot create a field, make it mandatory, or
  authorise a high-impact action.
- Ambiguous classification activates clarification or safe shared fields rather than
  silently committing the claim to an incompatible branch.
- A branch correction recalculates applicable work. It preserves prior values and source
  history instead of deleting facts merely because they are no longer active questions.

### Field selection states

For the current claim and action, a predefined field can be treated as:

| Selection state | Meaning |
| --- | --- |
| Required now | Missing information blocks the current safe action under an approved rule |
| Candidate now | Relevant information may improve the current step but does not justify unnecessary claimant effort |
| Pending later | Relevant to a known later action or unavailable evidence, but not a current blocker |
| Inactive | Not supported by the active claim and condition branches |
| System-owned | Supplied by identity, provider lookup, workflow, integration, staff, or audit rather than a claimant question |

These are selection states, not replacements for the stored field states such as
`proposed`, `confirmed`, `disputed`, `missing`, or `pending_generation`.

### Question selection

The Agent and orchestration layer choose the next question from active fields by:

1. handling an explicit safety or support interruption first;
2. reusing authenticated, retrieved, confirmed, or clearly claimant-supplied information;
3. excluding inactive, system-owned, already confirmed, and later-stage fields;
4. identifying missing fields required for the current next action;
5. resolving one material ambiguity or conflict when it blocks selection;
6. asking one focused question with the highest current value; and
7. progressing without further questions when the next action is safe.

The system must not interpret the field taxonomy as a reason to complete every possible
field in one interaction.

## Motor Branch Example

Given a claimant statement such as a rear-end collision description:

1. the natural account is stored with its source;
2. explicit injury, danger, human-support, and accessibility signals are evaluated;
3. `incident.type = motor` may be proposed from supported wording;
4. the approved motor rule activates existing motor fields such as registration, damage
   description, and drivability;
5. another-party, Police, evidence, towing, or property sub-branches activate only when
   supported;
6. fields already explicit in the claimant's account are not mechanically asked again;
7. only missing fields required for the current safe action become mandatory now; and
8. the next action is recalculated after every accepted fact, correction, evidence state,
   or handoff.

If the incident is later corrected to home or contents, the system changes active
branches without rewriting the claimant's original account or deleting traceable facts.

## Field Value, Source, and Confirmation

The same information value has different authority depending on its source:

| Source mode | Expected treatment |
| --- | --- |
| Explicit claimant statement | Record as claimant-supplied; ask again only when ambiguity, conflict, declaration, or consequence makes confirmation necessary |
| Model interpretation | Keep proposed when the interpretation is material; retain the source message |
| Evidence extraction | Keep proposed with evidence provenance until the required claimant or staff decision |
| Structured provider result | Preserve typed source and limitations; do not convert it into a high-impact conclusion |
| System or staff result | Record actor and authority; expose only the role-appropriate projection |

The internal form may translate natural language into professional field structure, but
it must not change meaning or make the claimant review every low-impact internal field.

## Tags and Review Signals

Dynamic branches may activate registered processing tags or propose review signals, but
tags remain separate from form facts:

- a tag or signal requires a predefined code, source, purpose, visibility, lifecycle,
  and rule reference;
- internal-only tags never enter claimant projections;
- a claim-family or workflow tag may support selection without becoming coverage,
  liability, fraud, approval, or rejection authority;
- evidence-linked review signals remain proposals for professional attention; and
- changing a branch cannot silently erase a staff decision or audit history.

The approved tag catalogue and executable rule representation remain open implementation
decisions and are not defined by this document.

## Handoff and Resume

- Resume recalculates active branches from the latest authoritative Claim State rather
  than replaying a fixed questionnaire or copying stale session state.
- Confirmed fields, source history, unresolved work, evidence state, and prior commitments
  survive resume and branch correction.
- A structured handoff packet contains confirmed facts, source references, active gaps,
  evidence, branches, responsibility, prior commitments, and the requested staff action.
- Complete messages remain available under staff access, while the packet uses relevant
  message references so a professional is not forced to read the complete transcript
  before understanding the claim.

## Contract Change Boundary

Adding a field code, changing its type or visibility, changing stored status semantics,
or exposing it through claimant or staff APIs is a shared contract change. It requires
the field model, API contract, domain validation, persistence mapping, claimant and staff
projections, fixtures, and tests to change together.

Changing a question's wording or candidate priority is not automatically a schema change,
but it still follows Agent Policy publication and evaluation. Making a field required for
claim creation, urgent handling, or another high-impact action is a controlled business
rule and requires Northwind authority.

## Open Decisions

- Which candidate fields enter the MVP registry for motor, home, and contents claims.
- The approved branch and tag catalogue and the representation of rule conditions.
- Which explicit claimant statements may become confirmed without a separate confirmation
  turn.
- Northwind's minimum fields for each safe next action and claim-creation route.
- How multi-product incidents and corrected claim-family classifications are represented.
- Which field-definition and collection-policy changes may be published through the
  Control Plane without a code and schema migration.
