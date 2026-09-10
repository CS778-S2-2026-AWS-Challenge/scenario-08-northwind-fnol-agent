# Third-party service consent and shared-data contract

This reference defines the final Validation Prototype consent and shared-data
boundary for Issues #592 through #595. It combines the accepted third-party service
catalogue with the claimant-facing P5.1 copy and defines record permission,
external-send permission, Northwind authority, claimant consent, refusal,
withdrawal, retention, expiry, and audit requirements.

This document does not create a provider integration, production legal basis,
new consent state, new Runtime service identity, new Claim State field, or new
external-task lifecycle. Current product specifications and implemented API and
domain contracts remain authoritative where this reference maps to Runtime
behaviour.

## Apply the authority model

Recording information in the Claim and sending information outside Northwind
are separate permissions. A claimant's external-service choice does not grant
new permission to collect or retain unrelated Claim data, and information
already validly recorded in the Claim does not automatically become eligible
for external disclosure.

A Northwind external send requires all of the following to be true at the time
of execution:

- The service identity and requested action are supported by the current
  Runtime contract.
- The recipient and purpose are known and bounded.
- The exact disclosed fields are known and no broader than the permitted
  scope.
- A current Northwind authority reference permits the action.
- A matching claimant-consent reference is granted for the same service,
  action, claimant, and disclosed fields.
- The provider path is available for the intended environment and data class.
- Required retention and privacy conditions are satisfied.

Northwind authority and claimant consent are independent authorities. Neither
substitutes for the other. Staff access to a Claim, staff ability to prepare a
request, or a model recommendation does not create disclosure authority.

The current Runtime accepts claimant consent only from the claimant associated
with the Claim. Authorised-representative consent is not established by the
current external-service contract and must not be inferred.

## Separate preparation, sending, and provider outcomes

Preparing an external request is not sending it. Provider acknowledgement is
not service completion, and a provider result is not automatically a confirmed
Claim fact.

The existing external-task lifecycle remains authoritative:

- `prepared` means the request has not been submitted.
- `accepted` requires evidence that the request was submitted and accepted.
- `retryable_failure` permits the governed same-operation recovery path.
- `terminal_failure` requires review rather than an automatic retry.
- `unknown_outcome` requires reconciliation before retry.

A timeout or partial effect after submission must not be converted into
success, safe failure, or a second request without the existing reconciliation
boundary.

## Apply refusal, withdrawal, expiry, and retention rules

Refusal means Northwind does not send the proposed external request. Refusal
does not delete information already validly recorded in the Claim and must not
silently change unrelated Claim work.

Withdrawal before sending invalidates that consent for the proposed send.
Withdrawal after a request may have reached a recipient is recorded, but
Northwind must not promise cancellation, recall, or recipient-side deletion
without separately verified provider capability.

The current consent model defines `granted` and `withdrawn`; it does not define
a general production time-based consent-expiry policy. This contract therefore
does not invent an expiry duration. A service that requires a time-based expiry
rule remains unavailable for production use until an authoritative contract
defines that rule. Wrong claimant, withdrawn consent, mismatched service or
action, or disclosure beyond the permitted fields already fails closed.

Northwind has no approved production retention period, deletion schedule, or
recipient-retention rule for these external-service requests. No duration may
be invented. Real customer-data sending remains unavailable where those
retention conditions are required and unresolved.

## Record audit evidence

This document does not introduce new AuditEvent names. Existing audit and
external-task contracts remain authoritative.

Material consent changes, authority decisions, disclosures, provider outcomes,
withdrawals, reconciliation outcomes, and privacy-relevant failures must retain
the applicable actor, purpose or reason, source references, time, outcome, and
limitations.

For an external request, the durable records must make it possible to determine
the service and action, purpose, exact disclosed fields, Northwind authority
reference, claimant-consent reference, operation identity where sent, delivery
evidence where available, and the resulting provider or failure state.

## Use the claim-participant service matrix

The following matrix is the final P5 authority mapping for the 12 accepted
claim-participant identifiers. Candidate fields describe the maximum research
input for later design; they are not permission to disclose those fields.

In each purpose and minimum-data cell, the text after `Claimant copy` and before
`Contract mapping` is claimant-readable wording. Contract mapping text provides
traceability and must not appear in claimant copy. A bracketed recipient, service
step, or product can be substituted only from an authoritative contract. If that
value is unavailable, show `P5-COPY-UNAVAILABLE` instead of the bracketed
placeholder or a consent choice.

| P3 service ID | Current VP path | Purpose and minimum data | Record rule | Send and staff-authority rule | Refusal and withdrawal | Retention and expiry | Claimant-copy rule |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `P3-NZP-REPORT` | Claimant-led Police reporting. | **Claimant copy — New Zealand Police reporting.** Report a non-emergency incident or update to New Zealand Police. **Northwind sends:** Nothing. You may later add a Police reference or report to your Claim. **Contract mapping:** `authorities.police_report_reference` or `Evidence.kind=police_report`. | Existing Claim/evidence rules only. External-service consent does not create record permission. | No Northwind send is authorised. Staff may guide the claimant but cannot represent Northwind as the reporting actor. | Northwind send refusal and withdrawal are not applicable because Northwind does not send. | The external Police process follows its own rules. Northwind production Claim retention remains unresolved. No P5 expiry duration is invented. | Use `P5-COPY-MANUAL` and `P5-COPY-MANUAL-RETENTION`. |
| `P3-NZP-TCR` | Claimant-led or staff-prepared manual request. | **Claimant copy — Traffic Crash Report request.** Ask New Zealand Police for a held Traffic Crash Report about the crash. **Northwind sends:** Nothing in the current path. A supplied report may be added to your Claim later. **Contract mapping:** Requester identity, reason, and representative authority are not mapped for disclosure. A supplied report may use `Evidence.kind=police_report`. | A supplied report may be recorded through the existing evidence contract. | Direct Northwind request authority is unavailable. Staff preparation does not create representative authority. | No Northwind send occurs; a Northwind-send option fails closed. | No Northwind retention or consent-expiry rule is approved for this service. | Use `P5-COPY-MANUAL` and `P5-COPY-MANUAL-RETENTION`; use `P5-COPY-UNAVAILABLE` for a Northwind-send option. |
| `P3-VEHICLE-RECOVERY` | Northwind dispatch unavailable. | **Claimant copy — Vehicle recovery.** Ask **[named recovery provider]** to help move the vehicle safely after this incident. **Candidate shared data:** Your Northwind Claim reference, vehicle location, registration, whether the vehicle can be driven, reported damage, and recovery request. **Contract mapping:** `claim_id`, `incident.location`, `vehicle.registration`, `vehicle.drivable`, `vehicle.damage_description`, and `requested_action`. Contact and eligibility inputs remain unmapped. | Existing Claim fields may remain recorded independently of a recovery request. | No production Northwind dispatch authority or provider path is established. Staff cannot infer it from roadside-assistance membership. | A proposed Northwind send is denied. Claimant-arranged assistance remains separate. | Production provider and Northwind retention are unresolved. No time-based expiry is defined. | Use `P5-COPY-UNAVAILABLE`; use manual copy where the claimant arranges recovery. |
| `P3-REPAIRER` | Claimant-selected/manual or unavailable Northwind path. | **Claimant copy — Repair quote or appointment.** Ask **[named repairer]** to inspect the reported damage and provide **[appointment, quote, or scope]**. This does not approve repairs or decide cover. **Candidate shared data:** Your Northwind Claim reference, the applicable vehicle or property damage, loss description, service location, and only the Evidence selected for this request. **Contract mapping:** `claim_id`, the applicable `vehicle.damage_description` or `property.affected_areas`, `loss.description`, and selected `Evidence.evidence_id` records. Service location, appointment, contact, and approval fields remain unmapped. | Damage and evidence may remain in the Claim under their existing contracts. | No generic repairer appointment or disclosure authority is established. Staff access is not authority to appoint or send. | Refusal blocks a proposed send. Manual claimant contact remains available where appropriate. | Provider and Northwind production retention are unresolved. No expiry duration is defined. | Use `P5-COPY-UNAVAILABLE` or manual copy. |
| `P3-ASSESSOR` | Controlled fixture path only: `vehicle_damage_assessment_routing`. | **Claimant copy — Vehicle damage assessment.** Ask the controlled assessment service to arrange an assessment of the vehicle damage recorded in this Claim. This does not decide cover or approve repairs. **We will share:** Your Northwind report and claim references; Northwind's routing authority and your permission reference; the vehicle damage assessment request; and your confirmed incident region. **Contract mapping:** Exact permitted Runtime scope: `claim_id`, `external_claim_id`, `authorisation_ref`, `claimant_consent_ref`, `requested_action`, and `location.region`. | Existing Claim recording remains independent of external-send consent. | The controlled request requires separate Northwind authority and matching granted claimant consent. Staff cannot replace claimant consent. No production assessor is contacted. | Refusal prevents the fixture request. Pre-send withdrawal prevents sending. Post-send uncertainty follows the existing reconciliation boundary. | Production retention is not approved. No general consent-expiry duration exists. Real customer-data use remains unavailable. | Use `P5-COPY-RECORD`, `P5-COPY-RETENTION-BLOCKED`, `P5-COPY-CONSENT`, `P5-COPY-REFUSE`, and both withdrawal states. State clearly that this is a controlled fixture. |
| `P3-EMERGENCY-WORKS` | Guidance, claimant arrangement, or staff-assisted manual handling. | **Claimant copy — Emergency property work.** Ask **[named contractor]** to carry out the agreed work needed to make the property safe, sanitary, secure, or weathertight. This does not approve cover or reimbursement. **Candidate shared data:** Your Northwind Claim reference, property address and affected areas, continuing risk and habitability status, loss description, requested work, and only the Evidence selected for this request. **Contract mapping:** `claim_id`, `property.address`, `property.affected_areas`, `property.ongoing_risk`, `property.habitable`, `loss.description`, `requested_action`, and selected `Evidence.evidence_id` records. Contractor identity, safe access, scope, contact, and spending authority remain unmapped. | Existing Claim and Evidence contracts govern recording. | No Northwind contractor-dispatch or spending authority is established. Safety guidance must not wait for external-service consent. | A Northwind send is denied unless a future approved path exists. Manual claimant action remains separate. | Retention and expiry conditions for a production external request are unresolved. | Use `P5-COPY-UNAVAILABLE` or the manual copy. |
| `P3-FENZ-INFO` | Claimant request or staff-prepared manual request. | **Claimant copy — Fire and Emergency information request.** Ask Fire and Emergency New Zealand for the specific information it holds about the incident. **Northwind sends:** Nothing in the current path. A supplied result may be added to your Claim later. **Contract mapping:** Request identity, contact, information scope, timeframe, and representative authority are not mapped. A supplied result may use `Evidence.kind=other_document`. | A supplied result may be recorded as evidence under the existing evidence contract. | No insurer API or standing Northwind request authority is established. | No Northwind send occurs. A proposed direct-send path fails closed. | FENZ handles information supplied directly to it under its process. Northwind production retention remains unresolved. | Use `P5-COPY-MANUAL` and `P5-COPY-MANUAL-RETENTION`; use `P5-COPY-UNAVAILABLE` for Northwind sending. |
| `P3-METSERVICE` | Public lookup, claimant-led request, or labelled simulation. | **Claimant copy — Historical weather information.** Ask MetService for **[named report type]** about the weather at the incident place and time to support review of what happened. The report does not decide cover or cause. **Candidate shared data:** When and where the incident happened, the incident type, and the bounded weather question. **Contract mapping:** `incident.occurred_at`, `incident.location`, and `incident.type`. The weather question, product, licence, quote, and request fields remain unmapped. | Weather evidence may be added under the existing evidence contract. | Public service existence does not establish Northwind procurement, account access, licence, or disclosure authority. | Direct Northwind sending is unavailable unless separately approved. | Provider and Northwind production retention are unresolved. No expiry duration is inferred. | Use `P5-COPY-UNAVAILABLE`; use manual copy for claimant-led acquisition. |
| `P3-NHC` | Home building/land pathway only; Northwind integration unavailable. | **Claimant copy — Natural Hazards Commission claim coordination.** Share the information needed for **[named NHCover step]** about eligible residential building or land damage. This does not decide whether NHCover or the Northwind policy applies. **Candidate shared data:** Your Northwind Claim and policy references, affected property address, applicable incident and loss details, and only the Evidence selected for this request. **Contract mapping:** `claim_id`, `policy.policy_number`, `property.address`, `incident.type`, `incident.occurred_at`, `incident.description`, `loss.description`, and selected `Evidence.evidence_id` records. Partner identity and routing fields remain unmapped. | Existing Claim and Evidence contracts govern recording. | No Northwind partner workflow or external-send authority is established. This row must not be applied to generic contents evidence. | Proposed Northwind sharing is denied without a future authorised path. | Production retention and expiry rules remain unresolved. | Use `P5-COPY-UNAVAILABLE`. |
| `P3-CONTENTS-EVIDENCE` | Claimant retrieves and uploads evidence. | **Claimant copy — Proof for an affected item.** Ask **[retailer, bank, manufacturer, service centre, or valuer]** for a receipt, statement, service record, or valuation that may support the Claim. **Northwind sends:** Nothing in the current path. You may later add the result to the affected item in your Claim. **Contract mapping:** Link the result to the applicable `contents_items[*]` entry and use `Evidence.kind=receipt` or `Evidence.kind=other_document`. | Resulting documents may be associated with the applicable contents item under the existing evidence contract. | Direct Northwind retrieval identity, matching keys, and disclosure authority are unavailable. | No Northwind send occurs. Withdrawal from a nonexistent send path is not applicable. | The external source controls information given directly to it. Northwind production Claim retention remains unresolved. | Use `P5-COPY-MANUAL` and `P5-COPY-MANUAL-RETENTION`; direct retrieval uses `P5-COPY-UNAVAILABLE`. |
| `P3-BROKER` | Authority-boundary participant; no automatic action target. | **Claimant copy — Broker coordination.** Send **[named broker]** the information needed for **[named communication, referral, or Claim step]** within the authority you have given them. **Candidate shared data:** Your Northwind Claim and policy references, the minimum applicable incident or loss details, and only the Evidence selected for this request. **Contract mapping:** `claim_id`, `policy.policy_number`, a future explicit allowlist of applicable registered incident/loss fields, and selected `Evidence.evidence_id` records. Broker identity, delegation, task, and contact fields remain unmapped. | Existing Claim information remains governed independently of broker sharing. | Broker involvement does not itself prove delegated authority. Staff cannot infer claimant delegation or a Northwind-send right. | A proposed send is denied until broker identity, purpose, delegation, and data scope are authoritative. | Production retention and expiry rules are unresolved. | Use `P5-COPY-UNAVAILABLE`. |
| `P3-ACC-PROVIDER` | Registered-health-provider-led pathway. Northwind lodgement unavailable. | **Claimant copy — ACC injury support.** A registered health provider can discuss and, when appropriate, lodge an ACC claim with you. **Northwind sends:** Nothing. Northwind does not diagnose an injury, lodge the ACC claim, decide ACC cover, or disclose its safety-relevant Claim facts through this service. | Northwind may retain its own safety-relevant Claim facts under the existing Claim contract; this does not authorise external medical disclosure. | No Northwind lodgement or disclosure authority exists and the pathway must not be simulated as a Northwind action. | Northwind send consent is not offered. | The provider or ACC explains its own retention. Northwind makes no new production retention or expiry claim. | Tell the claimant: "Northwind will not send your claim information to a health provider or ACC. A registered health provider can explain the ACC process." Do not offer Northwind send consent or simulate lodgement. |

## Use the enabling-platform matrix

Enabling platforms are not standalone claim participants. A platform cannot
gain its own claimant permission merely because a technical integration is
possible. Any future use inherits the purpose, minimum-data, authority,
consent, retention, and audit boundary of the approved Northwind action that
uses it.

| P3 platform ID | Current VP boundary | Processing purpose and candidate data | Permission and authority rule | Retention and audit rule | Claimant-copy rule |
| --- | --- | --- | --- | --- | --- |
| `P3-EN-MESSAGING` | Generic messaging capability only; production Northwind channel unavailable. | Deliver an approved message using the recipient address, sender identity, message content, channel configuration, and delivery metadata. | No standalone send permission. A future approved communication action must define recipient, content, channel basis, opt-out treatment, Northwind authority, and applicable claimant permission. | Provider region, retention, deletion, and production approval remain unresolved. Any future material disclosure uses the existing audit boundary. | Do not show a standalone third-party consent card. |
| `P3-EN-DOC-AZURE` | Generic document-processing capability only. | Extract text or fields from explicitly selected Evidence bytes and return machine-derived candidates. | No standalone permission. Selected Evidence must have an approved processing purpose and data scope before external processing. | Subscription, region, provider retention, deletion, and production data use remain unresolved. | No standalone service card; a future evidence-processing notice must describe the actual provider boundary and selected evidence. |
| `P3-EN-IDENTITY` | Generic identity capability only. | Authenticate the claimant from bounded credentials or identity assertions and return bounded identity or session assertions. | Authentication proves identity, not authority to disclose Claim data or execute a claim action. | Tenant, procurement, provider retention, and production identity governance remain unresolved. | No external-service consent card is created merely for authentication. |
| `P3-EN-ROUTES` | Route-computation capability only; no recovery-provider authority. | Calculate a route, distance, or duration from the minimum origin, destination, travel mode, and requested output fields. | Location disclosure requires an approved underlying action and minimum-data scope. Routing capability does not authorise dispatch. | Project access, licence, billing, provider retention, and production data-minimisation decisions remain unresolved. | Do not present route computation as vehicle-recovery consent. |
| `P3-EN-MODEL` | Provider-neutral advisory model capability only. | Process the minimum authorised Agent context and return advisory or structured output. | Model access does not create high-impact decision authority. Only minimum authorised context may be supplied under an approved model profile and purpose. | Provider training, logging, region, retention, and production approval must be governed before real customer data is used. | Do not present the model provider as an independent claim-service choice unless a future approved notice requires it. |
| `P3-EN-DOC-AWS` | Generic document/image extraction capability only. | Extract text, forms, tables, signatures, coordinates, or confidence from explicitly selected Evidence bytes. | No standalone permission. Evidence processing requires an approved purpose, selected material, and permitted data boundary. | IAM, region, storage, retention, deletion, and production authority remain unresolved. | No standalone service card; any future processing notice belongs to the approved evidence-processing action. |
| `P3-EN-CONVERSATION` | Generic chat/support capability only. | Carry the minimum Claim-linked messages, selected files, receipts, and delivery events between authorised users. | A conversation provider does not gain access to Claim content without an approved channel, identity mapping, visibility boundary, purpose, and data scope. | Procurement, region, provider retention, deletion, and production access remain unresolved. | Do not show a standalone provider-consent card for ordinary Northwind conversation. |
| `P3-EN-DAMAGE-AI` | Unavailable or labelled simulation only. | Analyse explicitly selected vehicle-damage images and the minimum related metadata, and return analytical output or confidence. | Vehicle-image analysis capability does not establish Northwind access, permitted data use, thresholds, or operational authority. | Commercial access, region, retention, deletion, result semantics, and production fitness remain unresolved. | Use unavailable/simulation wording. Do not represent Tractable or another damage-analysis vendor as a live Northwind service. |

## Preserve provenance and evidence status

Use this mapping to audit each P5 service boundary back to the accepted P3.3/P3.4 research record.
P3.1 source coordinates identify the public evidence, P3.2 disposition records the independent
challenge result and is preserved in P3.3, and the P3.4 closure coordinate identifies the gap
disposition that constrains Northwind use. Evidence status describes public-fact support separately
from Northwind production authority and access.

`blocked`, `unavailable`, and `simulation-only` in this table are research or access labels. They
are not `ExternalTaskOperationStatus` values and do not create a second Runtime lifecycle.

| P3 ID | P3.1 provenance | P3.2 disposition | P3.4 closure | Evidence and Northwind access status |
| --- | --- | --- | --- | --- |
| `P3-NZP-REPORT` | S01 | Accepted with qualification | `P3.4-G04` — `blocked` | Public reporting and result forms are supported. Direct Northwind read access is `unavailable`; claimant-supplied evidence is the baseline and synthetic evidence may be `simulation-only`. |
| `P3-NZP-TCR` | S02-S03 | Accepted with qualification | `P3.4-G01`, `P3.4-G04` — `blocked` | Public representative-request rules are supported. Direct Northwind request and response access is `unavailable`; manual handling remains authoritative. |
| `P3-VEHICLE-RECOVERY` | S04-S05 | Accepted with qualification | `P3.4-G02`, `P3.4-G04` — `blocked` | Distinct collision-towing and roadside forms are supported. Northwind dispatch and telemetry are `unavailable`; a configured demonstration may be `simulation-only`. |
| `P3-REPAIRER` | S06-S07 | Accepted with qualification | `P3.4-G03`, `P3.4-G04` — `blocked` | Repair roles and public result forms are supported. Northwind appointment and provider-status access are `unavailable`; supplied documents or synthetic records may provide `simulation-only` evidence. |
| `P3-ASSESSOR` | S06-S07 | Accepted with qualification | `P3.4-G03`, `P3.4-G04` — `blocked` | Assessment roles and public result forms are supported. Production provider-status access is `unavailable`; the controlled `vehicle_damage_assessment_routing` fixture remains `simulation-only`. |
| `P3-EMERGENCY-WORKS` | S06, S08 | Accepted with qualification | `P3.4-G04` — `blocked` | Public mitigation result forms are supported. Northwind contractor dispatch/status is `unavailable`; claimant- or staff-supplied work evidence is required. |
| `P3-FENZ-INFO` | S09-S10 | Accepted with qualification | `P3.4-G05`, `P3.4-G04` — `blocked` | Public request inputs and asynchronous outcomes are supported. Northwind authority and direct response access are `unavailable`; the exchange stays manual or `simulation-only`. |
| `P3-METSERVICE` | S11 | Accepted with qualification | `P3.4-G06`, `P3.4-G04` — `blocked` | Public report categories and result forms are supported. A selected Northwind product and purchased-report access are `unavailable`; a synthetic report may be `simulation-only`. |
| `P3-NHC` | S12-S14 | Accepted with qualification | `P3.4-G07A` — `resolved`; `P3.4-G07B`, `P3.4-G04` — `blocked` | The Home building/land versus contents boundary is resolved. Northwind partner exchange remains `unavailable`; a labelled insurer-mediated demonstration may be `simulation-only`. |
| `P3-CONTENTS-EVIDENCE` | S06 | Accepted with qualification | `P3.4-G07A` — `resolved`; `P3.4-G10`, `P3.4-G04` — `blocked` | Claimant-supplied contents evidence forms are supported. Direct Northwind retrieval is `unavailable`; claimant upload is the baseline and synthetic material may be `simulation-only`. |
| `P3-BROKER` | S07, S14 | Accepted with qualification | `P3.4-G08`, `P3.4-G04` — `blocked` | Public broker participation and bounded delegation are supported. A Northwind broker channel or delegation remains `unavailable`; a synthetic handoff may be `simulation-only`. |
| `P3-ACC-PROVIDER` | S15 | Accepted with qualification | `P3.4-G09`, `P3.4-G04` — `blocked` | The registered-provider ACC pathway is supported. Northwind diagnosis, lodgement, and status access are `unavailable` and must not be simulated as a Northwind action. |
| `P3-EN-MESSAGING` | S16 | Accepted with qualification | `P3.4-G11` — `blocked` | Generic messaging capability is supported. Northwind production access is `unavailable`; a controlled scenario may be `simulation-only`. |
| `P3-EN-DOC-AZURE` | S17 | Accepted with qualification | `P3.4-G11` — `blocked` | Generic asynchronous document analysis is supported. Northwind production access is `unavailable`; extracted candidates may be `simulation-only`. |
| `P3-EN-IDENTITY` | S18 | Accepted with qualification | `P3.4-G11` — `blocked` | Generic identity capability is supported. Northwind production tenant/procurement access is `unavailable`; repository identity contracts remain authoritative locally. |
| `P3-EN-ROUTES` | S19-S20 | Accepted with qualification | `P3.4-G11` — `blocked` | Generic route computation is supported. Northwind production project access is `unavailable`; route planning may be `simulation-only`. |
| `P3-EN-MODEL` | S21-S23 | Accepted with qualification | `P3.4-G11` — `blocked` | Generic provider inference capability is supported. Generic Northwind production use is `unavailable`; only an individually approved model profile may be configured. |
| `P3-EN-DOC-AWS` | S24 | Accepted with qualification | `P3.4-G11` — `blocked` | Generic document/image extraction is supported. Northwind production access is `unavailable`; machine-derived candidates may be `simulation-only`. |
| `P3-EN-CONVERSATION` | S25 | Accepted with qualification | `P3.4-G11` — `blocked` | Generic chat/support capability is supported. Northwind production access is `unavailable`; repository conversation fixtures remain separate development evidence. |
| `P3-EN-DAMAGE-AI` | S26-S27 | Unresolved for Northwind use | `P3.4-G11` — `blocked` | Vendor-described vehicle-damage analysis is supported only as a generic capability. Northwind production access is `unavailable`; Validation Prototype use is `simulation-only`. |

The authoritative research detail remains
`docs/research/third-party-stakeholder-unified-service-catalogue-and-implementation-brief.md`.
This compact mapping does not promote a public capability, a P3.2 disposition preserved in P3.3,
or a P3.4 research closure into Northwind authority, claimant consent, provider access, or
production readiness.

## Use final claimant copy fragments

This current engineering reference is the final P5 service-level contract.
`docs/research/third-party-service-claimant-consent-copy-draft.md` remains the
accepted P5.1 drafting and provenance input, but product and implementation
consumers use this document for the integrated authority and claimant-copy
boundary.

The following fragments are the final common claimant copy for the Validation
Prototype.

| Copy ID | Applies when | Final claimant copy |
| --- | --- | --- |
| `P5-COPY-RECORD` | Before an eligible Northwind send-permission choice. | **Already in your claim:** These details are already recorded in your Northwind claim. Giving permission below would allow only the listed details to be sent for this request; it does not change what is recorded in your claim. |
| `P5-COPY-CONSENT` | An approved and available Northwind send path requires claimant permission. | **Your choice:** Do you give Northwind permission to send the information listed above to **[recipient]** for **[purpose]**? Your permission covers only this service, this purpose, and this request. |
| `P5-COPY-REFUSE` | The claimant refuses the proposed send. | **You chose not to share:** We will not send this request. Information already recorded in your Northwind claim stays unchanged, and any claim steps that do not depend on this service can continue. We can ask a claims professional about another route. |
| `P5-COPY-WITHDRAW-UNSENT` | Permission is withdrawn before submission. | **Permission withdrawn:** We will not send this request. Information already recorded in your Northwind claim stays unchanged. |
| `P5-COPY-WITHDRAW-SENT` | Permission is withdrawn after the request may have reached the recipient. | **Withdrawal recorded:** The request may already have reached **[recipient]**, so we cannot promise that it or any copies can be cancelled, recalled, or deleted. A claims professional will check what can still be stopped and tell you what happens next. |
| `P5-COPY-RETENTION-BLOCKED` | A proposed real-data external send lacks approved production retention rules. | **How long it is kept:** Northwind has not approved a production retention period for this request or the recipient's copy. This service is not available for real claim data until both retention periods and deletion rules are confirmed. |
| `P5-COPY-MANUAL` | The claimant contacts the organisation directly and Northwind sends nothing. | **You contact them directly:** Northwind will not send your claim information to **[recipient]**. If you choose to contact them, their privacy notice and process apply. You can add the result to your Northwind claim later without restarting. |
| `P5-COPY-MANUAL-RETENTION` | Material from a claimant-led external path may later be added to the Claim. | **How long it is kept:** **[recipient]** decides how long it keeps information you give it. If you add the result to your Northwind claim, Northwind's claim-retention rules apply. Northwind's production retention period is not approved yet. |
| `P5-COPY-UNAVAILABLE` | Access, authority, recipient, data use, or another required production condition is not approved. | **This service is not available through Northwind:** Its access and data-sharing rules have not been approved. I can help you use the available manual option or arrange support. |

`P5-COPY-CONSENT` is never sufficient by itself. It is eligible only when the
recipient, purpose, disclosed fields, current Northwind authority, claimant
consent scope, provider path, and applicable retention boundary are all known
and authorised.

## Map claimant copy to authority

The P5.1 draft remains the upstream wording and provenance record. The final
common fragments are integrated into this document above. This contract
determines when each fragment is eligible to appear.

`P5-COPY-CONSENT` must not be shown for an unavailable, manual-only, or
research-only service. A consent prompt does not turn an unsupported service
into an authorised one.

For manual claimant-led services, Northwind states that it sends nothing and
uses the manual copy. For unsupported Northwind paths, the unavailable copy is
used. For the controlled assessor fixture, the complete record, retention,
consent, refusal, and withdrawal copy may be demonstrated only within the
synthetic Validation Prototype boundary.

The P5.1 non-blocking wording improvement is adopted when the Police-reporting
purpose is repeated: use "Report a non-emergency incident or update to New
Zealand Police" so the claimant, rather than Northwind, is unambiguously the
actor.

## Preserve implementation boundaries

This contract introduces no API, Runtime, persistence, frontend, fixture,
provider, or continuous-integration change.

The only current implemented external-service identity recognised by this P5
mapping is `vehicle_damage_assessment_routing`, with requested action
`vehicle_damage_assessment` and the six disclosure fields listed above. That
path is a controlled fixture, not proof of a production assessor integration.

All other P3 service and platform identifiers remain research coordinates.
They do not reserve Runtime service identities or imply future implementation.

## Complete cross-review

Issue #594 requires two distinct review perspectives. LLL263 verifies claimant
clarity and complete service-identifier coverage. jxu316-arch verifies
Northwind authority, auditability, record/send separation, refusal,
withdrawal, retention, and fail-closed behaviour.

Any omission discovered by that review is handed to Issue #595. No omission is
silently defaulted into permission or production capability.

## Record the P5.4 gap closure

Issue #595 audits the merged contract for service-level shared-data and consent-copy
omissions. The following dispositions are documentation audit results, not Runtime
states or new contract identifiers.

| Audit area | Disposition | Contract evidence |
| --- | --- | --- |
| Claim-participant purpose and minimum-data copy | Resolved | All 12 P3 claim-participant rows provide claimant-readable service, purpose, and shared-data wording before the raw contract mapping. |
| Enabling-platform processing scope | Resolved | All eight `P3-EN-*` rows state the bounded processing purpose and candidate data while prohibiting a standalone consent card. |
| Service and Runtime identifier alignment | Resolved | All 20 accepted P3 identifiers retain their P3 provenance. Only `vehicle_damage_assessment_routing`, action `vehicle_damage_assessment`, and its six permitted fields are executable. |
| Consent-state copy | Resolved | The nine `P5-COPY-*` fragments cover record/send separation, consent, refusal, both withdrawal moments, blocked retention, manual contact, manual retention, and unavailable service handling. |
| Production privacy and access conditions | Explicitly blocked | Each unresolved Northwind recipient, authority, retention, expiry, access, or data-use condition results in a manual, `unavailable`, or `simulation-only` rule. It never defaults to permission or a live capability. |

This closure is governed-document evidence only. It does not claim an API,
authorisation, integration, Runtime, browser-route, or full-journey result.
