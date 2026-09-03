# FNOL Information Model and Field Taxonomy

## Scope and authority

This design defines the Sprint 3 Validation Prototype information space for representative
`motor`, `home`, and `contents` FNOL paths. It is not a production insurance form, policy
decision, provider schema, or implementation claim. `SPEC/`, `docs/api.md`,
`docs/persistence-schema.md`, and published registry versions remain authoritative. A
listed field is not automatically mandatory.

The catalogue separates Claim Context fields from Evidence, WorkItem, Handoff, Review,
Consent, and Integration records. Branches are independent content dimensions, not
claim-lifecycle states, work statuses, or risk conclusions.

## Status and notation

| Term | Meaning |
| --- | --- |
| `required_now` | Missing value blocks the current safe action under a published rule. |
| `candidate_now` | Relevant but not a current blocker. |
| `pending_later` | Relevant to a later action or unavailable evidence. |
| `inactive` | Unsupported by current facts or active branches. |
| `system_owned` | Supplied by identity, lookup, workflow, integration, staff, or audit. |
| `registered` | Present in the current backend registry/API subset. |
| `candidate` | VP design field needing a later contract decision. |
| `record` | Separate durable record, not a Dynamic Form field. |

Table shorthand: `src` = claimant (`C`), staff (`S`), provider (`P`), evidence (`E`),
workflow (`W`), or system (`Y`); `NL` = natural-language extraction; `conf` = claimant
confirmation; `infer` = model may propose only; `safe` = affects current safe action;
`now` = may become required now; `vis` = claimant/staff visibility; `auth` = consent,
privacy, authority, or professional review.

The `safe/now/status` tuple contains three independent dimensions: whether the field can
affect a safe action, whether it can be selected as `required_now` for a particular claim,
and its catalogue/implementation status (`registered`, `candidate`, `record`, or
`system-owned`). Runtime fact status (`proposed`, `confirmed`, `disputed`, `missing`, or
`pending_generation`) must be stored separately. Applicability is explicit in the index
below; `common` means stable meaning across all three paths, while `conditional` means the
field is applicable only after a branch trigger.

## Field categories

| Category | Meaning | Collection rule |
| --- | --- | --- |
| Core FNOL | Information commonly relevant to initial notification | Consider for every path, but collect only when missing and needed for the current safe action |
| Conditional | Information relevant only when an incident or support fact activates it | Keep inactive until a supported condition activates it |
| Path-specific | Information associated with motor, home, or contents | Activate only for the applicable family branch |
| System-generated | Information produced by identity, workflow, integration, staff, or audit | Never ask the claimant to manufacture it |
| Separate record | Evidence, Handoff, WorkItem, Review, Consent, or Integration data | Keep in its own lifecycle and persistence boundary; do not flatten it into an unbounded form field |
| Later-stage | Information normally produced during assessment, settlement, or payment | Keep outside the current FNOL collection unless a later contract explicitly introduces it |

`Core FNOL` is not a global mandatory flag. A common field may remain unknown while an
urgent handoff, evidence registration, support transfer, or another safe action proceeds.

## Logical field model

The claimant starts with a natural account, not a pre-expanded questionnaire. The service
builds a claim-specific projection by combining the common field baseline, active family
branches, conditional branches, current WorkItems, and the next safe action:

```text
natural claimant account
-> explicit facts and bounded classification proposals
-> safety and support interruption checks
-> family and conditional branch candidates
-> published rules activate registered fields and records
-> required-now and candidate-now selection
-> Agent response, form patch, lookup, or handoff proposal
-> runtime validation and authorised state effects
-> recalculation after material facts, correction, evidence, resume, or handoff
```

The model may propose a family, branch, field value, or tag, but it cannot invent a field
code, mandatory condition, private tag, high-impact outcome, or provider-specific schema.
The Dynamic Form is a projection of Claim State, not a second copy of the claim and not a
fixed questionnaire.

## Explicit applicability index

| Applicability | Field codes |
| --- | --- |
| `common` | `claimant.role`, `claimant.client_number`, `claimant.contact_preference`, `policy.policy_number`, `claim.product_family`, `incident.type`, `incident.description`, `incident.occurred_at`, `incident.location`, `incident.cause`, `loss.description`, `incident.injury_or_danger`, `parties.other_parties`, `evidence.availability`, `declaration.factual_accuracy`, `consent.sharing_scope`, `report.channel`, `claim.created_at`, `claim.registry_version` |
| `motor` | `vehicle.identity`, `vehicle.registration`, `vehicle.make`, `vehicle.model`, `vehicle.year`, `vehicle.use`, `vehicle.damage_description`, `vehicle.drivable`, `vehicle.towing_required`, `vehicle.towing_location`, `driver.identity`, `driver.relationship`, `driver.licence_status`, `collision.occurred`, `collision.impact_area`, `collision.movement`, `other_vehicle.identity`, `other_party.contact`, `witness.details`, `road.conditions`, `weather.visibility`, `authority.police_status`, `authority.police_reference`, `repairer.details`, `motor.evidence_refs` |
| `home` | `property.address`, `property.occupancy_relationship`, `property.occupancy`, `property.affected_areas`, `property.building_damage`, `property.fixture_damage`, `property.cause_source`, `property.severity`, `property.ongoing_risk`, `property.habitable`, `property.utilities`, `mitigation.emergency_action`, `mitigation.temporary_repair`, `mitigation.contractor`, `accommodation.required`, `accommodation.details`, `weather.event`, `home.evidence_refs` |
| `contents` | `contents.items`, `contents.item.description`, `contents.item.category`, `contents.item.quantity`, `contents.item.brand`, `contents.item.model`, `contents.item.serial_number`, `contents.item.ownership`, `contents.item.purchase_date`, `contents.item.purchase_source`, `contents.item.estimated_value`, `contents.item.replacement_need`, `contents.item.loss_type`, `contents.discovery_at`, `theft.entry_context`, `contents.receipt_availability`, `contents.proof_of_ownership`, `contents.police_status`, `contents.police_reference`, `contents.item.evidence_refs`, `contents.item_group` |
| `conditional cross-path` | `incident.discovered_at`, `parties.other_parties`, `evidence.availability`, `declaration.factual_accuracy`, `consent.sharing_scope`, `collision.*`, `other_party.*`, `witness.*`, `authority.police_*`, `safety/injury`, `mitigation.*`, `accommodation.*`, `incident.theft_or_burglary`, `professional_review`, `human_support` |

`common` and `conditional cross-path` may both apply: common describes reusable meaning;
conditional describes collection-time branch activation. A record code is an explicit
reference/aggregate identity and must not be implemented as an unbounded form string.

## Complete common field inventory

The common set is derived by meaning across all three paths, not by unioning existing
registrations. Evidence, consent, workflow, and registry metadata are shown here only to
make their boundary explicit.

| Code | Meaning | Applies/type/multi | src/NL/conf/infer | safe/now/status | Current implementation | vis/auth |
| --- | --- | --- | --- | --- | --- | --- |
| `claimant.role` | Reporter relationship to policyholder | common/enum/no | C/y/y/y | n/c/registered | Registry + form | C/S; privacy |
| `claimant.client_number` | Authenticated customer reference | common/scalar/no | Y/n/n/n | n/n/registered | Registry; identity supplies value | S; privacy |
| `claimant.contact_preference` | Preferred safe contact channel | common/enum/no | C/y/y/y | support/c/registered | Registry/profile | C/S; privacy |
| `policy.policy_number` | Policy reference | common/scalar/no | C,P/y/y/y | lookup/c/registered | Registry; bounded lookup | C/S; privacy |
| `claim.product_family` | Motor, home, or contents family | common/enum/no | C,Y/y/y/y | routing/y/registered | Registry + form; top-level `incident_type` remains the compatibility projection | C/S; authority |
| `incident.type` | Collision, fire, water, theft, weather, etc. | common/enum/no | C/y/y/y | safety/y/registered | Registry + form | C/S; review if disputed |
| `incident.description` | Natural account of what happened | common/scalar/no | C/y/n/y | y/c/registered | Registry + form | C/S; privacy |
| `incident.occurred_at` | Loss occurrence date/time | common/date-time/no | C/y/y/y | safety/c/registered | Registry + form | C/S; privacy |
| `incident.discovered_at` | Discovery time, especially theft | conditional/date-time/no | C/y/y/y | safety/c/candidate | No field/schema | C/S; privacy |
| `incident.location` | Incident place or useful region | common/location/no | C/y/y/y | safety/y/registered | Registry + form | C/S; privacy |
| `incident.cause` | Initial cause, not coverage conclusion | common/scalar/no | C,E/y/y/y | safety/c/registered | Registry; evidence proposal gap | C/S; review if conflict |
| `loss.description` | Damaged, lost, or stolen subject | common/scalar/no | C,E/y/y/y | y/c/registered | Registry + form | C/S; privacy |
| `incident.injury_or_danger` | Bounded injury/continuing danger signal | common/boolean/no | C/y/y/y | urgent/y/registered | Registry + interruption rules | C/S; safety |
| `parties.other_parties` | Whether another person or organisation is involved | conditional/boolean/no | C/y/y/y | handoff/c/registered | Participant details remain a separate record | C/S; consent/privacy |
| `evidence.availability` | Available, missing, incomplete, pending | common/enum/no | C,E,W/y/y/y | next action/y/candidate | Evidence projection, not form | C/S; privacy |
| `declaration.factual_accuracy` | Claimant factual declaration | common/enum/no | C/y/y/y | authority/y/candidate | No declaration contract | C/S; authority |
| `consent.sharing_scope` | Purpose and fields allowed to share | conditional/structured/no | C/y/y/y | external/y/record | Consent record exists | C/S; consent/privacy |
| `report.channel` | Entry channel | common/enum/no | Y/n/n/n | n/n/system-owned | Claim State | S; audit |
| `claim.created_at` | System receipt time | common/date-time/no | Y/n/n/n | n/n/system-owned | Claim State | S; audit |
| `claim.registry_version` | Registry snapshot used | common/scalar/no | Y/n/n/n | n/n/record | Persisted as separate Field Registry and branch-rule coordinates on Branch Evaluation records, not as a claimant form field | S; audit |

## Motor field inventory

| Code | Meaning | Type/multi | src/NL/conf/infer | safe/now/status | Current implementation / needed boundary | vis/auth |
| --- | --- | --- | --- | --- | --- | --- |
| `vehicle.identity` | Insured vehicle identity/reference | object/no | C,P/y/y/y | routing/c/candidate | New registry/domain/API/persistence | C/S; privacy |
| `vehicle.registration` | Registration/plate | scalar/no | C,E/y/y/y | provider/c/registered | Registered; validation/masking alignment | C/S; privacy |
| `vehicle.make` | Make | scalar/no | C,E/y/y/y | n/c/candidate | New registry/domain/API/fixtures | C/S; privacy |
| `vehicle.model` | Model | scalar/no | C,E/y/y/y | n/c/candidate | New registry/domain/API/fixtures | C/S; privacy |
| `vehicle.year` | Model year | scalar/no | C,E/y/y/y | n/c/candidate | New registry/domain/API/fixtures | C/S; privacy |
| `vehicle.use` | Personal/business/commuting use | enum/no | C/y/y/y | routing/c/candidate | New bounded enum | C/S; policy/privacy |
| `vehicle.damage_description` | Visible damage account | scalar/no | C,E/y/y/y | safety/y/registered | Registered; evidence link separate | C/S; privacy |
| `vehicle.drivable` | Whether the vehicle is safe and able to be driven | boolean/no | C/y/y/y | safety/y/registered | Registered; towing rule gap | C/S; safety |
| `vehicle.towing_required` | Need for towing | enum/no | C,S/y/y/y | safety/y/candidate | Registry + WorkItem rule | C/S; consent |
| `vehicle.towing_location` | Safe tow destination/current location | location/no | C/y/y/y | safety/c/candidate | Registry/API; provider task separate | C/S; privacy/consent |
| `driver.identity` | Driver identity/reference | object/no | C,S/y/y/y | authority/c/candidate | Restricted object + visibility | S; privacy/authority |
| `driver.relationship` | Driver relationship to policyholder | enum/no | C/y/y/y | authority/c/candidate | Registry/domain/API | C/S; authority |
| `driver.licence_status` | Bounded licence signal | enum/no | C,E/y/y/y | review/pending/candidate | Restricted field + review boundary | S; privacy/review |
| `collision.occurred` | Collision branch fact | enum/no | C/y/y/y | routing/y/candidate | Branch registry, not lifecycle | C/S; privacy |
| `collision.impact_area` | Front/rear/side/other impact | enum/list/yes | C,E/y/y/y | evidence/c/candidate | Registry/list validation | C/S; privacy |
| `collision.movement` | Direction/manoeuvre at impact | object/no | C/y/y/y | review/c/candidate | Domain object; no liability inference | S; review |
| `other_vehicle.identity` | Other vehicle reference/details | object/yes | C,E/y/y/y | provider/pending/candidate | Participant structure + consent | S; privacy/consent |
| `other_party.contact` | Other party contact | object/no | C/y/y/y | external/pending/candidate | Consent-scoped participant record | S; privacy/consent |
| `witness.details` | Witness existence/contact | object/yes | C/y/y/y | evidence/pending/candidate | Participant record + consent | S; privacy/consent |
| `road.conditions` | Surface, intersection, controls | object/no | C,E/y/y/y | review/c/candidate | Registry/domain/API | S; review |
| `weather.visibility` | Weather, lighting, visibility | object/no | C,E/y/y/y | safety/c/candidate | Registry/domain/API | S; privacy |
| `authority.police_status` | Police contacted/required/pending | enum/no | C,S/y/y/y | authority/y/candidate | Branch + authority record | C/S; authority |
| `authority.police_reference` | Police file/reference | scalar/no | C,E/y/y/y | authority/c/registered | Bounded reference only | C/S; privacy/authority |
| `repairer.details` | Repairer and quote status | object/no | C,S,P/y/y/y | external/pending/candidate | Integration/WorkItem record | S; consent |
| `motor.evidence_refs` | Vehicle photo/video/estimate refs | list/yes | E,C/y/y/y | evidence/y/record | Evidence API + item links | C/S; privacy |

## Home field inventory

| Code | Meaning | Type/multi | src/NL/conf/infer | safe/now/status | Current implementation / needed boundary | vis/auth |
| --- | --- | --- | --- | --- | --- | --- |
| `property.address` | Insured property address | location/no | C,P/y/y/y | routing/y/registered | Registry + form | C/S; privacy |
| `property.occupancy_relationship` | Owner, tenant, landlord, other | enum/no | C/y/y/y | authority/c/candidate | Registry/domain/API | C/S; privacy |
| `property.occupancy` | Occupied, vacant, partial | enum/no | C/y/y/y | safety/c/candidate | Registry/domain/API | C/S; safety |
| `property.affected_areas` | Rooms, structures, outdoor areas | list/yes | C,E/y/y/y | triage/y/registered | Registered; branch shape gap | C/S; privacy |
| `property.building_damage` | Structural/building damage | scalar/no | C,E/y/y/y | safety/y/candidate | Registry/domain/API | C/S; safety/review |
| `property.fixture_damage` | Fixtures and built-ins | list/yes | C,E/y/y/y | safety/c/candidate | Registry/domain/API | C/S; privacy |
| `property.cause_source` | Water, fire, weather, impact source | enum/scalar/no | C,E/y/y/y | safety/y/candidate | Registry; no coverage inference | C/S; safety |
| `property.severity` | Bounded extent/severity | enum/no | C,E/y/y/y | safety/c/candidate | Deterministic rules required | C/S; review |
| `property.ongoing_risk` | Leak, fire, collapse, exposure | enum/no | C/y/y/y | urgent/y/candidate | Emergency branch | C/S; safety |
| `property.habitable` | Safe/usable to occupy | enum/no | C,S/y/y/y | support/y/candidate | Restricted field + review | C/S; safety/review |
| `property.utilities` | Power, gas, water, communications | object/no | C/y/y/y | safety/c/candidate | Structured value | C/S; safety |
| `mitigation.emergency_action` | Emergency/mitigation taken | list/yes | C,S,E/y/y/y | safety/y/record | WorkItem/evidence + projection | C/S; consent |
| `mitigation.temporary_repair` | Temporary repair details | object/yes | C,S,E/y/y/y | safety/pending/record | WorkItem/Integration record | S; consent |
| `mitigation.contractor` | Contractor identity/work status | object/yes | C,S,P/y/y/y | external/pending/record | Provider/task record | S; consent |
| `accommodation.required` | Temporary accommodation need | enum/no | C,S/y/y/y | support/y/candidate | Branch + WorkItem | C/S; privacy/consent |
| `accommodation.details` | Location/occupants/duration | object/no | C/y/y/y | support/pending/candidate | Restricted field/projection | C/S; privacy |
| `weather.event` | Storm, flood, earthquake, etc. | enum/no | C,E/y/y/y | routing/c/candidate | Branch + evidence link | C/S; safety |
| `home.evidence_refs` | Property photos/invoices/reports | list/yes | E,C/y/y/y | evidence/y/record | Evidence API + area links | C/S; privacy |

## Contents field inventory

Contents is intentionally explicit: the current registry has almost no contents-specific
coverage. Repeated item facts belong to item records, not a flat claim form.

| Code | Meaning | Type/multi | src/NL/conf/infer | safe/now/status | Current implementation / needed boundary | vis/auth |
| --- | --- | --- | --- | --- | --- | --- |
| `contents.items` | Affected item collection | record/yes | C,E/y/y/y | evidence/y/record | New `ContentsItem` API/domain/persistence | C/S; privacy |
| `contents.item.description` | Item description | scalar/no | C,E/y/y/y | evidence/y/candidate | Item schema/projection | C/S; privacy |
| `contents.item.category` | Item category | enum/no | C,E/y/y/y | routing/c/candidate | Bounded enum registry | C/S; privacy |
| `contents.item.quantity` | Count of similar items | scalar/no | C/y/y/y | evidence/c/candidate | Validation + grouping | C/S; privacy |
| `contents.item.brand` | Brand | scalar/no | C,E/y/y/y | n/c/candidate | Item schema | C/S; privacy |
| `contents.item.model` | Model/style | scalar/no | C,E/y/y/y | n/c/candidate | Item schema | C/S; privacy |
| `contents.item.serial_number` | Serial/unique identifier | scalar/no | C,E/y/y/y | evidence/pending/candidate | Masked restricted field | S; privacy |
| `contents.item.ownership` | Owned, leased, borrowed, gifted | enum/no | C,E/y/y/y | authority/c/candidate | Enum + authority rule | C/S; privacy |
| `contents.item.purchase_date` | Approximate/exact purchase date | date-time/no | C,E/y/y/y | evidence/pending/candidate | Item schema | C/S; privacy |
| `contents.item.purchase_source` | Retailer, private sale, gift | enum/scalar/no | C,E/y/y/y | evidence/pending/candidate | Bounded values | C/S; privacy |
| `contents.item.estimated_value` | Claimant estimate, not settlement value | scalar/no | C,E/y/y/y | evidence/c/candidate | Money type + review boundary | C/S; review |
| `contents.item.replacement_need` | Replace, repair, substitute | enum/no | C/y/y/y | next action/c/candidate | Item rule + WorkItem | C/S; privacy |
| `contents.item.loss_type` | Damaged, lost, stolen, destroyed | enum/no | C,E/y/y/y | routing/y/candidate | Enum + theft branch | C/S; authority |
| `contents.discovery_at` | When loss was discovered | date-time/no | C/y/y/y | safety/c/candidate | Registry/domain field | C/S; privacy |
| `theft.entry_context` | Forced entry/access/unknown | enum/scalar/no | C,E/y/y/y | authority/y/candidate | Restricted theft branch | C/S; authority/privacy |
| `contents.receipt_availability` | Receipt/invoice status | enum/no | C,E/y/y/y | evidence/y/candidate | Evidence projection | C/S; privacy |
| `contents.proof_of_ownership` | Ownership evidence references | list/yes | E,C/y/y/y | evidence/c/record | Item/evidence mapping | C/S; privacy |
| `contents.police_status` | Police status for theft/burglary | enum/no | C,S/y/y/y | authority/y/candidate | Authority record + branch | C/S; authority |
| `contents.police_reference` | Police file/reference | scalar/no | C,E/y/y/y | authority/pending/candidate | Reuse bounded reference | C/S; privacy/authority |
| `contents.item.evidence_refs` | Item photos/receipts/valuations | list/yes | E,C/y/y/y | evidence/y/record | Immutable item links | C/S; privacy |
| `contents.item_group` | Similar-item grouping/provenance | record/yes | C,E,Y/y/y/y | evidence/c/record | Group record + provenance | S; privacy |

## Conditional branch matrix

| Branch | Trigger | Activates / promotes | Exit/correction | Visibility/lifecycle | Separate record |
| --- | --- | --- | --- | --- | --- |
| `incident.collision` | Impact described | Collision fields; safety/location may be required | Suspend on correction; retain source/revision | C sees questions; S sees history; no lifecycle change alone | Review if material conflict |
| `participant.another_party` | Other person/vehicle mentioned | Participant candidate; consent before sharing | Withdrawal exits sharing; preserve prior fact | C sees scope; S sees restricted detail | Consent + participant/integration |
| `participant.witness` | Witness exists | Witness/evidence pending | Mark unavailable; never invent contact | S detail unless consent | Participant + Evidence |
| `authority.police` | Police called/required/reference | Status now; reference/document later | Correct with audit/history | C status; S reference | Authority + WorkItem |
| `safety.injury_or_danger` | Injury/danger wording | Immediate safe action; normal fields stay candidate | Clear only from new authoritative fact | Both see safe step | Handoff/WorkItem; may interrupt |
| `evidence.pending` | Missing/incomplete material | Evidence WorkItems | Upload/verification resolves | C request/status; S provenance | Evidence + WorkItem |
| `mitigation.emergency` | Active leak/fire/exposure | Emergency/mitigation fields | Verified resolution; retain actions | Both safe instruction; S detail | WorkItem/Handoff |
| `accommodation.temporary` | Home uninhabitable | Accommodation required for support | Habitability correction exits | C support status; S details | WorkItem/Handoff |
| `incident.theft_or_burglary` | Stolen item/forced entry | Discovery, entry, Police, ownership evidence | Reclassify only with source | C status; S authority evidence | Authority + Evidence + Review |
| `professional_review` | Material ambiguity/conflict | Review reason/source refs | Staff decision is immutable | C safe explanation; S full signal | Review; possibly Handoff |
| `human_support` | Distress/accessibility/request | Support preference and handoff context | Authorised resolution/cancellation | C owner/status; S packet | Handoff + WorkItem |

Branches may coexist, e.g. `family.motor + incident.collision + participant.another_party +
authority.police + evidence.pending`. Runtime rules, not the model, control activation,
correction, and exit.

## VP branch rules v1

The matrix above describes the business meaning of each branch. This section gives the
first rule-set shape that an implementation can evaluate. It is intentionally a bounded
VP baseline, not a Northwind production policy. The rule-set identifier is
`vp-dynamic-form-branch-rules-v1`; a published registry snapshot must carry its identifier
and version whenever a claim is evaluated.

### Rule inputs and outputs

The branch evaluator receives only provider-neutral, authorised inputs:

| Input | Use |
| --- | --- |
| Accepted Claim facts and their source references | Determine whether a trigger is explicit, confirmed, inferred, corrected, or conflicting |
| Current proposed facts | Permit a branch candidate without treating a model interpretation as confirmed |
| Current registered field and branch catalogue | Reject unknown codes and prevent a rule from activating an unregistered field |
| Current action and open WorkItems | Decide whether an active field can be `required_now` or remains a candidate/pending item |
| Safety, support, evidence, authority, and consent records | Activate interruption or conditional branches without copying those records into the form |
| Registry and policy version | Keep an evaluation reproducible and prevent a stale rule from changing a newer claim |

The evaluator returns a deterministic result containing:

- active, suspended, exited, and candidate branches with rule IDs and source references;
- the registered fields each branch adds or removes from the active projection;
- selection state for each relevant field (`required_now`, `candidate_now`, `pending_later`,
  `inactive`, or `system_owned`);
- WorkItem, Handoff, Evidence, Review, Consent, or Integration records to create or update;
- the primary runtime control signal, if a safety or support interruption applies; and
- a recomputation reason and the Claim revision against which the result was calculated.

The result is a proposal for Runtime execution. It is not a direct model instruction and it
does not itself mutate Claim State.

### Evaluation order

Rules are evaluated in this order, while branch activation remains additive:

1. **Safety interruption:** explicit injury, continuing danger, or emergency conditions are
   evaluated first. They may interrupt ordinary collection and create an urgent handoff.
2. **Support interruption:** repeated human requests, distress, or accessibility needs are
   evaluated next. A first ordinary request follows the configured/versioned rule.
3. **Family classification:** activate at most the supported family candidates for `motor`,
   `home`, and `contents`; an unresolved conflict keeps the candidates proposed and uses
   shared fields only.
4. **Incident and participant dimensions:** collision, theft/burglary, another party,
   witness, Police, and other conditional branches are evaluated independently.
5. **Evidence and mitigation:** pending evidence, emergency mitigation, towing, repair, and
   temporary accommodation create their own records and do not turn every related field into
   a blocker.
6. **Professional review:** material ambiguity or conflict creates an internal review record
   and may pause a high-impact action without exposing the internal signal to the claimant.
7. **Field selection:** only after active branches and WorkItems are known are fields promoted
   to `required_now`, `candidate_now`, or `pending_later` for the current action.

The first two steps select the primary Runtime control directive. The later steps may still
add useful fact proposals, evidence records, or questions without overriding that directive.

### Rule catalogue

| Rule ID | Condition | Activation result | Exit/correction | Current-action effect |
| --- | --- | --- | --- | --- |
| `BR-FAMILY-MOTOR-001` | Explicit vehicle/road/driver wording, a supported collision description, or an authorised lookup identifies motor context | Activate `family.motor`; add the motor field set and retain the common baseline | A clear claimant correction or conflicting authoritative lookup suspends motor-only candidates and preserves their source history | Only mobility, routing, or current-action fields can become `required_now` |
| `BR-FAMILY-HOME-001` | Explicit building, property, room, fixture, or home-damage wording, or an authorised lookup identifies home context | Activate `family.home`; add the home field set and retain the common baseline | A clear correction or authoritative conflict suspends home-only candidates without deleting facts | Only location, safety, habitability, mitigation, or current-action fields can become `required_now` |
| `BR-FAMILY-CONTENTS-001` | Explicit item, belongings, theft, loss, or contents wording, or an authorised lookup identifies contents context | Activate `family.contents`; add the contents item set and item/evidence records | A clear correction or authoritative conflict suspends contents candidates while retaining item facts and provenance | Only item identity, evidence, authority, or current-action fields can become `required_now` |
| `BR-COLLISION-001` | Impact, crash, rear-end, or collision is explicitly described | Activate `incident.collision`; add collision, participant, road, and possible Police/evidence candidates | Correction to a non-collision incident exits the branch and recalculates candidates | Do not require movement, road, or other-party details unless they block the current safe action |
| `BR-PARTICIPANT-OTHER-001` | Another person, vehicle, property owner, or organisation is mentioned | Activate `participant.another_party`; add participant candidates and a consent check before disclosure | A correction or consent withdrawal exits sharing while retaining the original statement | Contact or identity is `required_now` only for an authorised next action |
| `BR-PARTICIPANT-WITNESS-001` | A witness is mentioned or requested for the next action | Activate `participant.witness`; create a participant/evidence work item | Mark unavailable when the claimant cannot provide details; never invent contact data | Witness details normally remain `candidate_now` or `pending_later` |
| `BR-AUTHORITY-POLICE-001` | Police contact, a Police report, theft/burglary, or pending Police generation is mentioned | Activate `authority.police`; track status/reference and an evidence WorkItem | Correction or verified inapplicability exits the branch with audit history | A missing report remains `pending_later` unless a current authorised action explicitly requires it |
| `BR-SAFETY-001` | Explicit injury, continuing danger, or an emergency condition is present | Activate `safety.injury_or_danger`; create urgent handoff/WorkItem and bounded safe response | Clear only from a new authoritative fact; preserve the original safety statement | Interrupt ordinary questions; do not wait for the complete form |
| `BR-EVIDENCE-PENDING-001` | Expected material is missing, incomplete, unofficial, or not yet generated | Activate `evidence.pending`; create or update an evidence WorkItem with responsibility | Supplied evidence can resolve the item; rejection keeps the limitation explicit | Do not block unrelated safe progress or erase accepted facts |
| `BR-MITIGATION-001` | Active leak, fire, exposure, unsafe property, towing, or emergency repair is described | Activate the relevant mitigation branch and record safe actions separately | Verified resolution closes the WorkItem but retains action history | Ask only the minimum safety or mitigation information needed now |
| `BR-ACCOMMODATION-001` | A home is not safely habitable or temporary accommodation is requested | Activate `accommodation.temporary`; create a support WorkItem | Habitability correction or staff resolution exits the branch | Accommodation details remain support/workflow data unless needed for the current action |
| `BR-THEFT-001` | Stolen item, forced entry, burglary, or unknown disappearance is described | Activate theft/discovery, ownership-evidence, and possible Police branches | Reclassification requires a source-backed correction; preserve prior item facts | Discovery, entry context, and Police status may become current candidates; no fraud conclusion is inferred |
| `BR-REVIEW-001` | Material conflict, coverage ambiguity, or another approved review trigger exists | Create an internal Review record and, where necessary, a professional handoff | Staff records an immutable decision or resolves the conflict | Do not expose the internal signal as a claimant conclusion |
| `BR-HUMAN-SUPPORT-001` | Repeated human request, distress, accessibility need, or configured first-request condition | Create or reuse a Handoff and preserve the structured packet | Staff resolution/cancellation ends the active support branch | Claimant sees safe status and responsibility; staff receives context and requested action |

### Field-state promotion

After branch evaluation, the rule engine applies this order to each active registered field:

| Condition | Selection state |
| --- | --- |
| Field is supplied by authenticated identity, workflow, provider, integration, staff, or audit | `system_owned` |
| Field is not supported by an active branch | `inactive` |
| Field is relevant only to a later action or unavailable evidence | `pending_later` |
| Field is relevant but missing does not block the current safe action | `candidate_now` |
| Field is missing and a published rule says the current safe action cannot proceed without it | `required_now` |

Stored fact status remains separate from selection state. A `required_now` field may still be
`proposed`, `missing`, or `disputed`; it is not silently confirmed merely because the rule
engine selected it for the next question.

### Runtime integration boundary

The Agent does not fetch or execute this Markdown directly. The intended integration is:

```text
published Branch/Field Registry snapshot
        ↓
provider-neutral BranchRuleEvaluator
        ↓
active branches + field selection + WorkItems + interruption result
        ↓
bounded Claim Context supplied to Agent Runtime
        ↓
Agent proposes conversation moves, form patches, lookups, or handoff actions
        ↓
Runtime validates the proposal and applies authorised effects
```

In the target architecture, the evaluator reads a versioned Field/Content Branch Registry
through the configuration or registry port. It does not call a model, database, or provider
directly. The Agent receives the evaluated active branches, allowed registered fields,
current selection states, relevant WorkItems, and permitted actions as bounded context. The
Agent may suggest a branch candidate or field patch, but the evaluator and Runtime remain the
authority for activation, `required_now`, Claim State mutation, visibility, and side effects.

For the VP implementation, the same boundary may initially be backed by a checked-in,
versioned rule definition or a local registry adapter. That is an implementation choice; the
contract must remain replaceable so a later Control Plane publication can provide the active
snapshot without changing Agent code.

## Required-now selection rules

1. Handle injury, danger, distress, accessibility, and explicit support requests first.
2. Reuse authenticated, confirmed, retrieved, and prior source-backed facts.
3. Activate only supported branches; keep unrelated fields inactive.
4. Mark `required_now` only when a published rule says it blocks the current safe action.
5. Keep ambiguity candidate until a focused clarification or staff review is justified.
6. Keep Evidence, Consent, Handoff, Provider, and Review records in their own state machines.
7. Recalculate after facts, corrections, evidence, handoff, or resume.

## Field value, source, and confirmation

The same value has different authority depending on its source:

| Source | Treatment |
| --- | --- |
| Explicit claimant statement | Record the original wording and claimant provenance; ask again only when ambiguity, conflict, declaration, or consequence makes confirmation necessary |
| Authenticated identity or structured lookup | Reuse within its permitted purpose; do not ask the claimant to recreate system-owned information |
| Model interpretation | Keep proposed when material; retain the source message and require the applicable confirmation or review |
| Evidence extraction | Keep proposed with evidence provenance until the required claimant or staff decision |
| Provider result | Preserve typed source, version, and limitations; never convert it directly into a coverage, liability, fraud, or approval conclusion |
| Staff or workflow result | Record actor, authority, reason, and source references; expose only the role-appropriate projection |

Runtime validates every field patch independently. One valid patch does not authorise an
unrelated side effect, and one invalid patch must not be repaired by parsing model prose.

## Handoff, resume, and correction

- Resume recalculates active branches from the latest authoritative Claim State rather than
  replaying a fixed questionnaire or copying stale session state.
- Confirmed fields, source history, unresolved work, evidence state, and prior commitments
  survive resume and branch correction.
- A branch correction suspends or exits no-longer-supported candidates without deleting the
  original account, source references, evidence history, or staff decisions.
- A structured handoff packet contains confirmed facts, source references, active gaps,
  evidence, branches, responsibility, prior commitments, and the requested staff action.
- Complete messages remain available under authorised staff access, while the packet uses
  relevant message references so a professional can understand the claim without reading
  the complete transcript first.

## Contract change boundary

Adding a field code, changing its type or visibility, changing stored status semantics, or
exposing it through claimant or staff APIs is a shared contract change. It requires the
field model, API contract, domain validation, persistence mapping, claimant and staff
projections, fixtures, and tests to change together.

Changing question wording or candidate priority is not automatically a schema change, but
it still follows Agent Policy publication and evaluation. Making a field required for claim
creation, urgent handling, external disclosure, or another high-impact action is a
controlled business rule and requires the applicable Northwind authority.

Lifecycle states, WorkItems, Evidence, Handoff, Review, Consent, and Integration records
remain separate data contracts. They must not be represented as ordinary claimant fields
merely to make a Dynamic Form table appear complete.

## Implementation gap table

| Area | Current backend | Current API | Current persistence | Needed consumer | Owner candidate |
| --- | --- | --- | --- | --- | --- |
| Common subset | 19 registry codes; bounded form | Partial claim/form schemas | Generic `WorkingClaim.form` | Agent, claimant, staff | `liyang6620`; backend owner |
| Motor extensions | Registration/damage/drivable only | No complete motor schema | Generic form | Dynamic Form, Agent, staff | `liyang6620` + Agent owner |
| Home extensions | Address/areas only | No complete home schema | Generic form | Dynamic Form, claimant, staff | `liyang6620` + backend owner |
| Contents extensions | Dedicated fields absent | No item API | No item/group mapping | Dynamic Form, evidence, staff | `liyang6620` + backend owner |
| Branch registry | Concepts documented, runtime incomplete | No branch endpoint | Branch history incomplete | Agent/runtime/projections | Agent owner + `liyang6620` |
| Required-now projection | Partial current-action logic | No complete selection response | Selection history absent | Agent, Dynamic Form, UI | Agent + backend owners |
| Item/evidence provenance | Evidence API exists | Item links absent | New immutable mapping | Evidence, claimant, staff | `bdfa123` + `liyang6620` |
| Consent/declaration | External consent exists; declaration absent | Route-specific only | Consent record; catalogue scopes absent | Agent/integrations/UI | `liyang6620` + backend owner |
| Registry versioning | Constant exists | No publication API | Claim version not retained | Agent/audit/staff | `liyang6620` + Control Plane owner |

## API/domain/persistence/projection impact

- Add shared field definitions, branch/selection states, typed contents item objects, and
  role-safe projections together; never create route-private enums.
- A persistence change must update access patterns, `docs/persistence-schema.md`, protocols,
  adapters, revisions, ownership checks, fixtures, and contract tests.
- Evidence keeps object reference, checksum, source, version, visibility, and item/area
  provenance; original bytes never enter `WorkingClaim.form`.
- Agent/Dynamic Form consumes a published registry snapshot and deterministic rules. Model
  output remains a proposal; runtime validates and applies it.
- Claimant sees friendly labels, current questions, safe next step, consent scope, and
  evidence status. Staff sees structured facts, sources, corrections, pending work,
  restricted review signals, and handoff context.

## Open decisions

1. Approve initial fields and enum values for each family.
2. Confirm policy lookup and identity-match inputs without inventing provider schemas.
3. Approve minimum `required_now` sets for intake, emergency support, evidence, and routing.
4. Approve retention/visibility for participant, Police, licence, serial, and value data.
5. Decide whether contents uses one record per item, grouped records, or both with IDs.
6. Define publication/rollback behavior for in-progress claims.
7. Define professional-review thresholds and staff-authority decisions.

## Current implementation statement

The backend is a partial implementation, not a complete three-path schema. Contents
coverage is largely absent from the current registry. This document is a design input for
later field, branch, API, persistence, Dynamic Form, Agent, and projection work; no listed
candidate is implemented until its contract, tests, and role projections exist.
