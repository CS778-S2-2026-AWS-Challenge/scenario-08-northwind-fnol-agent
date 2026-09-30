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
| `unregistered` | Approved catalogue field absent from the executable registry and typed records. |
| `record` | Separate durable record, not a Dynamic Form field. |
| `alias` | Catalogue-only name mapped to a canonical executable code; never submit or register it. |

### Current implementation reconciliation

The executable source of truth currently contains 28 registered Dynamic Form field codes.
This catalogue also names concepts that deliberately live in typed records or branch
evaluations. Reconciliation against the commercial first notice of loss (FNOL) research and
the current backend produces three distinct groups:

- 9 are already covered by an equivalent canonical structure: Evidence availability,
  agreement acceptance, vehicle Asset identity/make/model/year, collision branch evaluation,
  the canonical incident discovery field, and receipt Evidence state. They must not be
  duplicated in the Dynamic Form registry.
- The 24 commercially necessary fields approved by #1082 are now implemented in the backend registry and Claim contracts. They cover Policyholder identity and
  reporter relationship; the insured vehicle's Driver; vehicle use and towing; other-party
  insurance; Witness presence and contact; Police reporting status; and Home occupancy. Their
  exact storage boundaries appear in the inventories below.
- Earlier unregistered candidates for collision geometry, road/weather detail, repairer detail,
  separate building/fixture damage, property severity/utilities, accommodation detail, weather
  event, contents serial/purchase data, replacement need, and a duplicate contents Police status
  are outside this narrowed FNOL scope. Existing narrative, safety, Evidence, WorkItem, or
  registered Police fields remain authoritative for those concerns.

`authority.police_reference` is a catalogue label; the executable registry code is
`authorities.police_report_reference`. `contents.discovery_at` is not a second field; contents
uses the registered canonical code `incident.discovered_at`. These names are documented as
aliases only and must not be registered in parallel.

Table shorthand: `src` = claimant (`C`), staff (`S`), provider (`P`), evidence (`E`),
workflow (`W`), or system (`Y`); `NL` = natural-language extraction; `conf` = claimant
confirmation; `infer` = model may propose only; `safe` = affects current safe action;
`now` = may become required now; `vis` = claimant/staff visibility; `auth` = consent,
privacy, authority, or professional review.

The `safe/now/status` tuple contains three independent dimensions: whether the field can
affect a safe action, whether it can be selected as `required_now` for a particular claim,
and its catalogue/implementation status (`registered`, `unregistered`, `record`, `alias`, or
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
| `common` | `claimant.role`, `claimant.client_number`, `claimant.contact_preference`, `claimant.relationship_to_policyholder`, `policyholder.identity_ref`, `policyholder.name`, `policy.policy_number`, `claim.product_family`, `incident.type`, `incident.description`, `incident.occurred_at`, `incident.location`, `incident.cause`, `loss.description`, `incident.injury_or_danger`, `parties.other_parties`, `evidence.availability`, `declaration.factual_accuracy`, `consent.sharing_scope`, `report.channel`, `claim.created_at`, `claim.registry_version` |
| `motor` | `vehicle.identity`, `vehicle.registration`, `vehicle.make`, `vehicle.model`, `vehicle.year`, `vehicle.use`, `vehicle.damage_description`, `vehicle.drivable`, `vehicle.towing_required`, `vehicle.towing_location`, `driver.identity_ref`, `driver.name`, `driver.phone`, `driver.email`, `driver.relationship_to_policyholder`, `driver.owner_permission`, `driver.licence_number`, `driver.licence_status`, `collision.occurred`, `other_vehicle.identity`, `other_party.contact`, `other_party.insurer_name`, `other_party.policy_number`, `other_party.claim_reference`, `witness.present`, `witness.name`, `witness.phone`, `witness.email`, `authority.police_reference`, `motor.evidence_refs` |
| `home` | `property.address`, `property.occupancy_relationship`, `property.occupancy`, `property.affected_areas`, `property.ongoing_risk`, `property.habitable`, `mitigation.emergency_action`, `mitigation.temporary_repair`, `mitigation.contractor`, `home.evidence_refs` |
| `contents` | `contents.items`, `contents.item.description`, `contents.item.category`, `contents.item.quantity`, `contents.item.brand`, `contents.item.model`, `contents.item.ownership`, `contents.item.estimated_value`, `contents.item.loss_type`, `contents.discovery_at`, `theft.entry_context`, `contents.receipt_availability`, `contents.proof_of_ownership`, `contents.police_reference`, `contents.item.evidence_refs`, `contents.item_group` |
| `conditional cross-path` | `incident.discovered_at`, `parties.other_parties`, `evidence.availability`, `declaration.factual_accuracy`, `consent.sharing_scope`, `collision.*`, `other_party.*`, `witness.*`, `police.*`, `authority.police_*`, `safety/injury`, `mitigation.*`, `incident.theft_or_burglary`, `professional_review`, `human_support` |

`common` and `conditional cross-path` may both apply: common describes reusable meaning;
conditional describes collection-time branch activation. A record code is an explicit
reference/aggregate identity and must not be implemented as an unbounded form string.
The 24 newly registered fields describe capabilities the commercial intake must support, not a
universal creation checklist. A conditional value may remain unknown, unavailable, or pending
without blocking Claim creation unless a later published rule explicitly assigns a collection
deadline.

## Complete common field inventory

The common set is derived by meaning across all three paths, not by unioning existing
registrations. Evidence, consent, workflow, and registry metadata are shown here only to
make their boundary explicit.

| Code | Meaning | Applies/type/multi | src/NL/conf/infer | safe/now/status | Current implementation | vis/auth |
| --- | --- | --- | --- | --- | --- | --- |
| `claimant.role` | Reporter classification | common/scalar/no | C/y/y/y | n/c/registered | Registered as text; #1084 must bound the approved reporter roles without creating a duplicate field | C/S; privacy |
| `policyholder.identity_ref` | Account or Policyholder identity reference when the reporter is not the Policyholder | conditional/reference/no | C,P/y/y/n | authority/c/registered | Implemented as the Claim-scoped Policyholder record member | S; privacy/authority |
| `policyholder.name` | Policyholder name when no durable identity reference is available | conditional/scalar/no | C,P/y/y/n | authority/c/registered | Implemented as the Claim-scoped Policyholder record member | C/S; privacy/authority |
| `claimant.relationship_to_policyholder` | Reporter relationship to the Policyholder | conditional/enum/no | C/y/y/y | authority/c/registered | Implemented as a bounded Dynamic Form field | C/S; privacy/authority |
| `claimant.client_number` | Authenticated customer reference | common/scalar/no | Y/n/n/n | n/n/registered | Registry; identity supplies value | S; privacy |
| `claimant.contact_preference` | Preferred safe contact channel | common/enum/no | C/y/y/y | support/c/registered | Registry/profile | C/S; privacy |
| `policy.policy_number` | Policy reference | common/scalar/no | C,P/y/y/y | lookup/c/registered | Registry; bounded lookup | C/S; privacy |
| `claim.product_family` | Motor, home, or contents family | common/enum/no | C,Y/y/y/y | routing/y/registered | Registry + form; top-level `incident_type` remains the compatibility projection | C/S; authority |
| `incident.type` | Collision, fire, water, theft, weather, etc. | common/enum/no | C/y/y/y | safety/y/registered | Registry + form | C/S; review if disputed |
| `incident.description` | Natural account of what happened | common/scalar/no | C/y/n/y | y/c/registered | Registry + form | C/S; privacy |
| `incident.occurred_at` | Loss occurrence date/time without invented precision | common/temporal/no | C/y/y/y | safety/c/registered | Registry + form assertion history | C/S; exact, approximate, range, partial, unknown, timezone-aware |
| `incident.discovered_at` | Discovery time, especially theft | conditional/temporal/no | C/y/y/y | creation/c/registered | Theft branch; before creation | C/S; privacy |
| `incident.location` | Incident place or useful region | common/location/no | C/y/y/y | safety/y/registered | Registry + form | C/S; privacy |
| `incident.cause` | Initial cause, not coverage conclusion | common/scalar/no | C,E/y/y/y | safety/c/registered | Registry; evidence proposal gap | C/S; review if conflict |
| `loss.description` | Damaged, lost, or stolen subject | common/scalar/no | C,E/y/y/y | y/c/registered | Registry + form | C/S; privacy |
| `incident.injury_or_danger` | Bounded injury/continuing danger signal | common/boolean/no | C/y/y/y | urgent/y/registered | Registry + interruption rules | C/S; safety |
| `parties.other_parties` | Whether another person or organisation is involved | conditional/boolean/no | C/y/y/y | handoff/c/registered | Participant details remain a separate record | C/S; consent/privacy |
| `incident.liability_position` | Whether fault is accepted, shared, disputed or unknown when another party is involved | conditional/enum/no | C/y/y/y | triage/y/registered | Registry v8; required once `parties.other_parties` is true | C/S |
| `loss.estimated_amount` | Estimated loss in NZD from the claimant or a quote or assessment | common/number/no | C,E/y/y/y | triage/c/registered | Registry v8 | C/S |
| `claim.cover_disagreement` | Whether the claimant disputes the excess or the cover | common/enum/no | C/y/y/y | triage/y/registered | Registry v8 | C/S |
| `evidence.availability` | Available, missing, incomplete, pending | common/enum/no | C,E,W/y/y/y | next action/y/record | Covered by `EvidenceRecord`, `EvidenceStatus`, and `EvidenceSummary`; not a form field | C/S; privacy |
| `declaration.factual_accuracy` | Claimant factual declaration | common/enum/no | C/y/y/y | authority/y/record | Covered by `ClaimAgreementAcceptance` and the agreement service/API; not a form field | C/S; authority |
| `consent.sharing_scope` | Purpose and fields allowed to share | conditional/structured/no | C/y/y/y | external/y/record | Consent record exists | C/S; consent/privacy |
| `report.channel` | Entry channel | common/enum/no | Y/n/n/n | n/n/system-owned | Claim State | S; audit |
| `claim.created_at` | System receipt time | common/date-time/no | Y/n/n/n | n/n/system-owned | Claim State | S; audit |
| `claim.registry_version` | Registry snapshot used | common/scalar/no | Y/n/n/n | n/n/record | Persisted as separate Field Registry and branch-rule coordinates on Branch Evaluation records, not as a claimant form field | S; audit |

## Motor field inventory

| Code | Meaning | Type/multi | src/NL/conf/infer | safe/now/status | Current implementation / needed boundary | vis/auth |
| --- | --- | --- | --- | --- | --- | --- |
| `vehicle.identity` | Insured vehicle identity/reference | object/no | C,P/y/y/y | routing/c/record | Covered by `AssetRecord`, `VehicleAssetDetails`, and the immutable Claim asset snapshot | C/S; privacy |
| `vehicle.registration` | Registration/plate | scalar/no | C,E/y/y/y | provider/c/registered | Registered; validation/masking alignment | C/S; privacy |
| `vehicle.make` | Make | scalar/no | C,E/y/y/y | n/c/record | Optional `VehicleAssetDetails` and immutable Claim snapshot member; not a form field | C/S; privacy |
| `vehicle.model` | Model | scalar/no | C,E/y/y/y | n/c/record | Optional `VehicleAssetDetails` and immutable Claim snapshot member; not a form field | C/S; privacy |
| `vehicle.year` | Model year | scalar/no | C,E/y/y/y | n/c/record | Optional `VehicleAssetDetails` and immutable Claim snapshot member; not a form field | C/S; privacy |
| `vehicle.use` | Private, commuting, business, rideshare/delivery, other, or unknown use at the incident | enum/no | C/y/y/y | routing/c/registered | Implemented as a bounded Dynamic Form field | C/S; policy/privacy |
| `vehicle.damage_description` | Visible damage account | scalar/no | C,E/y/y/y | safety/y/registered | Registered; evidence link separate | C/S; privacy |
| `vehicle.drivable` | Whether the vehicle is safe and able to be driven | boolean/no | C/y/y/y | safety/y/registered | Registered; towing rule gap | C/S; safety |
| `vehicle.towing_required` | Required, not required, already towed, or unknown | enum/no | C,S/y/y/y | safety/y/registered | Implemented as a bounded Dynamic Form field | C/S; consent |
| `vehicle.towing_location` | Claimant-supplied current or intended tow location; interpretation is not inferred by the backend | location/no | C/y/y/y | safety/c/registered | Implemented as a bounded Dynamic Form field; the current contract preserves the supplied meaning without choosing current versus destination | C/S; privacy/consent |
| `driver.identity_ref` | Existing account identity reference for the actual Driver | reference/no | C,Y/y/y/n | authority/c/registered | Implemented as a typed Driver record member | S; privacy/authority |
| `driver.name` | Actual Driver name when no identity reference is available | scalar/no | C/y/y/n | authority/c/registered | Implemented as a typed Driver record member | C/S; privacy/authority |
| `driver.phone` | Actual Driver phone | scalar/no | C/y/y/n | contact/c/registered | Implemented as a typed Driver record member | C/S; privacy |
| `driver.email` | Actual Driver email | scalar/no | C/y/y/n | contact/c/registered | Implemented as a typed Driver record member | C/S; privacy |
| `driver.relationship_to_policyholder` | Driver relationship to the Policyholder | enum/no | C/y/y/y | authority/c/registered | Implemented as a typed Driver record member | C/S; authority |
| `driver.owner_permission` | Confirmed, not confirmed, unknown, or not applicable | enum/no | C/y/y/y | authority/c/registered | Implemented as a typed Driver record member without liability inference | C/S; authority |
| `driver.licence_number` | Protected Driver licence number | protected scalar/no | C,E/y/y/n | authority/pending/registered | Stored in the protected Driver boundary and omitted from model/RAG and claimant projections | S; privacy/authority |
| `driver.licence_status` | One reported licensing state: valid, expired, suspended, learner, restricted, or unknown | enum/no | C,E/y/y/y | review/pending/registered | Implemented as a typed Driver record member; the current contract does not expose a separate licence-class field | S; privacy/review |
| `collision.occurred` | Collision branch fact | enum/no | C/y/y/y | routing/y/record | Covered by collision branch evaluation; not a lifecycle or form field | C/S; privacy |
| `other_vehicle.identity` | Other vehicle reference/details | object/yes | C,E/y/y/y | provider/pending/record | Bounded `MotorOtherDriverRecord.vehicle_registration`; zero or one per Motor Claim | C/S; privacy |
| `other_party.contact` | Other party name, phone, and email | object/no | C/y/y/y | external/pending/record | Bounded `MotorOtherDriverRecord`; excluded from model/RAG context | C/S; privacy |
| `other_party.insurer_name` | Other party insurer when known | scalar/no | C/y/y/n | external/pending/registered | Implemented on the existing `MotorOtherDriverRecord` | C/S; privacy |
| `other_party.policy_number` | Other party Policy number when supplied | protected scalar/no | C/y/y/n | external/pending/registered | Implemented on the existing restricted participant record with masked projection | S; privacy |
| `other_party.claim_reference` | Other party insurer Claim reference when one exists | scalar/no | C/y/y/n | external/pending/registered | Implemented on the existing restricted participant record | C/S; privacy |
| `witness.present` | Yes, no, or unknown Witness presence | enum/no | C/y/y/y | evidence/c/registered | Implemented as a bounded Dynamic Form field | C/S; privacy |
| `witness.name` | Witness name | scalar/yes | C/y/y/n | evidence/pending/registered | Implemented as a repeatable typed Witness record member | S; privacy/consent |
| `witness.phone` | Witness phone | scalar/yes | C/y/y/n | evidence/pending/registered | Implemented as a repeatable typed Witness record member | S; privacy/consent |
| `witness.email` | Witness email | scalar/yes | C/y/y/n | evidence/pending/registered | Implemented as a repeatable typed Witness record member | S; privacy/consent |
| `police.status` | Not reported, reported, reference pending/available, not required, or unknown | enum/no | C,S/y/y/y | authority/y/registered | Implemented as a bounded Dynamic Form field; existing Police references remain canonical | C/S; authority |
| `authority.police_reference` | Police file/reference | scalar/no | C,E/y/y/y | authority/c/alias | Catalogue alias for registered `authorities.police_report_reference`; submit only the canonical code | C/S; privacy/authority |
| `motor.evidence_refs` | Vehicle photo/video/estimate refs | list/yes | E,C/y/y/y | evidence/y/record | Evidence API + item links | C/S; privacy |

## Home field inventory

| Code | Meaning | Type/multi | src/NL/conf/infer | safe/now/status | Current implementation / needed boundary | vis/auth |
| --- | --- | --- | --- | --- | --- | --- |
| `property.address` | Insured property address | location/no | C,P/y/y/y | routing/y/registered | Registry + form | C/S; privacy |
| `property.occupancy_relationship` | Owner, tenant, landlord, authorised representative, or other | enum/no | C/y/y/y | authority/c/registered | Implemented as a bounded Dynamic Form field | C/S; privacy |
| `property.occupancy` | Occupied, vacant, partially occupied, or unknown | enum/no | C/y/y/y | safety/c/registered | Implemented as a bounded Dynamic Form field | C/S; safety |
| `property.affected_areas` | Rooms, structures, outdoor areas | list/yes | C,E/y/y/y | triage/y/registered | Registered; branch shape gap | C/S; privacy |
| `property.ongoing_risk` | Leak, fire, collapse, exposure | enum/no | C/y/y/y | urgent/y/registered | Registry + home family; may trigger emergency mitigation | C/S; safety |
| `property.habitable` | Safe/usable to occupy | boolean/no | C,S/y/y/y | support/y/registered | Registry + home family; may trigger accommodation support | C/S; safety/review |
| `mitigation.emergency_action` | Emergency/mitigation taken | list/yes | C,S,E/y/y/y | safety/y/record | WorkItem/evidence + projection | C/S; consent |
| `mitigation.temporary_repair` | Temporary repair details | object/yes | C,S,E/y/y/y | safety/pending/record | WorkItem/Integration record | S; consent |
| `mitigation.contractor` | Contractor identity/work status | object/yes | C,S,P/y/y/y | external/pending/record | Provider/task record | S; consent |
| `home.evidence_refs` | Property photos/invoices/reports | list/yes | E,C/y/y/y | evidence/y/record | Evidence API + area links | C/S; privacy |

## Contents field inventory

Contents is intentionally explicit: the registry has a bounded contents subset while repeated
item facts belong to typed item records, not a flat claim form.

| Code | Meaning | Type/multi | src/NL/conf/infer | safe/now/status | Current implementation / needed boundary | vis/auth |
| --- | --- | --- | --- | --- | --- | --- |
| `contents.items` | Affected item collection | record/yes | C,E/y/y/y | evidence/y/record | Typed `ContentsItem` domain/API/persistence record | C/S; privacy |
| `contents.item.description` | Item description | scalar/no | C,E/y/y/y | evidence/y/record | Typed item field and role-safe projection | C/S; privacy |
| `contents.item.category` | Item category | scalar/no | C,E/y/y/y | routing/c/record | Opaque display category; bounded vocabulary remains a follow-up decision | C/S; privacy |
| `contents.item.quantity` | Count of similar items | scalar/no | C/y/y/y | evidence/c/record | Typed item field with minimum-one validation | C/S; privacy |
| `contents.item.brand` | Brand | scalar/no | C,E/y/y/y | n/c/record | Optional typed item/assertion/Asset proposal member | C/S; privacy |
| `contents.item.model` | Model/style | scalar/no | C,E/y/y/y | n/c/record | Optional typed item/assertion/Asset proposal member | C/S; privacy |
| `contents.item.ownership` | Owned, leased, borrowed, gifted, other | enum/no | C,E/y/y/y | authority/c/record | Typed item enum; wider authority rules remain follow-up work | C/S; privacy |
| `contents.item.estimated_value` | Claimant estimate, not settlement value | money/no | C,E/y/y/y | evidence/c/record | Optional currency-qualified money value; not settlement authority | C/S; review |
| `contents.item.loss_type` | Damaged, lost, stolen, destroyed | enum/no | C,E/y/y/y | routing/y/record | Typed item enum; theft conditional behavior remains a separate branch | C/S; authority |
| `contents.discovery_at` | When loss was discovered | date-time/no | C/y/y/y | safety/c/alias | Catalogue alias for registered `incident.discovered_at`; submit only the canonical code | C/S; privacy |
| `theft.entry_context` | Forced entry/access/unknown | enum/scalar/no | C,E/y/y/y | authority/y/registered | Theft branch; required now; forced_entry, unlocked, unknown, not_applicable | C/S; authority/privacy |
| `contents.receipt_availability` | Receipt/invoice status | enum/no | C,E/y/y/y | evidence/y/record | Covered by receipt Evidence lifecycle/status projection; not a form field | C/S; privacy |
| `contents.proof_of_ownership` | Ownership evidence references | list/yes | E,C/y/y/y | evidence/c/record | Item/evidence mapping | C/S; privacy |
| `contents.police_reference` | Police file/reference | text/no | C,E/y/y/y | authority/pending/registered | Optional bounded reference in theft branch | C/S; privacy/authority |
| `contents.item.evidence_refs` | Item photos/receipts/valuations | list/yes | E,C/y/y/y | evidence/y/record | Immutable item links | C/S; privacy |
| `contents.item_group` | Similar-item grouping/provenance | record/yes | C,E,Y/y/y/y | evidence/c/record | Group record + provenance | S; privacy |

## Conditional branch matrix

The executable catalogue uses Field Registry `6` and branch rules
`vp-dynamic-form-branch-rules-v2`. The following leaf fields are registered:

| Field | Value contract | Collection deadline |
| --- | --- | --- |
| `injury.persons_affected` | Nonempty text list | required_now |
| `injury.severity_reported` | minor, needs_medical_attention, serious, unknown | required_now |
| `injury.medical_attention` | none, self_treated, gp_or_clinic, ambulance_called, hospitalised, unknown | before_creation |
| `incident.discovered_at` | Temporal value with original wording and precision | before_creation in theft |
| `theft.entry_context` | forced_entry, unlocked, unknown, not_applicable | required_now |
| `contents.police_reference` | Nonempty text | optional |

Collection deadlines are declared by each branch. The evaluator's `_required_set`
supplies field selection, requirement resolution, creation, and external-dispatch
gates. `before_creation` and `before_dispatch` do not become `required_now` merely
because a branch is active. Optional fields remain permitted; staff-only fields do
not enter the model field contract. Repeatable records remain outside generic form.
`authorities.emergency_services_notified` is a cross-path boolean, including Home
and Contents incidents; it is not restricted to Motor.

| Branch | Kind | Collection policy | Record intents |
| --- | --- | --- | --- |
| family.motor / home / contents | fact | Family-required fields: required_now | None |
| incident.collision | fact | parties.other_parties: required_now | motor_other_driver |
| contents.theft | fact | theft.entry_context: required_now; incident.discovered_at: before_creation; contents.police_reference: optional | None |
| injury.details | fact | persons_affected and severity_reported: required_now; medical_attention: before_creation | None |
| safety.injury_or_danger | workflow | None; incident.injury_or_danger is already common-required | Handoff intent |
| authority.police | record | authorities.police_report_reference: optional | evidence_pending_police_report |
| participant.another_party | record | None | motor_other_driver |
| evidence.pending | record | Existing evidence lifecycle | Existing evidence intent |
| accommodation.temporary | record | None | accommodation_work_item |
| mitigation.emergency | record | None | mitigation_work_item |
| human_support / professional_review | workflow | None | Existing handoff/review intent |
| participant.witness | projection | None | None |

The injury-detail branch requires a confirmed positive injury/danger fact; urgent
Claim State alone activates the safety workflow, not these fact leaves. Weak
injury words can identify a candidate without being accepted as a fact. A source-backed
negative correction exits injury details even when previous leaf values remain for
audit. Active fact branches retain recorded leaves across silent turns; old-version
branch evaluations never resurrect a branch in the current registry.

Required facts are split into `satisfied` (confirmed), `recorded` (proposed), and
`missing_required_now` (missing or disputed). Proposed facts, including Contents
items, are not asked again. They block creation until explicit confirmation.
`missing_by_branch` groups missing facts for contextual questions; `ready_pending_confirmation`
distinguishes an otherwise complete report with proposed facts. The total includes
recorded facts, while the satisfied count includes only confirmed facts.

Direct claimant facts may be normalized without requiring a second confirmation.
Inference, disputed facts, and non-claimant values for authority-sensitive fields
(`claim.product_family`, `incident.injury_or_danger`, `parties.other_parties`,
`incident.type`) require confirmation. Safety handoff preserves accepted facts and
permits subsequent conversation; active handoff suspends all third-party suggestions.

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
3. **Family classification:** in v8 model turns without authoritative family, expose the
   registered top-level `motor`, `home`, and `contents` fields as candidates independent of
   keyword matches. Candidate admission adds no family requirements. A persisted proposed or
   confirmed family selects its collection requirements; source validation still controls
   confirmation. ControlledAgent retains its existing deterministic admission rules.
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
| `BR-COLLISION-001` | Impact, crash, rear-end, or collision is explicitly described | Activate `incident.collision`; add other-participant and possible Police/Evidence candidates | Correction to a non-collision incident suspends the branch, preserves its sources, and recalculates candidates | Do not require other-party details unless they block the current safe action |
| `BR-PARTICIPANT-OTHER-001` | Another person, vehicle, property owner, or organisation is mentioned | Activate `participant.another_party`; add participant candidates and a consent check before disclosure | A correction or consent withdrawal exits sharing while retaining the original statement | Contact or identity is `required_now` only for an authorised next action |
| `BR-PARTICIPANT-WITNESS-001` | A witness is mentioned or requested for the next action | Activate `participant.witness`; create a participant/evidence work item | Mark unavailable when the claimant cannot provide details; never invent contact data | Witness details normally remain `candidate_now` or `pending_later` |
| `BR-AUTHORITY-POLICE-001` | Police contact, a Police report, theft/burglary, or pending Police generation is mentioned | Activate `authority.police`; track status/reference and an evidence WorkItem | Correction or verified inapplicability exits the branch with audit history | A missing report remains `pending_later` unless a current authorised action explicitly requires it |
| `BR-SAFETY-001` | Explicit injury, continuing danger, or an emergency condition is present | Activate safety workflow; save accepted facts and urgent handoff with bounded safe response | Clear only from a new authoritative fact; preserve the original safety statement | Preserve dialogue and optional relevant questions; suspend third-party suggestions during handoff |
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

## Implementation boundary

| Area | Current backend | Current API | Current persistence | Needed consumer | Owner candidate |
| --- | --- | --- | --- | --- | --- |
| Common and conditional subset | 28 executable registered codes; bounded form | Claim, message-turn, form, confirmation, and Dynamic Form projections | Generic `WorkingClaim.form` with assertion history | Agent, claimant, staff | Implemented VP baseline |
| Motor extensions | Registration, damage, drivable state, and common fields | Role-safe Dynamic Form and Claim projections | Generic registered fields | Agent, claimant, staff | Implemented VP baseline |
| Home extensions | Address, affected areas, ongoing risk, habitability, and common fields | Role-safe Dynamic Form and Claim projections | Generic registered fields | Agent, claimant, staff | Implemented VP baseline |
| Contents extensions | Typed source-aware item records plus optional brand/model and common fields | Role-safe item, Dynamic Form, confirmation, Claim, and Evidence-link projections | Embedded item/assertion records plus immutable item-to-Evidence associations | Dynamic Form, claimant, staff | Implemented bounded journey baseline |
| Branch registry | Mutually exclusive families plus registered conditional branches | Embedded versioned Dynamic Form projection; no standalone public branch endpoint | Immutable applied Branch Evaluation history | Agent/runtime/projections | Implemented VP baseline |
| Required-now projection | Deterministic current-action requirements and next-item selection | `requirements` on Dynamic Form responses | Selection and requirement result retained in Branch Evaluation | Agent, Dynamic Form, UI | Implemented VP baseline |
| Item/evidence provenance | Evidence API plus same-Claim association validation | Item links on claimant and staff detail | Immutable `ContentsItemEvidenceAssociation` | Evidence, claimant, staff | Implemented bounded journey baseline |
| Consent/agreement | External consent and Claim agreement acceptance exist as separate records | Route-specific role-safe projections | Consent and agreement acceptance records; catalogue-wide scopes remain absent | Agent/integrations/UI | Implemented bounded records; broader scope remains an open decision |
| Commercial FNOL fields | Executable registry, typed Claim participant records, and role-safe projections for the approved 24-field set | Conditional values may be absent or pending | Claim revision and existing record boundaries remain authoritative | Agent, claimant, staff | #1084 implemented |
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

1. Confirm policy lookup and identity-match inputs without inventing provider schemas.
2. Approve production `required_now` sets beyond the implemented VP claim-creation baseline.
3. Approve retention and visibility for the new Policyholder, Driver, other-party, Witness,
   Police, and occupancy values before implementation in #1084.
4. Decide whether contents uses one record per item, grouped records, or both with IDs.
5. Define publication/rollback behavior for in-progress claims.

## Current implementation statement

The backend implements a bounded VP baseline for motor, home, and contents. It includes the
registered Dynamic Form codes, typed contents and participant records, account Assets and immutable Claim asset
snapshots, Evidence and agreement records, mutually exclusive family selection, conditional
branches, deterministic current-action requirements, assertion history, role-safe projections,
and claim creation for each family. The remaining catalogue candidates are explicitly outside #1084.

## Requested-data inventory and ownership

This section is the #918 inventory and minimum privacy boundary. It does not create APIs,
lifecycle states, migrations, provider verification, payment execution, Policy Summary CRUD, or
Policy-to-Asset associations. Those implementation contracts belong to the bounded child issues.
Only Dynamic Form entries belong in the Field/Branch Registry; account, protected, repeatable,
file, and operational data remain typed records.

| Requested datum | Current canonical representation | Delivery owner |
| --- | --- | --- |
| Legal name | Profile member; legacy display name migrates into it | #923 implemented |
| Preferred name | Optional Profile member; drives the compatibility display name when present | #923 implemented |
| Date of birth | Optional protected Profile member | #923 implemented |
| Phone number | Existing Profile contact member | Existing / #923 projection |
| Email address | Existing authenticated account identifier and Profile projection | Existing / #923 projection |
| Residential address | Optional Profile address member | #923 implemented |
| Policy number | Reuse `policy.policy_number`; reusable account Policy Number record | #923 implemented |
| Bank account type | Protected Payment Destination member; never a payment command | #923 implemented |
| Bank account number | Encrypted and ordinarily masked Payment Destination member | #923 implemented |
| Driver licence number | Encrypted and ordinarily masked Identity Record member | #923 implemented |
| Passport number | Encrypted and ordinarily masked Identity Record member | #923 implemented |
| Policyholder identity/name for a non-Policyholder reporter | Claim-scoped typed Policyholder record members | #1084 implemented |
| Reporter relationship to Policyholder | Bounded conditional Dynamic Form field | #1084 implemented |
| Reusable insured vehicle | Existing vehicle Asset and immutable Claim asset snapshot | #921 |
| Vehicle registration | Reuse `vehicle.registration` and vehicle Asset snapshot | #921 |
| Vehicle registered owner | Existing optional `VehicleAssetDetails.registered_owner`; copied into the immutable vehicle snapshot | #921 |
| Motor incident time | Reuse `incident.occurred_at` | Existing registry |
| Motor incident location | Reuse `incident.location` | Existing registry |
| Motor account of what happened | Reuse `incident.description` | Existing registry |
| Vehicle damage | Reuse `vehicle.damage_description` | Existing registry |
| Vehicle damage photos | Reuse Evidence | Existing Evidence baseline |
| Other driver name | Optional member of the bounded zero-or-one `MotorOtherDriverRecord` | #919 implemented |
| Other driver contact | Optional phone/email members on the role-safe Motor other-driver projection; excluded from model/RAG context | #919 implemented |
| Other vehicle registration | Optional `vehicle_registration` on the bounded Motor other-driver record | #919 implemented |
| Actual Driver identity, contact, relationship, owner permission, and licence | Claim-scoped typed Driver record; licence is omitted from role-safe projections | #1084 implemented |
| Vehicle use | Bounded conditional Dynamic Form field | #1084 implemented |
| Vehicle towing requirement and location | Bounded conditional Dynamic Form fields; existing recovery service remains separate | #1084 implemented |
| Other-party insurer, Policy number, and Claim reference | Extension of the existing Motor other-driver record | #1084 implemented |
| Witness presence | Bounded conditional Dynamic Form field | #1084 implemented |
| Witness name, phone, and email | Repeatable typed Witness record members | #1084 implemented |
| Police reporting status | Bounded conditional Dynamic Form field; existing Police references and Evidence remain canonical | #1084 implemented |
| Motor Police reference | Reuse `authorities.police_report_reference` | Existing registry |
| Motor repair quote, invoice, or estimate | Reuse Evidence | Existing Evidence baseline |
| Reusable insured property | Existing property Asset and immutable Claim asset snapshot | #921 |
| Property address | Reuse `property.address`; property Asset snapshot supplies the reusable detail | #920 |
| Property owner/name | Existing optional `PropertyAssetDetails.owner_name`; copied into the immutable property snapshot | #921 |
| Reporter relationship to property and occupancy state | Bounded conditional Dynamic Form fields | #1084 implemented |
| Home incident time | Reuse `incident.occurred_at` | Existing registry |
| Home account of what happened | Reuse `incident.description` | Existing registry |
| Damaged property areas | Reuse `property.affected_areas` | Existing registry |
| Home damage photos | Reuse Evidence | Existing Evidence baseline |
| Emergency repair receipt | Reuse receipt Evidence with Claim ownership and claimant/staff metadata readback | #920 verified |
| Home Police reference | Reuse `authorities.police_report_reference` | Existing registry |
| Reusable contents asset | Existing contents Asset and immutable Claim asset snapshot | #921 |
| Damaged, lost, or stolen item description | Existing ContentsItem and `loss.description` | Existing baseline |
| Contents brand | Optional `brand` on ContentsItem, assertion history, Asset proposal, and role-safe projections | #922 implemented |
| Contents model | Optional `model` on ContentsItem, assertion history, Asset proposal, and role-safe projections | #922 implemented |
| Receipt or proof of purchase | Evidence linked to one same-Claim ContentsItem through an immutable association | #922 implemented |
| Contents incident time | Reuse `incident.occurred_at` | Existing registry |
| Contents incident location | Reuse `incident.location` | Existing registry |
| Contents repair quote | Evidence linked to one same-Claim ContentsItem through an immutable association | #922 implemented |
| Contents Police reference | Reuse `authorities.police_report_reference` | Existing registry |

No executable registry field is added by #918 or #921. Aliases such as `police_reference` are
not registered, and requested files are Evidence rather than Dynamic Form strings.

### Asset-to-Claim prefill

Selecting an active owned asset proposes, but does not confirm, only these existing facts:

| Asset type | Proposed registered fields |
| --- | --- |
| Vehicle | `claim.product_family=motor`, `vehicle.registration` |
| Property | `claim.product_family=home`, `property.address` |
| Contents | `claim.product_family=contents`; also one proposed ContentsItem from Asset description/category/brand/model |

Each proposal uses claimant source authority because the authenticated claimant selected the
record, keeps `status=proposed`, and records `asset:{asset_id}:revision:{revision}`. Selection
does not confirm ownership, coverage, liability, identity, payment eligibility, value, damage,
loss, or theft.
