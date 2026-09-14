# Sprint 4 third-party integration forms

This research contract selects the third-party operating forms that Sprint 4 may honestly present in the motor, home, and contents First Notice of Loss journeys. It reuses the existing P3 catalogue and consent/shared-data contract. It does not create a competing catalogue, provider integration, API, persistence model, or request-state vocabulary.

Issue #775 owns this selection and implementation handoff. Issue #776 owns the canonical external-service lifecycle registry. Issue #777 consumes both outputs.

## Decision summary

The selected Sprint 4 capabilities are:

| P3 ID | Scenario | Capability status | Recommended access form |
| --- | --- | --- | --- |
| `P3-ASSESSOR` | Motor; Home | Existing motor path is `simulation-only`; production access is `unavailable` | Governed external request only for the existing controlled motor fixture; staff/manual otherwise |
| `P3-REPAIRER` | Motor; Home | `manual`; Northwind appointment/status access is `unavailable` | Explanatory service card plus claimant-led or staff-assisted contact |
| `P3-NZP-REPORT` | Motor collision/theft; Contents theft | `manual` | Official New Zealand Police 105 link/phone guidance |
| `P3-NZP-TCR` | Motor collision | `manual` | Official request guidance plus Agent-assisted preparation or staff handoff |
| `P3-VEHICLE-RECOVERY` | Motor collision | `manual`; Northwind dispatch is `unavailable` | Safety/drivability guidance plus claimant-led or staff-assisted recovery |
| `P3-EMERGENCY-WORKS` | Home | `manual`; Northwind dispatch/spending authority is `unavailable` | Safety guidance first, then claimant-led or staff-assisted urgent work |
| `P3-NHC` | Home natural hazard | `manual`; direct Northwind exchange is `unavailable` unless separately proven | Explanatory service card plus insurer/staff-mediated coordination |
| `P3-CONTENTS-EVIDENCE` | Contents | `manual` | Agent-assisted preparation plus claimant retrieval and existing Evidence upload |

No selected capability is a production third-party integration. The only implemented external-service identity remains `vehicle_damage_assessment_routing` with action `vehicle_damage_assessment`, and it remains a controlled fixture.

Public service existence is not Northwind procurement. Credentials are not authority. Authority does not replace claimant consent. Consent does not create provider access. A fixture is not a live provider result.

## Selected service decisions

### P3-ASSESSOR

- **Scenario:** Motor collision; professional assessment in Home where applicable.
- **Sources:** Existing P3 sources `S06-S07`: ICNZ *Making a Claim* and FMA *Weather Events Claims Insights*.
- **Real service:** Professional damage/loss assessment, scope, request for more information, or delay/status result.
- **Current form:** Motor controlled fixture only; other assessor paths have no implemented Runtime identity.
- **Required input:** For the existing fixture, exactly `claim_id`, `external_claim_id`, `authorisation_ref`, `claimant_consent_ref`, `requested_action`, and `location.region`.
- **Observable output:** Controlled routing result/provider reference; any later result remains separate from verified Claim facts until governed verification/write-back.
- **Authority and consent:** Current Northwind routing authority plus matching claimant consent are required. No production assessor appointment authority is established.
- **Minimum disclosure:** Only the six published fields above. Damage images/descriptions are not silently added.
- **Limitation:** The fixture does not contact a production assessor, decide cover, approve repairs, guarantee timing, or prove production provider status access.
- **Status:** `simulation-only` for the motor fixture; production use `unavailable`.
- **Recommended form:** Governed external request for the existing fixture; staff/manual path otherwise.
- **Rejected form:** Generic “Book assessor” or real-provider “Assessment complete”. That would invent provider identity, procurement, appointment authority, and production status access.
- **Next owner:** Runtime/backend while the controlled operation is in flight; staff when a real provider or professional decision is required.
- **Write-back:** Preserve provider/result provenance, verify the result, then use existing governed Evidence/Claim rules.

### P3-REPAIRER

- **Scenario:** Motor collision and Home property repair.
- **Sources:** Existing P3 sources `S06-S07`.
- **Real service:** Inspection, quote/scope, repair, invoice, and progress/completion evidence. Claimant-selected and insurer-authorised paths are distinct.
- **Current form:** No generic Runtime identity; claimant/manual or staff-assisted only.
- **Required input:** Existing damage/loss information and explicitly selected Evidence. Current mappings cover `claim_id`, applicable `vehicle.damage_description` or `property.affected_areas`, `loss.description`, and selected `Evidence.evidence_id`. Appointment/contact/approval remain unmapped.
- **Observable output:** Quote, scope, invoice, appointment information, or progress/completion evidence when later supplied by the claimant or staff.
- **Authority and consent:** No generic Northwind repair appointment, repair approval, disclosure, or provider-status authority. No Northwind send occurs in the selected manual form.
- **Minimum disclosure:** Northwind sends no claim data to a repairer in the selected manual form. Only claimant/staff-supplied material later enters the existing Evidence boundary.
- **Limitation:** No verified Northwind network, appointment authority, repair approval, live status feed, provider SLA, or production retention contract is established.
- **Status:** `manual`; Northwind appointment/status access `unavailable`.
- **Recommended form:** Explanatory service card plus claimant-led contact; staff handoff where insurer-authorised appointment is required.
- **Rejected form:** “Book repair”, “Repair authorised”, or invented live repair progress.
- **Next owner:** Claimant for claimant-selected repairer; claims professional for insurer-authorised appointment or repair authority.
- **Write-back:** Quote/scope/invoice may become Evidence; they do not approve cover, liability, or expenditure.

### P3-NZP-REPORT

- **Scenario:** Motor collision/theft, Contents theft, and other losses where Police reporting is relevant.
- **Sources:** Existing P3 source `S01`, New Zealand Police 105 / All online options.
- **Real service:** Claimant-led non-emergency reporting through 105 online/phone. Emergency situations use 111. Once a reference exists, Police provide a case/report update route.
- **Current form:** Official claimant-led channel; no Northwind submission/read Runtime identity or API.
- **Required input:** The Police channel determines the claimant-supplied incident/reporting information. Northwind does not define or send a substitute provider payload.
- **Observable output:** Police acknowledgement/reference and later claimant-supplied Police material where available.
- **Authority and consent:** No evidence establishes Northwind authority to submit a 105 report or read its status. Northwind external-send consent is not applicable because Northwind sends nothing.
- **Minimum disclosure:** Northwind sends no claim data to Police in the selected form. The claimant decides what to provide through the official Police process.
- **Limitation:** Northwind cannot promise Police acceptance, response time, case progress, report availability, or live status visibility.
- **Status:** `manual`.
- **Recommended form:** Official 105 link/phone guidance.
- **Rejected form:** Northwind “Submit Police report” or status claiming Northwind submitted/read the report.
- **Next owner:** Claimant until an official reference/result is obtained; staff only when later claim handling requires review of supplied material.
- **Write-back:** Existing Police-reference Claim field where permitted; Police documents may be Evidence.

### P3-NZP-TCR

- **Scenario:** Motor collision where a held Traffic Crash Report is needed later in the claim.
- **Sources:** Existing P3 sources `S02-S03`, official Police TCR request and representative path.
- **Real service:** A person or authorised representative may request a held Traffic Crash Report. Release is not guaranteed.
- **Current form:** Claimant-led or staff-prepared manual request only; no standing Northwind TCR Runtime/provider integration.
- **Required input:** Location/time, Police file number where known, request reason, identity, and representative-authority evidence may be required depending on requester.
- **Observable output:** Request decision and, where releasable, a TCR supplied through the official pathway.
- **Authority and consent:** Public representative rules do not establish standing claimant-specific Northwind authority. A future staff representative request would require real request-specific authority evidence.
- **Minimum disclosure:** Northwind sends no data in the selected claimant-led form. Agent/staff preparation may explain official requirements but must not transmit identity/authority material through an unapproved integration.
- **Limitation:** Release may be withheld, additional identity/authority evidence may be required, and Northwind has no guaranteed response time or direct status/read access.
- **Status:** `manual`.
- **Recommended form:** Official request guidance plus Agent-assisted preparation; staff handoff where an authorised representative route is needed.
- **Rejected form:** Automatic TCR retrieval or API inferred from the public request page.
- **Next owner:** Claimant for self-request; authorised staff only where real representative authority exists.
- **Write-back:** Returned TCR may become Police-report Evidence; receipt remains separate from verified Claim facts.

### P3-VEHICLE-RECOVERY

- **Scenario:** Motor collision with an unsafe or undriveable vehicle.
- **Sources:** Existing P3 sources `S04` AA Insurance collision guidance and `S05` AMI Roadside Rescue.
- **Real service:** Collision towing/recovery to move an unsafe vehicle to a safe location or repairer. Collision recovery and roadside breakdown assistance are not interchangeable.
- **Current form:** Safety/drivability guidance with claimant-led or staff-assisted manual coordination; no Northwind dispatch Runtime identity.
- **Required input:** The manual journey may use existing vehicle location/condition, registration, drivability, damage description, and claim context to help the claimant/staff choose the next step. Provider eligibility, contact, safe-access, destination, and dispatch fields remain unapproved for a governed Northwind request.
- **Observable output:** Claimant/staff-observed towing/recovery outcome, provider decline/unavailability, or later towing receipt/material.
- **Authority and consent:** No verified Northwind recovery network, dispatch authority, or telemetry. Northwind external-send consent is not applicable because Northwind sends nothing in the selected form.
- **Minimum disclosure:** Northwind sends no claim data to a recovery provider in the selected manual form.
- **Limitation:** No provider eligibility, dispatch SLA, destination control, telemetry, provider acknowledgement, or reimbursement/coverage decision is established.
- **Status:** `manual`; Northwind dispatch `unavailable`.
- **Recommended form:** Drivability/safety guidance plus claimant-led or staff-assisted recovery.
- **Rejected form:** Reusing roadside rescue for a collision or showing “Tow dispatched”.
- **Next owner:** Claimant or claims professional depending on the applicable insurer/manual route.
- **Write-back:** Towing receipt/material may become Evidence. Towing does not imply claim acceptance or repair approval.

### P3-EMERGENCY-WORKS

- **Scenario:** Home loss requiring urgent mitigation to reduce continuing damage or make the property safe.
- **Sources:** Existing P3 source `S06` ICNZ and current NHC urgent-repair guidance used by the P3 catalogue.
- **Real service:** Urgent mitigation to make property safe, sanitary, secure, or weathertight.
- **Current form:** Safety guidance plus claimant-arranged or staff-assisted manual handling; no Northwind contractor dispatch Runtime identity.
- **Required input:** Existing candidate mapping covers `claim_id`, `property.address`, `property.affected_areas`, `property.ongoing_risk`, `property.habitable`, `loss.description`, `requested_action`, and selected Evidence. Contractor identity, safe access, scope, contact, and spending authority remain unmapped.
- **Observable output:** Claimant/staff-observed completion or inability to proceed, plus later work record, photos, invoice, or contractor material where supplied.
- **Authority and consent:** No generic contractor dispatch, spending, or reimbursement authority. Safety guidance must not wait for consent. No Northwind send occurs in the selected manual form.
- **Minimum disclosure:** Northwind sends no claim data to a contractor in the selected manual form.
- **Limitation:** No provider network, dispatch SLA, spending authority, reimbursement promise, approved work scope, or production provider status feed is established.
- **Status:** `manual`; dispatch/spending authority `unavailable`.
- **Recommended form:** Safety guidance first, then claimant-led or staff-assisted urgent work.
- **Rejected form:** Delaying safety for consent, auto-booking work, or auto-approving reimbursement.
- **Next owner:** Claimant for immediate safe action; claims professional where insurer authority is needed.
- **Write-back:** Work photos/invoice/contractor record may become Evidence; mitigation evidence is not a coverage decision.

### P3-NHC

- **Scenario:** Home natural-hazard damage affecting eligible residential building/land pathways.
- **Sources:** Existing P3 sources `S12-S14`, Natural Hazards Commission public claims guidance.
- **Real service:** For most partner-insurer claims, the private insurer is the main point of contact. NHC directly manages defined exceptions.
- **Current form:** Explanatory/insurer-mediated coordination. Northwind partner status and technical exchange are unverified.
- **Required input:** Existing candidate mapping may use `claim_id`, `policy.policy_number`, `property.address`, incident type/time/description, `loss.description`, and selected Evidence. Partner identity and routing remain unmapped.
- **Observable output:** Claim-manager update, assessment/specialist report, scope of works, settlement advice, or other material supplied through the insurer/NHC process.
- **Authority and consent:** Public NHC guidance does not prove Northwind partner status, credentials, or direct exchange authority. No new Northwind-to-NHC send is selected by this brief.
- **Minimum disclosure:** Northwind sends no data through a new NHC integration in the selected manual/insurer-mediated form.
- **Limitation:** Northwind-specific partner status, credentials, routing, technical exchange, SLA, retention, and status feed are unverified; NHC relevance does not itself determine Northwind policy cover.
- **Status:** `manual`; direct Northwind exchange `unavailable` unless separately proven.
- **Recommended form:** Explanatory service card plus insurer/staff-mediated coordination.
- **Rejected form:** “Send to NHC”, “NHC accepted”, or applying building/land NHCover to generic contents evidence.
- **Next owner:** Northwind claims professional/private insurer unless the claimant is in a published direct-NHC exception.
- **Write-back:** Supplied specialist/assessment/scope documents may become Evidence; NHC relevance does not decide policy coverage.

### P3-CONTENTS-EVIDENCE

- **Scenario:** Contents loss where proof of ownership, purchase, condition, repair, or value is needed.
- **Sources:** Existing P3 source `S06`, ICNZ *Making a Claim*.
- **Real service:** Claimant obtains receipt, statement, service record, valuation, or similar proof from a retailer, bank, manufacturer, service centre, valuer, or other external source.
- **Current form:** Claimant-led retrieval plus the existing Evidence upload path; no generic Northwind direct-retrieval Runtime identity.
- **Required input:** The claimant identifies the affected contents item and the type of supporting material needed. Northwind does not define a generic direct-provider request payload.
- **Observable output:** Receipt, statement, service record, valuation, other supplied proof, or inability to obtain the requested material.
- **Authority and consent:** No generic Northwind direct-retrieval relationship. Northwind external-send consent is not applicable because Northwind sends nothing.
- **Minimum disclosure:** Northwind sends no claim data to the external source in the selected form.
- **Limitation:** External sources may not retain or release the requested material; Northwind has no generic provider identity, matching key, response SLA, direct retrieval authority, or live status access.
- **Status:** `manual`.
- **Recommended form:** Agent-assisted preparation plus claimant retrieval and existing Evidence upload.
- **Rejected form:** Automatic retailer/bank/manufacturer retrieval without provider identity, matching, authority, and consent.
- **Next owner:** Claimant while obtaining the material; staff if an unresolved evidence gap requires professional follow-up.
- **Write-back:** Existing item-to-Evidence association; receipt is not automatic fact confirmation.

## Worked collision journey

The collision example follows this implementation-facing sequence.

1. **Claimant account.** “I was in a crash; the front of my car is badly damaged and I have photos” does not establish drivability, injury status, professional assessment, repair authority, Police reporting, or coverage.
2. **Safety first.** If injury, immediate danger, or emergency help may be required, ordinary intake pauses. Show appropriate emergency guidance. Keep 111 emergency help distinct from 105 non-emergency Police reporting.
3. **Drivability.** If the vehicle is not safely drivable, explain collision recovery and use `P3-VEHICLE-RECOVERY` in its manual/staff-assisted form. Do not claim Northwind dispatched a tow. If safely drivable, continue without inventing a recovery task.
4. **Photo Evidence.** Photos enter the existing Evidence path. They may support proposed facts or professional review, but they are not an assessor decision and do not authorise repair or decide cover.
5. **Professional assessment.** Where appropriate, the existing controlled motor assessor path may be used only with its current authority, consent, and exact disclosure scope. It remains labelled simulation-only. An assessor result does not decide cover and does not approve/book repair. Real assessors outside that identity remain staff/manual.
6. **Repairer.** Repairer inspection/quote/repair is separate from assessment. Claimant-selected repairers may be contacted manually. Insurer-authorised appointment belongs to claims-professional authority. Never translate “assessment indicates repair is needed” into “repair booked”.
7. **Police.** Emergencies use 111. Non-emergency reporting uses the official 105 route. Northwind may explain the route but does not claim submission. A later Police reference/document may enter Claim/Evidence. A TCR follows the official request/authority route.
8. **Next owner.** Claimant owns manual official/external routes; claims professionals own insurer authority/provider choice; the controlled assessor task owns only an actual in-flight fixture operation; Northwind reconciliation owns `unknown_outcome`. `accepted` or `assigned` never means completed, and result receipt never means verified/written back.

## Canonical lifecycle boundary

Issue #775 defines no second external-service state machine. Issue #777 must consume #776.

The #776 contract owns:

- Consent/preparation: `consent_required`, `authorised`, `prepared`, `submitting`.
- Provider operation: `accepted`, `queued`, `assigned`.
- Failure/recovery: `retryable_failure`, `terminal_failure`, `unknown_outcome`.
- Separate result stages: result received, result verified, written back.
- Capability provenance/access form: configured, simulated, manual, unavailable.

Manual link/phone/guidance paths do not create fake ExternalTask records. #776 is still open at this evidence point, so this brief uses only the vocabulary already published in the #776 Issue contract and introduces no local alias.

## Separate research gaps from engineering gaps

Research/authority gaps that code must not invent:

- Production assessor provider/procurement/retention/SLA.
- Northwind repairer network, appointment authority, and live repair status.
- Northwind collision-recovery network, dispatch authority, and telemetry.
- Northwind Police 105 submission/read authority.
- Standing claimant-specific Northwind representative authority for TCR.
- Generic emergency-contractor dispatch/spending authority.
- Northwind NHC partner/technical-exchange status.
- Generic direct retailer/bank/manufacturer contents-evidence retrieval.

Issue #775 justifies **no new provider-specific Claim Context business field**.

Future automation-only details belong in the external-task/request/provider-adapter boundary unless separate product evidence makes them durable Claim facts:

| Future capability | Required engineering data | Contract location |
| --- | --- | --- |
| Production assessor | Provider identity, approved retention/data-use, provider status/result mapping, credentials/configuration | Integration configuration + provider adapter/external-task metadata |
| Repairer | Provider identity, service location, requested appointment/quote/scope, contact path, insurer-authority reference | External-task request/provider adapter |
| Recovery | Recovery provider, destination, eligibility/contact/safe-access, dispatch evidence | External-task request/provider adapter |
| TCR representative request | File number where known, reason, representative-authority evidence reference, request channel | External-task request/provider adapter |
| Emergency works | Contractor identity, work scope, safe-access data, spending/approval authority reference | External-task request/provider adapter |
| NHC partner exchange | Verified partner/routing identity, approved disclosure/retention, external reference/status mapping | Integration configuration + external-task/provider adapter |

The existing assessor identity/action/disclosure/authority/consent/idempotency/delivery/failure/result contracts are reused unchanged.

## Handoff requirements for #777

### Backend

- Reuse #776; do not encode service-specific status vocabularies.
- Keep manual capabilities out of external-task persistence unless Northwind actually owns a governed request.
- Reuse the assessor fixture's current authority/consent/idempotency/audit boundary.
- Preserve delivery evidence and reconcile `unknown_outcome` before another side effect.
- Keep third-party results separate from verified Claim facts.
- Reject cross-Claim, stale-authority, changed-payload, and unsupported-capability requests.
- Do not convert a P3 research ID into an executable `service_identity` without a reviewed engineering contract.

### Agent/runtime

- Select only registry-backed capabilities.
- Explain access form and limitation.
- Distinguish assessment, repair, recovery, Police reporting, and NHC coordination.
- Ask for consent only for an actually approved Northwind send.
- Agent proposes; Runtime decides whether a real side effect is allowed.
- Treat `unknown_outcome` as reconciliation, not ordinary retry.
- Generate claimant wording from the actual execution result.

### Claimant frontend

- Render service purpose, access form, limitation, pending owner, and next action.
- Use official link/phone presentation for Police/manual paths.
- Label the assessor fixture as simulation-only.
- Keep accepted/queued/assigned separate from completed.
- Keep result received separate from verified/written back.
- Do not present manual guidance as a live Northwind integration.
- Do not show repair-booking or Police-submit unless a later backend contract publishes an authorised capability.

### Workbench

- Show the same authoritative capability/operation state with additional authorised staff context.
- Show who owns the next step.
- Preserve authority, consent, delivery evidence, failure/recovery, provider/result provenance, and verification where an ExternalTask exists.
- Staff visibility does not grant disclosure or provider-appointment authority.

## Source matrix

The selected public sources were rechecked on 2026-09-14.

| Source ID | Public source | Supports | Does not prove |
| --- | --- | --- | --- |
| `S01` | New Zealand Police — All online options / 105 | Non-emergency 105 reporting and case/report update route | Northwind submission/read API |
| `S02-S03` | New Zealand Police — Request a Traffic Crash Report | TCR availability and representative-authority requirements | Standing Northwind authority or unrestricted API |
| `S04` | AA Insurance — collision guidance | One insurer's towing/repair pathway and drivability distinction | Northwind cover/network/dispatch |
| `S05` | AMI Roadside Rescue | Roadside-breakdown boundary and accident/collision exclusion | Collision recovery or Northwind access |
| `S06` | ICNZ — Making a Claim | House/contents/motor evidence forms and claims context | Northwind provider contracts |
| `S07` | FMA — Weather Events Claims Insights | Third-party roles, insurer oversight, delegated-authority boundaries | Northwind provider relationship/API |
| `S12-S14` | Natural Hazards Commission claims guidance | Insurer point-of-contact model, assessment/specialist roles, urgent-work boundary | Northwind partner/technical integration |

## Unsafe interpretations explicitly rejected

- Public provider/service page is not a Northwind provider account.
- Provider category is not provider identity.
- Repair recommendation is not repair appointment.
- Assessor result is not coverage or repair approval.
- Police 105 link is not a Police report submitted by Northwind.
- Claimant Police reference is not live Police status access.
- Roadside assistance is not collision recovery.
- NHC public partnership model is not proof Northwind is an NHC partner.
- Consent checkbox does not create provider access or authority.
- Fixture acknowledgement is not production-provider acknowledgement.
- `accepted` or `assigned` does not mean completed.
- Result received does not mean result verified/written back.
- Manual, unavailable, and simulation-only do not count as successful live integrations.

## Acceptance mapping

| #775 acceptance criterion | Evidence |
| --- | --- |
| Every selected row cites source, scenario, service form, authority, consent, minimum disclosure, output, limitation, and capability status | Decision summary and selected service decisions |
| Each row has a recommended access form and rejected/unsafe alternative | Selected service decisions |
| Collision example includes assessor, repairer, Police without unverified access | Worked collision journey |
| Capability is separated from procurement, credentials, authority, production readiness | Decision summary, authority boundaries, unsafe interpretations |
| Lifecycle uses #776 and introduces no second vocabulary | Canonical lifecycle boundary |
| Frontend/backend/Agent consumers can identify implementation work | Engineering gap table and #777 handoff |
| Unknown/manual/unavailable/simulation-only remain explicit | Decision summary, service decisions, unsafe interpretations |

## Follow-up boundary

Issue #775 stops at research-backed selection and implementation contract.

Issue #777 may implement only the forms selected here and the lifecycle published by #776. A later provider/procurement decision may expand one service from manual/unavailable to a governed external request, but that requires fresh authority, consent, provider-access, disclosure, retention, failure/recovery, and provenance evidence. It must not be inferred from this document.
