# FNOL Information Model and Field Taxonomy

## Status and Authority

This document is the field-level logical model that complements
[Data Architecture](data-architecture.md). It defines the information that may arise
during FNOL, how that information is classified, and how a controlled branch selects a
dynamic subset for one claim.

The model is derived from the
[FNOL As-Is Process and Reporting Fields research](research/fnol-as-is-process-and-reporting-fields.md).
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
-> multiple explicit facts and bounded classification proposals
-> safety and support interruption checks
-> content-branch candidates, such as motor, collision, or another party
-> approved rule activates registered field groups and tags
-> conditional sub-branches activate when supported by claim facts
-> current-action requirements identify required-now and candidate fields
-> TurnPlan combines any useful response, form patches, lookups, and next step
-> Runtime applies only validated and authorised effects
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

The current implementation recognises these 19 form field codes:

| Group | Registered fields |
| --- | --- |
| Policy and claimant | `policy.policy_number`, `claimant.client_number`, `claimant.role`, `claimant.contact_preference` |
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

Lifecycle and operational fields such as claim status, next action, responsible party,
WorkItems, follow-up due time, expiry, and purge status belong to Claim State and workflow
records.
They are not automatically claimant-facing FNOL fields and must not be confused with
the dynamic information collected from the claimant.

## VP Field Directory

This directory is the complete information inventory for the three Sprint 3 Validation
Prototype paths. It is deliberately broader than the current runtime registry so that
branch design can distinguish a known product requirement from an implemented field.
It is not a promise that every row is currently collectable or required for claim creation.

The status values used below are:

| Status | Meaning |
| --- | --- |
| `registered` | The field code is accepted by the current backend field registry and may be used by the current bounded runtime path. |
| `candidate` | The information belongs in the VP directory, but its field code or consumer contract is not yet registered. It requires a later shared-contract change before runtime use. |
| `record` | The information is owned by a separate Claim State, Evidence, Handoff, consent, or integration record rather than a Dynamic Form field. |
| `system-owned` | The service, authenticated identity, provider, workflow, or staff supplies it; it must not be collected as an ordinary claimant question. |

`Common` means that the information may be relevant to all three paths. It does not mean
that the field is globally mandatory. `Conditional` means that an incident, participant,
safety, authority, evidence, or support fact must activate it first.

### Common FNOL fields

These fields form the shared baseline from which each path-specific branch starts.

| Field code | Meaning | Class | Status | Source and confirmation boundary |
| --- | --- | --- | --- | --- |
| `claimant.client_number` | Authenticated customer reference | Common, system-owned | `registered` | Authenticated identity; never ask the claimant to re-enter it when available |
| `claimant.role` | Relationship of reporter to the policyholder or incident | Common | `registered` | Claimant statement or authenticated context; confirm when authority is material |
| `claimant.contact_preference` | Preferred contact channel | Common | `registered` | Claimant choice; explicit consent may be required for a channel |
| `policy.policy_number` | Policy reference supplied for lookup | Common | `registered` | Claimant or policy lookup; provider result remains source-linked |
| `policy.product` | Product or claim-family product match | Common, system/provider-owned | `candidate` | Structured policy lookup or controlled classification; do not infer coverage from the label |
| `incident.type` | Broad incident family or type | Common | `registered` | Claimant statement or bounded classification proposal; material ambiguity requires clarification |
| `incident.occurred_at` | Date and time of loss or occurrence | Common | `registered` | Claimant statement, evidence, or system-normalised time; preserve uncertainty |
| `incident.location` | Place where the incident occurred | Common | `registered` | Claimant statement; confirm only when ambiguity affects routing or safety |
| `incident.description` | Claimant's natural account of what happened | Common | `registered` | Always retain original message provenance; never replace it with a model summary |
| `incident.cause` | Initial stated or proposed cause | Common | `registered` | Claimant statement or proposed interpretation; do not turn a hypothesis into a conclusion |
| `incident.injury_or_danger` | Injury, continuing danger, or immediate safety concern | Common, conditional | `registered` | Explicit claimant statement; safety interruption takes precedence over ordinary intake |
| `loss.description` | What was damaged, lost, stolen, or otherwise affected | Common | `registered` | Claimant statement; may contain several items or areas in one message |
| `parties.other_parties` | Whether another person, vehicle, or organisation is involved | Common, conditional | `registered` | Claimant statement; detailed party data belongs to a later approved structure |
| `authorities.emergency_services_notified` | Whether emergency services were contacted | Common, conditional | `registered` | Claimant statement or verified service result; never claim contact without confirmation |
| `declaration.factual_declaration` | Claimant declaration that the supplied account is accurate to the best of their knowledge | Common, customer decision | `candidate` | Explicit claimant action; not implied by confirming an individual field |
| `consent.sharing_scope` | Data and purpose approved for an external participant | Common, customer decision | `candidate` | Explicit consent record; scope must name the permitted fields and recipient |
| `claim.next_action` | Current safe next step and responsible party | Common, system-owned | `record` | Derived from Claim State and WorkItems; not an ordinary claimant form field |
| `claim.lifecycle_state` | Draft, waiting, handoff, ready-to-create, created, or other lifecycle state | Common, system-owned | `record` | Authoritative Claim State; Dynamic Form must not redefine it |
| `evidence.summary` | Aggregate evidence availability and outstanding materials | Common, system-owned | `record` | Evidence records and WorkItems; individual files are not embedded in the form |

### Motor path field set

The motor path includes the common baseline plus vehicle, driver, road, participant,
authority, and mobility information. Rows marked `record` remain separate records even
when the motor branch makes them relevant.

| Field code | Meaning | Class | Status | Source and confirmation boundary |
| --- | --- | --- | --- | --- |
| `vehicle.registration` | Registration or plate identifier | Motor | `registered` | Claimant statement or policy/vehicle lookup; confirm before an external request |
| `vehicle.make` | Vehicle manufacturer | Motor | `candidate` | Claimant statement or authorised lookup |
| `vehicle.model` | Vehicle model | Motor | `candidate` | Claimant statement or authorised lookup |
| `vehicle.year` | Vehicle model year | Motor | `candidate` | Claimant statement or authorised lookup |
| `vehicle.use` | Personal, business, commuting, or other use | Motor | `candidate` | Claimant statement; do not infer policy use from the incident description |
| `vehicle.damage_description` | Visible damage to the insured vehicle | Motor | `registered` | Claimant statement, image proposal, or staff observation; image extraction remains proposed |
| `vehicle.drivable` | Whether the vehicle can be safely driven | Motor | `registered` | Claimant statement; safety-sensitive ambiguity requires clarification |
| `vehicle.towing_location` | Location to which the vehicle was or should be towed | Motor, conditional | `candidate` | Claimant or verified towing result; only activate when towing is needed |
| `driver.identity` | Driver identity | Motor, conditional | `candidate` | Claimant or authorised record; subject to privacy and authority checks |
| `driver.contact` | Driver contact details | Motor, conditional | `candidate` | Claimant or authorised record; collect only for an active participant need |
| `driver.policy_relationship` | Driver relationship to the policyholder | Motor, conditional | `candidate` | Claimant statement or policy lookup; material uncertainty may require review |
| `driver.licence_status` | Bounded licence status relevant to the report | Motor, conditional | `candidate` | Claimant or authorised staff; not a coverage or liability decision |
| `other_vehicle.description` | Other vehicle make, model, registration, or damage summary | Motor, conditional | `candidate` | Claimant statement or evidence; detailed third-party data requires a shared contract |
| `other_party.contact` | Contact details for another involved party | Motor, conditional | `candidate` | Claimant statement; claimant consent and privacy scope apply |
| `witness.exists` | Whether a witness exists | Motor, conditional | `candidate` | Claimant statement |
| `witness.contact` | Witness contact details | Motor, conditional | `candidate` | Claimant statement; collect only when needed for the next action |
| `road.direction_of_travel` | Direction or lane context | Motor, conditional | `candidate` | Claimant statement; do not infer from a map or image without a governed source |
| `road.condition` | Road surface or traffic condition | Motor, conditional | `candidate` | Claimant statement or cited evidence |
| `weather.condition` | Weather or visibility condition | Motor, conditional | `candidate` | Claimant statement or cited evidence |
| `authorities.police_report_status` | Whether Police reporting is not started, pending, supplied, or unavailable | Motor, conditional | `candidate` | Claimant statement or authority result; status is not proof of liability |
| `authorities.police_report_reference` | Police file or report reference | Motor, conditional | `registered` | Claimant or verified Police result; pending generation remains explicit |
| `authorities.emergency_services_notified` | Emergency service notification status | Motor, conditional | `registered` | Shared field; only active when safety facts require it |
| `motor.repairer_preference` | Preferred repairer or repair route | Motor, conditional | `candidate` | Claimant choice or staff decision; does not itself authorise a referral |

### Home path field set

The home path includes the common baseline plus property, occupancy, habitability,
mitigation, and affected-area information.

| Field code | Meaning | Class | Status | Source and confirmation boundary |
| --- | --- | --- | --- | --- |
| `property.address` | Address of the affected property | Home | `registered` | Claimant statement or authorised policy lookup |
| `property.affected_areas` | Rooms, structures, or areas affected | Home | `registered` | Claimant statement; retain multiple areas without collapsing them |
| `property.occupancy_status` | Whether the property is occupied, vacant, or partly occupied | Home, conditional | `candidate` | Claimant statement; activate when safety or mitigation depends on occupancy |
| `property.habitability_status` | Whether the property remains safely habitable | Home, conditional | `candidate` | Claimant statement; safety ambiguity takes precedence over ordinary intake |
| `property.damage_description` | Description of building or fixture damage | Home | `candidate` | Claimant statement, image proposal, or staff observation |
| `property.cause_source` | Water, fire, weather, impact, or other initial cause source | Home | `candidate` | Claimant statement or cited service result; no coverage conclusion |
| `property.emergency_repair_needed` | Whether urgent mitigation or repair is needed | Home, conditional | `candidate` | Claimant statement or staff assessment; may create a WorkItem |
| `property.utilities_status` | Whether electricity, water, gas, or another utility is affected | Home, conditional | `candidate` | Claimant statement; collect only when relevant to safety or mitigation |
| `property.temporary_accommodation_needed` | Whether temporary accommodation is needed | Home, conditional | `candidate` | Claimant statement; creates a follow-up or professional-work item, not an automatic entitlement |
| `property.owner_or_tenant` | Occupancy or ownership relationship | Home, conditional | `candidate` | Claimant statement or policy record; use only for an authorised purpose |
| `home.mitigation_actions_taken` | Safe actions already taken to reduce further loss | Home, conditional | `candidate` | Claimant statement; never request unsafe action |
| `home.contractor_contact` | Contractor or emergency repair contact | Home, conditional | `candidate` | Claimant statement or staff record; external sharing requires consent |
| `home.weather_event` | Weather event associated with the loss | Home, conditional | `candidate` | Claimant statement or cited knowledge/service result |

### Contents path field set

The contents path includes the common baseline plus item, ownership, valuation,
purchase-evidence, and theft/discovery information. Item evidence remains an Evidence
record and is not reduced to a free-text form field.

| Field code | Meaning | Class | Status | Source and confirmation boundary |
| --- | --- | --- | --- | --- |
| `contents.item_description` | Description of each affected item | Contents | `candidate` | Claimant statement; support multiple items and preserve item grouping |
| `contents.item_category` | Category such as electronics, furniture, clothing, or jewellery | Contents | `candidate` | Claimant statement or controlled classification proposal |
| `contents.item_quantity` | Number of affected items | Contents | `candidate` | Claimant statement; do not infer quantity from a singular phrase |
| `contents.item_brand` | Brand or manufacturer | Contents | `candidate` | Claimant statement or evidence proposal |
| `contents.item_model` | Model or product identifier | Contents | `candidate` | Claimant statement or evidence proposal |
| `contents.item_serial_number` | Serial or unique item identifier | Contents, conditional | `candidate` | Claimant statement or evidence; collect only when useful for identification |
| `contents.purchase_date` | Approximate purchase date | Contents | `candidate` | Claimant statement or receipt; preserve approximate dates |
| `contents.purchase_source` | Retailer or source of purchase | Contents, conditional | `candidate` | Claimant statement or receipt |
| `contents.ownership_status` | Ownership or responsibility for the item | Contents | `candidate` | Claimant statement or policy record; material conflict requires review |
| `contents.estimated_value` | Initial claimant estimate of value | Contents | `candidate` | Claimant statement; an estimate is not an approved settlement value |
| `contents.replacement_needed` | Whether replacement is requested or relevant | Contents, conditional | `candidate` | Claimant choice; does not authorise payment or coverage |
| `contents.receipt_available` | Whether purchase evidence is available | Contents, conditional | `candidate` | Claimant statement; absence should create pending evidence, not erase the item |
| `contents.proof_of_ownership` | Available ownership evidence references | Contents, conditional | `record` | Evidence metadata and protected objects; claimant sees only safe status |
| `contents.discovery_at` | When loss, theft, or damage was discovered | Contents, conditional | `candidate` | Claimant statement; distinguish occurrence time when unknown |
| `contents.entry_or_theft_context` | Bounded description of entry, theft, or loss context | Contents, conditional | `candidate` | Claimant statement; Police and fraud decisions remain outside the field |
| `contents.police_report_status` | Police report state for theft or burglary | Contents, conditional | `candidate` | Claimant statement or authority result |
| `contents.police_report_reference` | Police reference for theft or burglary | Contents, conditional | `candidate` | Claimant or verified Police result; pending generation remains explicit |

### Cross-path conditional records

These records can attach to any path when the facts activate them. They are listed here
to prevent each path from inventing a separate representation.

| Record or field | Activation signal | Owner | Status | Boundary |
| --- | --- | --- | --- | --- |
| `evidence.items[]` | Image, document, receipt, Police report, estimate, or other material is supplied or expected | Evidence subsystem | `record` | Preserve metadata, provenance, lifecycle, protected object reference, and extraction proposals separately |
| `evidence.pending_generation` | A document is expected but has not yet been generated | Evidence subsystem | `record` | Create a pending WorkItem; do not block unrelated safe work |
| `handoff.request` | Human-support, urgency, accessibility, or professional-review condition | Handoff subsystem | `record` | Transfer confirmed facts, sources, gaps, responsibility, and requested action |
| `review.signal` | Material conflict, coverage ambiguity, or other approved review trigger | Review subsystem | `record` | Internal-only proposal; never expose fraud or risk conclusions to the claimant |
| `external.consent` | A third-party request needs claimant-approved sharing | Integration subsystem | `record` | Store purpose, recipient, permitted fields, actor, and lifecycle |
| `external.request` | A repairer, assessor, Police, or other participant request is prepared | Integration subsystem | `record` | Track preparation, authority, submission, result, verification, reconciliation, and failure |
| `follow_up.task` | A later customer, staff, or external action is required | Workflow subsystem | `record` | Record responsible party, due time, attempts, and outcome; do not make it a form field |

## Common Fields and Branch Differences

The directory produces the following branch structure:

| Layer | Common to all three paths | Motor additions | Home additions | Contents additions |
| --- | --- | --- | --- | --- |
| Identity and policy | Claimant role/contact, policy reference, product match | — | — | — |
| Incident | Type, occurrence time, location, natural description, initial cause, safety signal | Road/vehicle context | Property/occupancy context | Item/loss context |
| Loss | Loss description, other-party signal, emergency-service status | Vehicle damage and drivability | Building damage, affected areas, habitability and mitigation | Item catalogue, ownership, value and purchase evidence |
| Conditional authority | Police, witness, injury, evidence, consent, handoff, review and external records | Police/driver/other vehicle branches | Emergency repair/utility/accommodation branches | Theft/discovery/Police branches |
| Operational records | Claim lifecycle, next action, evidence summary, handoff, WorkItems and integrations | Same shared records | Same shared records | Same shared records |

The shared baseline must be collected or reused before path-specific questioning, but only
the current action's required fields become `required_now`. A motor claim must not ask
home-only questions, and a contents claim must not ask vehicle-only questions, unless a
supported multi-branch incident activates the additional dimension.

## VP Branch Decision Matrix

The following matrix is the first executable design target for #384. It defines what a
published rule may activate; it does not claim that the current runtime already evaluates
all rows.

| Branch | Trigger evidence | Activate fields/records | Exit or correction | Required-now guidance |
| --- | --- | --- | --- | --- |
| `family.motor` | Claimant describes a vehicle or road incident, or an authorised lookup identifies motor context | Motor registered fields plus motor candidate set; activate `vehicle.*` and relevant participant/evidence records | Explicit correction to home/contents or a conflicting authoritative lookup suspends motor candidates while preserving source history | Ask only fields needed for safe mobility, claim preparation, or the current requested action |
| `family.home` | Claimant describes damage to a building, home, fixture, or property area | Home registered fields plus home candidate set; activate `property.*` and mitigation records as supported | Explicit correction to motor/contents or conflicting authoritative lookup suspends home candidates | Ask location, affected area, safety/habitability, or mitigation fields only when they unblock the next safe action |
| `family.contents` | Claimant describes lost, stolen, or damaged belongings or individual items | Contents candidate set plus item evidence records; activate theft/Police branch only when supported | Explicit correction to home/motor or conflicting authoritative lookup suspends contents candidates without deleting item facts | Ask item identity, quantity, ownership, or evidence only when needed for the current action |
| `incident.collision` | Impact, crash, rear-end, or collision wording | `incident.type`, parties, vehicle/road fields, possible Police/evidence branches | Correction to non-collision cause exits collision branch and recalculates candidates | Do not ask road or other-party detail unless it affects the current action |
| `participant.other_party` | Another person, vehicle, property owner, or organisation is mentioned | Other-party and consent records; motor may add `other_vehicle.*` | Claimant says no other party or corrects the account | Ask only contact or identity needed for an authorised next step |
| `authority.police` | Police report, theft, burglary, authority attendance, or pending report is mentioned | Police status/reference and evidence WorkItem | Police involvement is corrected or evidence is verified as not applicable | Pending Police generation remains a later WorkItem and does not block unrelated safe progress |
| `safety.injury_or_danger` | Explicit injury, continuing danger, or emergency condition | Safety field, urgent handoff, emergency-service record, and bounded response | Safety signal is corrected by claimant or authorised staff; preserve the original statement and decision history | Interrupt ordinary questions; do not wait for the complete form |
| `evidence.pending` | Required or expected material is missing, incomplete, unofficial, or not yet generated | Evidence record and pending WorkItem | Evidence arrives, is rejected, or is no longer needed | Mark responsibility and next step; do not make unrelated fields mandatory |
| `support.human` | Human-support request, repeated request, distress, or accessibility need | Handoff record and claimant-safe status; preserve current form and messages | Staff resolves/cancels handoff or claimant withdraws request | Apply the configured first-request rule; repeated/urgent/accessibility requests transfer immediately |
| `review.professional` | Material conflict, coverage ambiguity, or approved review signal | Internal review record and structured handoff packet | Staff records a decision or resolves the conflict | Do not convert the signal into a claimant-visible conclusion |

Branch activation is additive: one claim may be `family.motor + incident.collision +
participant.other_party + authority.police + evidence.pending` at the same time. A later
correction recalculates the active form and candidate questions, but does not erase the
original account, source references, evidence history, or staff decisions.

## Content Branch Model

### Content-branch dimensions

The decision structure is a graph rather than one irreversible questionnaire path:

| Dimension | Examples | Behaviour |
| --- | --- | --- |
| Claim family | motor, home, contents, unknown | Activates the relevant predefined field group and collection rules |
| Incident type | collision, theft, fire, water, weather, accidental damage | Adds applicable incident facts, evidence needs, and question candidates |
| Participant | another party, witness, Police, repairer, assessor | Adds only supported participant and coordination information |
| Safety and support | injury, continuing danger, distress, accessibility | Supplies an interruption signal and changes support behaviour without becoming a workflow state |
| Evidence state | available, missing, incomplete, unofficial, pending generation | Changes evidence responsibility without silently making unrelated fields mandatory |
| Professional authority | coverage ambiguity, material conflict, review signal | Creates a bounded staff request and does not turn the signal into a decision |

A claim may have a primary family branch and several simultaneous conditional branches.
For example, a motor incident may also involve injury, another party, damaged property,
pending Police evidence, and a professional-review need. One label must not erase another
dimension.

Content branches do not include `draft`, `waiting`, `review`, `ready_to_create`, or
`created`. Those belong to the Claim lifecycle. Current work and blockers are represented
by lifecycle and independent WorkItems, not by adding another content branch.

### Content-branch activation

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
- The model records only a branch candidate, supporting facts, source references, and
  uncertainty. The rule engine controls `proposed`, `active`, `suspended`, and
  `exited/corrected` status.

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

The Agent and orchestration layer choose the next useful interaction from active fields
and WorkItems by:

1. handling an explicit safety or support interruption first;
2. reusing authenticated, retrieved, confirmed, or clearly claimant-supplied information;
3. excluding inactive, system-owned, already confirmed, and later-stage fields;
4. identifying missing fields required for the current next action;
5. resolving one material ambiguity or conflict when it blocks selection;
6. combining an answer, explanation, lookup, or several supported fact proposals in the
   same turn when useful;
7. asking one focused question with the highest current value only when an answer is
   needed; and
8. progressing without further questions when the next action is safe.

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

A form-patch proposal records the field code, proposed value and status, source type and
references, confidence state where applicable, confirmation need, and intended operation
such as add or correct. Runtime validates each patch independently. One invalid patch
does not make the model's remaining text authoritative, and one valid patch does not
authorise unrelated proposed side effects.

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
- Resume also reloads lifecycle and WorkItems. Changing lifecycle or completing a
  WorkItem may change the current purpose and permitted tools, but it does not rewrite
  incident facts or content branches.

## Contract Change Boundary

Adding a field code, changing its type or visibility, changing stored status semantics,
or exposing it through claimant or staff APIs is a shared contract change. It requires
the field model, API contract, domain validation, persistence mapping, claimant and staff
projections, fixtures, and tests to change together.

Changing a question's wording or candidate priority is not automatically a schema change,
but it still follows Agent Policy publication and evaluation. Making a field required for
claim creation, urgent handling, or another high-impact action is a controlled business
rule and requires Northwind authority.

Adding lifecycle states, follow-up fields, retention fields, or Customer Memory fields
is a separate data and persistence contract change; it does not turn those fields into
ordinary claimant questions.

## Open Decisions

- Which candidate fields enter the MVP registry for motor, home, and contents claims.
- The approved branch and tag catalogue and the representation of rule conditions.
- Which explicit claimant statements may become confirmed without a separate confirmation
  turn.
- Northwind's minimum fields for each safe next action and claim-creation route.
- How multi-product incidents and corrected claim-family classifications are represented.
- Which field-definition and collection-policy changes may be published through the
  Control Plane without a code and schema migration.
