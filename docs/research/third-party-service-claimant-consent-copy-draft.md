# P5.1 Third-Party Service Claimant Consent Copy Draft

This reference draft supplies the claimant-facing copy owned by Issue #592. It covers every
service and enabling-platform identifier in the accepted P3.3 catalogue, while leaving action
authority, audit rules, and final retention decisions to P5.2 and the merged P5 contract.

The copy is documentation evidence only. It does not create a Runtime service identity, permitted
field, consent state, provider connection, Northwind authority, legal basis, retention period, or
production-ready notice.

## Assemble one service notice

A claimant notice uses the service-specific values below with the common state copy. The UI must
show the readable labels, not the P3 coordinate, Runtime identifier, or raw field names.

Use this order for one notice:

1. Name the service and recipient.
2. Explain the single request purpose.
3. List the minimum information that would leave Northwind.
4. Explain that recording information and sending it are separate.
5. State the applicable retention limitation.
6. Offer an unpressured yes or no choice.
7. Show the correct refusal or withdrawal outcome after the claimant acts.

The P3 identifiers remain research coordinates. Only
`vehicle_damage_assessment_routing` is an implemented Runtime `service_identity`; no other row
creates or reserves one.

## Use the common state copy

The following copy fragments are documentation coordinates, not API enums or reason codes.

| Copy ID | When it applies | Claimant-facing draft |
| --- | --- | --- |
| `P5-COPY-RECORD` | Before any Northwind send-permission choice | **Already in your claim:** These details are already recorded in your Northwind claim. Giving permission below would allow only the listed details to be sent for this request; it does not change what is recorded in your claim. |
| `P5-COPY-CONSENT` | An approved and available Northwind send path needs claimant permission | **Your choice:** Do you give Northwind permission to send the information listed above to **[recipient]** for **[purpose]**? Your permission covers only this service, this purpose, and this request. |
| `P5-COPY-REFUSE` | The claimant says no | **You chose not to share:** We will not send this request. Information already recorded in your Northwind claim stays unchanged, and any claim steps that do not depend on this service can continue. We can ask a claims professional about another route. |
| `P5-COPY-WITHDRAW-UNSENT` | Permission is withdrawn before the request is sent | **Permission withdrawn:** We will not send this request. Information already recorded in your Northwind claim stays unchanged. |
| `P5-COPY-WITHDRAW-SENT` | Permission is withdrawn after the request may have reached the recipient | **Withdrawal recorded:** The request may already have reached **[recipient]**, so we cannot promise that it or any copies can be cancelled, recalled, or deleted. A claims professional will check what can still be stopped and tell you what happens next. |
| `P5-COPY-RETENTION-BLOCKED` | Any proposed Northwind external send in the Validation Prototype | **How long it is kept:** Northwind has not approved a production retention period for this request or the recipient's copy. This service is not available for real claim data until both retention periods and deletion rules are confirmed. |
| `P5-COPY-MANUAL` | The claimant contacts the organisation directly and Northwind sends nothing | **You contact them directly:** Northwind will not send your claim information to **[recipient]**. If you choose to contact them, their privacy notice and process apply. You can add the result to your Northwind claim later without restarting. |
| `P5-COPY-MANUAL-RETENTION` | A result from a claimant-led path may later be added to the Claim | **How long it is kept:** **[recipient]** decides how long it keeps information you give it. If you add the result to your Northwind claim, Northwind's claim-retention rules apply. Northwind's production retention period is not approved yet. |
| `P5-COPY-UNAVAILABLE` | Access, authority, recipient, or data use is not approved | **This service is not available through Northwind:** Its access and data-sharing rules have not been approved. I can help you use the available manual option or arrange support. |

`P5-COPY-CONSENT` must never appear by itself. It is eligible only when the recipient, exact
purpose, exact disclosed fields, current Northwind authority, provider access, and retention notice
are all available from authoritative contracts. The Runtime still performs the final checks.

## Map contract identifiers to claimant labels

This table defines wording only for identifiers that already exist. A service that needs an
unmapped identity, contact, authority, appointment, product, or report-type field stays
unavailable until a later contract maps that input.

| Contract identifier | Claimant label |
| --- | --- |
| `claim_id`, `external_claim_id` | Your Northwind report and claim references. |
| `incident.description` | Your description of what happened. |
| `incident.occurred_at` | When the incident happened. |
| `incident.location` | Where the incident happened. |
| `incident.type` | The type of incident. |
| `incident.injury_or_danger` | Whether you reported an injury or continuing danger. |
| `loss.description` | What was damaged or lost. |
| `parties.other_parties` | Whether another person or organisation was involved. |
| `authorities.police_report_reference` | Your Police report reference, if one has been issued. |
| `authorities.emergency_services_notified` | Whether emergency services were contacted. |
| `vehicle.registration` | Your vehicle registration. |
| `vehicle.damage_description` | Your description of the vehicle damage. |
| `vehicle.drivable` | Whether the vehicle can be driven. |
| `property.address` | The address of the affected property. |
| `property.affected_areas` | The parts of the property that are affected. |
| `property.ongoing_risk` | Any continuing risk at the property. |
| `property.habitable` | Whether the home can currently be lived in. |
| `policy.policy_number` | Your policy number. |
| `contents_items[*].description`, `quantity`, `loss_type`, `ownership`, `estimated_value` | The affected items, how many, what happened to them, whether you own them, and the value you provided. |
| `Evidence.evidence_id`, `kind`, `status`, `file_status` | The relevant document or image and its Northwind evidence status. |
| `authorisation_ref`, `claimant_consent_ref`, `requested_action` | Northwind's authority, your permission record, and the requested service action. These are described to the claimant but their raw references are not shown. |
| `location.region` | The confirmed incident region. |

## Cover every claim-journey participant

Each row contains the copy values for one P3.3 claim participant. A **candidate** data scope is not
permission to send those fields; it records the minimum wording input for P5.2/P5.3 review.

| P3 service ID | Runtime identity and current path | Recipient and purpose copy | Minimum shared-data copy and contract identifiers | Choice, retention, and withdrawal copy |
| --- | --- | --- | --- | --- |
| `P3-NZP-REPORT` | No Runtime identity. Claimant-led Police 105 or other appropriate Police channel. | **New Zealand Police reporting.** Send a non-emergency incident report or update to New Zealand Police. | **Northwind sends:** Nothing. A Police report or reference later added to the Claim is represented by `authorities.police_report_reference` or `Evidence.kind=police_report`. | Use `P5-COPY-MANUAL` and `P5-COPY-MANUAL-RETENTION`. Northwind send refusal and withdrawal are not applicable because Northwind does not send the report. Emergencies remain on the 111 safety path. |
| `P3-NZP-TCR` | No Runtime identity. Claimant-led or staff-prepared manual request only. | **Traffic Crash Report request.** Ask New Zealand Police for a held Traffic Crash Report about the crash. | **Northwind sends:** Nothing in the current path. Requester identity, reason, and representative-authority evidence do not have an approved external-disclosure mapping. A supplied result may use `Evidence.kind=police_report`. | Use `P5-COPY-MANUAL` and `P5-COPY-MANUAL-RETENTION`. Use `P5-COPY-UNAVAILABLE` for a Northwind-send option. No release or response time is promised. |
| `P3-VEHICLE-RECOVERY` | No Runtime identity. Northwind operating form and dispatch authority are unresolved. | **Vehicle recovery.** Ask **[named recovery provider]** to help move the vehicle safely after this incident. | **Candidate scope:** The Claim reference, vehicle location, registration, condition, damage summary, and recovery request: `claim_id`, `incident.location`, `vehicle.registration`, `vehicle.drivable`, `vehicle.damage_description`, `requested_action`. Claimant contact and eligibility inputs are unmapped. | Current copy uses `P5-COPY-UNAVAILABLE`. A future approved path assembles `P5-COPY-RECORD`, `P5-COPY-RETENTION-BLOCKED`, `P5-COPY-CONSENT`, `P5-COPY-REFUSE`, and both withdrawal states. Do not describe roadside breakdown membership as collision recovery. |
| `P3-REPAIRER` | No Runtime identity. Claimant-selected and insurer-authorised repair paths remain distinct. | **Repair quote or appointment.** Ask **[named repairer]** to inspect the reported damage and provide **[appointment / quote / scope]**. This does not approve repairs or decide cover. | **Candidate scope:** `claim_id`, the applicable `vehicle.damage_description` or `property.affected_areas`, `loss.description`, the service location, and explicitly selected `Evidence.evidence_id` records. Appointment, contact, and approval fields are unmapped. | Current copy uses `P5-COPY-UNAVAILABLE` unless the claimant contacts a repairer directly, when the two manual fragments apply. A future approved Northwind-send path uses every record, retention, consent, refusal, and withdrawal fragment. |
| `P3-ASSESSOR` | Implemented controlled identity: `vehicle_damage_assessment_routing`; fixture provider only. Other assessor, adjuster, engineer, or specialist paths are unavailable. | **Vehicle damage assessment.** Ask the controlled assessment service to arrange an assessment of the vehicle damage recorded in this Claim. This does not decide cover or approve repairs. | **We will share:** Your Northwind report and claim references; Northwind's routing authority and your permission record; the vehicle damage assessment request; and your confirmed incident region. Exact current fields: `claim_id`, `external_claim_id`, `authorisation_ref`, `claimant_consent_ref`, `requested_action`, `location.region`. | Assemble all common record, blocked-retention, consent, refusal, and withdrawal fragments. The card must say **Controlled assessment fixture—no production assessor is contacted**. Do not add damage images or descriptions to the current scope. |
| `P3-EMERGENCY-WORKS` | No Runtime identity. Guidance, claimant arrangement, or staff-assisted manual handling only. | **Emergency property work.** Ask **[named contractor]** to carry out the agreed work needed to make the property safe, sanitary, secure, or weathertight. This does not approve cover or reimbursement. | **Candidate scope:** `claim_id`, `property.address`, `property.affected_areas`, `property.ongoing_risk`, `property.habitable`, `loss.description`, `requested_action`, and only the selected evidence. Safe-access, contact, scope, and spending authority are unmapped. | Current copy uses `P5-COPY-UNAVAILABLE` or the two manual fragments. A future Northwind dispatch uses every record, retention, consent, refusal, and withdrawal fragment. Safety guidance must not wait for this consent choice. |
| `P3-FENZ-INFO` | No Runtime identity. Claimant request or staff-prepared manual request only. | **Fire and Emergency information request.** Ask Fire and Emergency New Zealand for the specific information it holds about the incident. | **Northwind sends:** Nothing in the current path. Requester identity, contact, information scope, timeframe, and representative authority are not mapped for external disclosure. A supplied result may use `Evidence.kind=other_document`. | Use `P5-COPY-MANUAL` and `P5-COPY-MANUAL-RETENTION`. Use `P5-COPY-UNAVAILABLE` for a Northwind-send option. The copy must not promise release, a charge-free response, or a fixed completion date. |
| `P3-METSERVICE` | No Runtime identity. Public lookup, claimant-led request, or labelled simulation only. | **Historical weather information.** Ask MetService for **[named report type]** about the weather at the incident place and time to support review of what happened. The report does not decide cover or cause. | **Candidate scope:** `incident.occurred_at`, `incident.location`, `incident.type`, and the bounded weather question. The selected report product, licence, quote, and request field are unmapped. No claimant identity should be included unless the approved product requires it. | Current copy uses `P5-COPY-UNAVAILABLE`; a claimant-led purchase uses the manual fragments. A future approved Northwind request uses every record, retention, consent, refusal, and withdrawal fragment. |
| `P3-NHC` | No Runtime identity. Home building/land only; Northwind partner workflow is unconfirmed. | **Natural Hazards Commission claim coordination.** Share the information needed for **[named NHCover step]** about eligible residential building or land damage. This does not decide whether NHCover or the Northwind policy applies. | **Candidate scope:** `claim_id`, `policy.policy_number`, `property.address`, `incident.type`, `incident.occurred_at`, `incident.description`, `loss.description`, and explicitly selected Evidence. Partner identity, routing step, and exchange fields are unmapped. | Current copy uses `P5-COPY-UNAVAILABLE`. A future approved insurer-mediated path uses every record, retention, consent, refusal, and withdrawal fragment. Never apply this row to generic contents evidence. |
| `P3-CONTENTS-EVIDENCE` | No Runtime identity. Claimant retrieves and uploads evidence. | **Proof for an affected item.** Ask **[retailer / bank / manufacturer / service centre / valuer]** for a receipt, statement, service record, or valuation that may support the Claim. | **Northwind sends:** Nothing in the current path. The result may be linked to the applicable `contents_items[*]` entry and stored as `Evidence.kind=receipt` or `Evidence.kind=other_document`. Direct retrieval identity, matching keys, and authority are unmapped. | Use `P5-COPY-MANUAL` and `P5-COPY-MANUAL-RETENTION`. Use `P5-COPY-UNAVAILABLE` for direct Northwind retrieval. Northwind withdrawal copy is not applicable before a direct-send path exists. |
| `P3-BROKER` | No Runtime identity. Authority-boundary participant, not an automatic action target. | **Broker coordination.** Send **[named broker]** the information needed for **[named communication, referral, or Claim step]** within the authority you have given them. | **Candidate scope:** `claim_id`, `policy.policy_number`, the minimum applicable incident/loss fields, and explicitly selected Evidence. Broker identity, claimant-authority evidence, delegation scope, action, and contact fields are unmapped. | Current copy uses `P5-COPY-UNAVAILABLE`. A future approved path uses every record, retention, consent, refusal, and withdrawal fragment and must name the broker and delegated task. Broker involvement is not universal. |
| `P3-ACC-PROVIDER` | No Runtime identity. Health-provider-led pathway; Northwind lodgement is unavailable and must not be simulated. | **ACC injury support.** A registered health provider can discuss and, when appropriate, lodge an ACC claim with you. Northwind does not diagnose an injury, lodge the ACC claim, or decide ACC cover. | **Northwind sends:** Nothing. `incident.injury_or_danger` may support Northwind's safety and handoff path but is not approved for disclosure to a health provider through this service. Patient identity, injury details, provider details, and declaration are outside the current external-request contract. | **You contact them directly:** Northwind will not send your claim information to a health provider or ACC. A registered health provider can explain the ACC process. Do not add medical or ACC information to this Claim unless Northwind requests it through an approved path. The provider or ACC explains how long it keeps information you give it; Northwind makes no retention claim for that separate pathway. Do not offer Northwind send consent or simulate lodgement. If the claimant needs urgent help, follow the safety path rather than this service copy. |

## Cover every enabling platform

Enabling platforms process part of another Northwind capability; they are not claim participants
or standalone claimant actions. The following coverage prevents a technical vendor from being
silently presented as a recipient chosen by the claimant.

| P3 platform ID | Potential processing purpose and data | Claimant-copy disposition |
| --- | --- | --- |
| `P3-EN-MESSAGING` | Deliver an approved message using recipient address, sender identity, message content, and delivery metadata. | Do not show a third-party service consent card. Production copy remains blocked until Northwind approves the channel basis, sender, opt-out, content, region, provider retention, and deletion rules. |
| `P3-EN-DOC-AZURE` | Extract text or fields from selected `Evidence` bytes and return machine-derived candidates. | Do not show a standalone service consent card. An evidence-processing notice must name the purpose, selected evidence, provider category, region, retention, and the need to confirm extracted facts before real data is sent. |
| `P3-EN-IDENTITY` | Authenticate the claimant and return bounded identity or session assertions. | Do not treat authentication as permission to disclose Claim data or perform a Claim action. Production identity copy requires the approved identity provider and privacy terms. |
| `P3-EN-ROUTES` | Calculate a route, distance, or duration from selected origin, destination, travel mode, and output fields. | Do not describe the platform as a towing or recovery provider. Any future location-processing notice must identify the exact route purpose and minimum locations before use. |
| `P3-EN-MODEL` | Process the minimum authorised Agent context and return advisory or structured output. | Do not show a third-party action consent card. Production Agent privacy copy remains blocked until the exact profile, purpose, data scope, region, retention, training/logging terms, and evaluation are approved. |
| `P3-EN-DOC-AWS` | Extract text, forms, tables, signatures, coordinates, or confidence from selected `Evidence` bytes. | Use the same evidence-processing notice boundary as `P3-EN-DOC-AZURE`; do not imply that extracted content is a confirmed Claim fact. |
| `P3-EN-CONVERSATION` | Carry Claim-linked messages, selected files, receipts, and delivery events between authorised users. | Do not show a standalone service consent card. Production channel copy requires approved identity mapping, role visibility, content scope, moderation, retention, deletion, region, and provider access. |
| `P3-EN-DAMAGE-AI` | Analyse selected vehicle-damage images and return an advisory result or confidence. | Do not show or enable a production action. A labelled simulation may use synthetic images only. Real-data copy remains blocked until access, region, image scope, result meaning, retention, and human verification are approved. |

P5.2 must decide whether each approved platform is covered by a general privacy notice, a
purpose-specific processing notice, explicit consent, or another Northwind-authorised basis. This
draft deliberately does not make that legal or authority decision.

## Review the coverage and copy

The review result for this draft is bounded as follows:

- All 12 P3.3 claim-participant identifiers have a named recipient or recipient placeholder, one
  bounded purpose, minimum data wording tied to current contract identifiers, and an explicit
  manual, unavailable, or consent-copy path.
- All eight P3.3 enabling-platform identifiers have a processing-purpose and claimant-copy
  disposition; none is silently promoted into a claimant-selected external action.
- The current assessor fixture uses the implemented `service_identity` and exact six permitted
  fields. Every other Runtime identity or unmapped input remains unavailable.
- Every Northwind-send path references record/send separation, retention, refusal, pre-send
  withdrawal, and post-send withdrawal. Claimant-led paths state that Northwind sends nothing.
- The copy makes no coverage, liability, repair approval, emergency contact, provider completion,
  recall, deletion, service-level, or production-access promise.

This is copy-review evidence at governed-document level. It is not API-contract, authorisation,
integration, Runtime, browser-route, or full-journey evidence.

For the research source and access limits, see the
[P3.3 Unified Third-Party Service Catalogue and Implementation Brief](third-party-stakeholder-unified-service-catalogue-and-implementation-brief.md).
For the record/send, withdrawal, and open-retention boundary, see
[Privacy Governance](../privacy-governance.md). For the implemented field and external-request
shapes, see the [Northwind FNOL API Contract](../api.md),
[Persistence Contract](../persistence-schema.md), and
[Claim Creation and Provider Adapter Boundary](../claim-creation-boundary.md).
