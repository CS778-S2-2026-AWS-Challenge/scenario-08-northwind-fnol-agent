# P3.3 Unified Third-Party Service Catalogue and Implementation Brief

This research record is the final P3.3 delivery for Issue #588. It reconciles the accepted P3.1
stakeholder/service research with the accepted P3.2 independent challenge into one implementation-facing
catalogue for motor, home, and contents First Notice of Loss (FNOL) journeys in New Zealand.

This document is governed research evidence only. It does not select providers, create Northwind
authority, define a new application state machine, or claim procurement, credentials, approved
personal-data use, live provider access, or production readiness.

## Reconciliation authority

The upstream fact authority is the final P3.1 record in
`docs/research/third-party-stakeholder-service-research.md`. Its stable `P3-*` identifiers and
`S01-S28` source coordinates remain the research source of truth. The final P3.2 record in
`docs/research/third-party-stakeholder-service-independent-challenge-review.md` supplies the
independent disposition and challenge boundary for each P3.1 entry.

The P3.3 reconciliation preserves four separations:

- Claim-journey participants are not enabling platforms.
- Public service or vendor capability is not Northwind authority, procurement, credentials, or
  approved data use.
- External request acknowledgement, provider result, verified evidence, and Northwind Claim State
  are different events and authorities.
- Research words such as "pending", "completed", "unavailable", or "disputed" are descriptive
  service/evidence conditions only. They are not new Runtime, API, or persistence states.

Current `SPEC/` and engineering contracts remain authoritative for product and implementation
behaviour. This research can preserve an unknown or unsafe boundary; it cannot override those
contracts.

## Unified service catalogue

The catalogue covers all 12 final P3.1 claim-journey participant identifiers and all eight final
P3.1 enabling-platform identifiers.

| P3.1 ID | Layer | Stakeholder / capability | Scenario | P3.2 disposition | Service or access form | Primary inputs | Observable output / evidence | Authority / consent boundary | Provenance | Validation Prototype boundary |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `P3-NZP-REPORT` | Claim participant | New Zealand Police reporting | Motor / theft | Accepted with qualification | Claimant uses Police 105 or another appropriate Police channel | Incident details required by the selected Police channel | Report acknowledgement or Police reference; later update where available | No source establishes Northwind submission/read access; emergencies use 111 | S01 | Guidance or claimant-led reporting only unless a separately authorised Northwind path exists |
| `P3-NZP-TCR` | Claim participant | Traffic Crash Report request | Motor | Accepted with qualification | Person or authorised representative requests the held report | Location/time, Police file number when known, reason, identity and representative authority evidence | Request decision and, when releasable, TCR | Representative authority matters; no standing Northwind authority, guaranteed release, or unrestricted API is established | S02-S03 | Claimant/manual handling until Northwind authority and request evidence are established |
| `P3-VEHICLE-RECOVERY` | Claim participant | Vehicle recovery / towing | Motor | Accepted with qualification | Claimant-arranged, staff-arranged, insurer-network, or guidance-only | Vehicle location/condition plus any eligibility and safe-access details | Transport/assistance evidence, decline, or unavailability where observable | Roadside breakdown membership is not collision recovery; canonical Northwind arrangement is unresolved | S04-S05 | Preserve operating form as unresolved; do not imply configured dispatch |
| `P3-REPAIRER` | Claim participant | Repairer / repair quotation | Motor / Home | Accepted with qualification | Claimant-selected or insurer-authorised/network repair path | Damage evidence, vehicle/property details, referral/appointment data, relevant approval | Appointment, quote/scope, invoice, progress/completion evidence, or inability to proceed | Appointment and approval authority depend on the path; competitor networks do not prove Northwind access | S06-S07 | Distinguish claimant-selected and insurer-authorised paths; no live provider integration is claimed |
| `P3-ASSESSOR` | Claim participant | Assessor / adjuster / engineer / specialist | Motor / Home | Accepted with qualification | Usually insurer-appointed professional work, physical or remote | Claim context, damage evidence, location, appointment and bounded scope | Inspection, assessment/specialist report, request for information, or delay | Northwind appointment authority, provider eligibility, observable status, and service level remain unresolved | S06-S07 | Staff/manual task boundary until an authorised provider path is established |
| `P3-EMERGENCY-WORKS` | Claim participant | Emergency contractor / tradesperson | Home | Accepted with qualification | Claimant or insurer arranges urgent mitigation | Property location, hazard/damage, urgency, safe access, requested mitigation and approval where needed | Safe/sanitary/secure/weathertight mitigation and work evidence where available | Public guidance does not define a Northwind contractor network, spending authority, or reimbursement rule | S06, S08 | Surface safety/mitigation need; provider dispatch remains manual or simulation-only unless authorised |
| `P3-FENZ-INFO` | Claim participant | Fire and Emergency New Zealand information | Home / fire | Accepted with qualification | Official Information Act or Privacy Act information request | Requester identity/contact, specific information/timeframe, and authority where required | Acknowledgement, decision, released information, extension, transfer, charge, or refusal | Requests are asynchronous and may require identity/authority evidence; no insurer API is established | S09-S10 | Claimant/manual request or labelled simulation; not a synchronous FNOL completion dependency |
| `P3-METSERVICE` | Claim participant | MetService historical weather evidence | Home | Accepted with qualification | Public information or formal reporting product | Date, location and weather/event question or report type | Historical report or other weather evidence where obtained | S11 supports report categories and published starting prices, not a Northwind-selected product, final/custom quote, licence, procurement, or access | S11 | Evidence support only; selected product/access remains unresolved and may be simulated |
| `P3-NHC` | Claim participant | Natural Hazards Commission Toka Tū Ake / NHCover | Home natural hazard | Accepted with qualification | Primarily insurer-mediated residential building/land pathway; limited direct-NHC paths also exist | Natural-hazard event/damage, insured property/land details and requested supporting material | Claim progress, assessment, information request, acceptance/non-acceptance explanation, or specialist evidence where applicable | Generic contents cover is not supported; Northwind partner status and exact workflow are unresolved | S12-S14 | Keep Home building/land pathway separate from contents; no Northwind integration is assumed |
| `P3-CONTENTS-EVIDENCE` | Claim participant | Retailer, bank, manufacturer, service centre, or valuer evidence | Contents | Accepted with qualification | Claimant normally retrieves/uploads evidence | Item identity plus receipt, statement, serial/service record, valuation or other proof | Supporting document, alternative evidence, or unavailable record | Direct Northwind retrieval requires separately proven service access and disclosure authority | S06 | Claimant retrieval/upload is the safe baseline |
| `P3-BROKER` | Claim participant | Broker or authorised intermediary | Cross-cutting | Accepted with qualification | Broker coordinates with insurer under claimant authorisation or bounded delegation | Claimant authority, policy/incident context and insurer-required information | Claim coordination, communication relay, or referral | Broker participation and delegated authority are not universal and must be explicit | S07, S14 | Authority-boundary participant by default; actionable Northwind service remains unresolved |
| `P3-ACC-PROVIDER` | Claim participant | Registered health provider / ACC injury pathway | Injury support adjacent to FNOL | Accepted with qualification | Eligible provider lodges an ACC claim with the patient | Patient identity/contact, accident/injury details, provider details and patient declaration/consent | Lodgement, request for information, later ACC cover decision | Does not authorise Northwind to diagnose, lodge ACC claims, or decide ACC/insurance coverage | S15 | Adjacent authority-boundary example only unless separately authorised |
| `P3-EN-MESSAGING` | Enabling platform | Twilio messaging / verification | Cross-cutting | Accepted with qualification | Authenticated SaaS messaging/verification APIs | Recipient/sender/content/configuration with minimum necessary claim data | Message/verification identity and delivery/verification evidence | Procurement, sender setup, communication basis, opt-out handling, credentials and allowed content remain unresolved | S16 | Generic capability only; live Northwind use unavailable until approved |
| `P3-EN-DOC-AZURE` | Enabling platform | Azure AI Document Intelligence | Evidence processing | Accepted with qualification | Authenticated asynchronous document analysis | Uploaded evidence document | Machine-extracted text/fields/tables/confidence and analysis result | Subscription, region, retention, approved data use and claim-fact authority remain unresolved | S17 | Machine-derived evidence candidate only; live Northwind use unavailable until approved |
| `P3-EN-IDENTITY` | Enabling platform | Auth0 identity and access management | Cross-cutting | Accepted with qualification | Hosted identity protocols/APIs | Credentials or identity assertions | Authenticated identity/session claims | Authentication proves identity, not authority to disclose data or perform a claim action; tenant/procurement unresolved | S18 | Generic capability only; no production identity migration is claimed |
| `P3-EN-ROUTES` | Enabling platform | Google Maps Platform Routes | Motor / Home support | Accepted with qualification | Authenticated route computation | Origin, destination, travel mode and requested output fields | Route, distance and duration | Routing is infrastructure, not a recovery provider; project access, licence, billing and data-minimisation decisions are unresolved | S19-S20 | May be simulated for planning; no Northwind project/provider dispatch is claimed |
| `P3-EN-MODEL` | Enabling platform | OpenAI API / Amazon Bedrock inference | Cross-cutting | Accepted with qualification | Provider-neutral model gateway to an approved provider profile | Minimum-necessary model context | Generated or structured advisory output | Account/model, region, retention, personal-data scope, evaluation and production approval are separate governance decisions | S21-S23 | Advisory capability only; no high-impact decision authority or generic production-access claim |
| `P3-EN-DOC-AWS` | Enabling platform | Amazon Textract | Evidence processing | Accepted with qualification | Document/image extraction service | Supported evidence images/documents | Extracted text, handwriting, forms, tables, signatures, coordinates and confidence | Region, IAM, storage, retention, supported claim-document set and production authority remain unresolved | S24 | Machine-derived evidence candidate only; live Northwind use unavailable until approved |
| `P3-EN-CONVERSATION` | Enabling platform | Sendbird chat / support tooling | Cross-cutting | Accepted with qualification | Client/server chat APIs and webhooks | Claim-linked message/file content allowed by the governed visibility boundary | Channels, messages, files, receipts, retrieval and event evidence | Identity mapping, claimant/staff visibility, retention, procurement and live access remain unresolved | S25 | Generic capability only; no Northwind conversation provider is established |
| `P3-EN-DAMAGE-AI` | Enabling platform / claim-domain tool | Tractable vehicle-damage analysis | Motor | Unresolved for Northwind use | Vendor-described image analysis and integration capability | Vehicle-damage images and related metadata | Analytical damage output or confidence where a configured service actually exists | Commercial access, permitted data use, regional availability, thresholds, result semantics and operational fitness are unproven | S26-S27 | Unavailable or simulation-only until access/governance conditions are independently evidenced |

## Preserve cross-review decisions

P3.3 retains these P3.2 conclusions as implementation constraints:

- Roadside breakdown assistance is not collision recovery. `P3-VEHICLE-RECOVERY` cannot infer a
  collision dispatch path from roadside-assistance membership.
- NHC is not a generic contents service. `P3-NHC` stays Home building/land specific and
  `P3-CONTENTS-EVIDENCE` stays separate.
- Technical capability is not business authority. The eight `P3-EN-*` entries establish generic
  capability only.
- Evidence is not a claim decision. Police, FENZ, weather, repair, assessment, contents, document
  extraction and damage-analysis outputs cannot independently establish coverage, liability,
  fraud, acceptance, rejection, or settlement.
- Authentication is not action authority. Actor identity does not grant authority to submit a
  report, request a record, disclose claim data, appoint a provider, or decide a claim.
- Acknowledgement is not completion. External acceptance, result receipt, result verification and a
  Northwind Claim decision remain different events.

## Map research stages to the authoritative external-task lifecycle

Implementation authority remains `backend/domain/external_services.py` together with the
external-task sections of `docs/api.md`, `docs/persistence-schema.md`, and
`docs/claim-creation-boundary.md`. This document does not add enum values or persistence states.

| Research or business concept | Authoritative implementation representation | Interpretation |
| --- | --- | --- |
| Request prepared but not sent | `ExternalTaskOperationStatus.PREPARED` + `ExternalTaskDelivery.NOT_SUBMITTED` | Preparation records intended work only and does not prove provider contact |
| Request submitted and provider acceptance is evidenced | `ExternalTaskOperationStatus.ACCEPTED` + `ExternalTaskDelivery.SUBMITTED` + delivery evidence | `accepted` means the provider accepted the operation; it does not mean service completion or claim acceptance |
| Failure classified as safe to retry | `ExternalTaskOperationStatus.RETRYABLE_FAILURE` | Retry semantics come from the existing failure classifier, not research wording |
| Failure requiring review | `ExternalTaskOperationStatus.TERMINAL_FAILURE` | The canonical classifier/authority contract decides this state; it is not a synonym for generic service failure |
| Partial effect or ambiguous post-submission outcome | `ExternalTaskOperationStatus.UNKNOWN_OUTCOME` | Reconcile the operation before retry; never relabel an ambiguous submission as a safe failure |
| Provider answer or material received | Separate `ExternalTaskResult` plus evidence links | A provider result is separate from task status and separate from Claim State |
| Provider result checked | `ExternalTaskResultVerification.UNVERIFIED`, `CONSISTENT`, `INCONSISTENT`, or `REVIEW_REQUIRED` | Verification records how the result compares with the claim; no value automatically promotes it to a confirmed claim fact |
| Business wording such as pending, completed, unavailable, superseded, or disputed | Research/service-result description only | These words must not be serialized as `ExternalTaskOperationStatus` or used to create a second implementation lifecycle |

`provider_reference` and delivery evidence can prove routing or acknowledgement facts. They are not
a provider result and must not be treated as completion. A result verified as `CONSISTENT` remains
external evidence; the governed Claim fact-resolution path decides Claim State.

## Retain unresolved gaps with deterministic handoff

`Unresolved`, `unknown`, `unavailable`, and `simulation-only` in this section are research/access
labels, not `ExternalTaskOperationStatus` values. Issue #589 owns P3.4 gap closure after P3.3 is
accepted.

| Gap | Related P3 IDs | P3.3 status | Owner after #588 | Safe boundary now | Required next action in #589 |
| --- | --- | --- | --- | --- | --- |
| Police TCR authority | `P3-NZP-TCR` | Unresolved / Northwind access unknown | @LLL263 | Claimant/manual handling; no Northwind request is represented as authorised | Verify any publicly resolvable authority evidence; otherwise retain Northwind-side request access as unavailable |
| Vehicle recovery operating form | `P3-VEHICLE-RECOVERY` | Unresolved | @LLL263 | Preserve claimant-arranged, staff-arranged, insurer-network, and guidance-only alternatives | Close only publicly resolvable facts; otherwise retain the Northwind operating form as unknown |
| Repair pathway and appointment authority | `P3-REPAIRER`, `P3-ASSESSOR` | Unresolved | @LLL263 | Distinguish claimant-selected and insurer-authorised work; infer no appointment authority | Record supported public facts and keep Northwind appointment authority unavailable where not evidenced |
| Observable external completion evidence | All 12 claim-participant `P3-*` IDs above | Unresolved by participant | @LLL263 | Record only evidence actually observable; do not invent provider completion states | Map each resolvable public completion signal and mark the rest unavailable or simulation-only |
| FENZ operating form | `P3-FENZ-INFO` | Unresolved / direct Northwind access unavailable | @LLL263 | Claimant/manual request or labelled simulation | Close public request facts and retain Northwind-specific authority/access as unavailable unless evidenced |
| MetService operating form | `P3-METSERVICE` | Unresolved / Northwind product and access unknown | @LLL263 | Preserve public report categories separately from any selected Northwind product | Record supported product facts and leave final/custom quote, licence, procurement and Northwind access unresolved where evidence is absent |
| NHC prototype state and contents boundary | `P3-NHC`, `P3-CONTENTS-EVIDENCE` | Home/contents boundary resolved; Northwind workflow unresolved | @LLL263 | Keep NHCover Home-specific and contents evidence separate | Preserve that boundary and mark Northwind-specific workflow/access unknown if no new authority exists |
| Broker actionability | `P3-BROKER` | Unresolved | @LLL263 | Treat broker as an authority-boundary participant, not an automatic Northwind action target | Resolve public role facts only; actionable Northwind service remains unavailable unless separately authorised |
| ACC actionability | `P3-ACC-PROVIDER` | Northwind action unavailable | @LLL263 | Keep provider-led ACC lodgement outside Northwind action authority | Record relevant public pathway changes while preserving Northwind diagnosis/lodgement authority as unavailable |
| Direct contents-evidence retrieval | `P3-CONTENTS-EVIDENCE` | Unresolved / direct access unavailable | @LLL263 | Claimant retrieval/upload remains the baseline | Close only verified service facts; otherwise retain direct Northwind retrieval as unavailable |
| Enabling-platform production access | All eight `P3-EN-*` IDs above | Northwind production access unknown; unavailable or simulation-only unless approved | @LLL263 | Generic vendor capability does not become configured Northwind capability | Record procurement/access evidence only when authoritative; retain every unproved production path as unavailable or simulation-only |

## Hand authority work to P5 and implementation work to P11

P5 should derive service-specific consent and sharing rules from this catalogue rather than one
global third-party consent rule. Each selected service must distinguish data recorded internally
from data sent externally, claimant consent from Northwind authority, and claimant-visible results
from staff-only operational information.

P11 may implement only services whose service identity, requested action, authority, permitted
disclosure, access form, delivery evidence, failure handling, result verification and simulation
boundary are defined by authoritative engineering contracts. An unresolved P3.3/P3.4 access label
cannot be converted into a live provider action by an adapter, Agent, or Runtime prompt.

## Preserve the final P3.1 source register

The final P3.1 `S01-S28` coordinates are reproduced below so the P3.3 catalogue remains directly
traceable. P3.2 challenges their evidentiary boundaries without replacing the register.

| ID | Source and access date | Supports | Does not establish |
| --- | --- | --- | --- |
| S01 | [New Zealand Police — All online options](https://www.police.govt.nz/advice-services/all-online-options), accessed 2026-09-09 | 105 reporting and later case/report updates | Northwind submission or read access |
| S02 | [New Zealand Police — Request a Traffic Crash Report](https://www.police.govt.nz/advice-services/accessing-information/request-traffic-crash-report-tcr), accessed 2026-09-09 | TCR request routes and legal access categories | Guaranteed release or API access |
| S03 | [New Zealand Police — Request a TCR when involved in the crash](https://www.police.govt.nz/advice-services/accessing-information/request-traffic-crash-report-tcr/request-traffic-crash-report), accessed 2026-09-09 | Identity, representative authority, request details, and channels | Standing Northwind authority arrangement |
| S04 | [AA Insurance — What should I do if I have been in a car accident?](https://www.aainsurance.co.nz/help/article/360001231555-What-should-I-do-if-I-ve-been-in-a-car-accident), accessed 2026-09-09 | Post-accident towing can form part of an insurer claim pathway | Northwind cover or dispatch process |
| S05 | [AMI — Roadside Rescue](https://www.ami.co.nz/car-insurance/roadside-rescue), accessed 2026-09-09 | Breakdown service form and explicit collision exclusion | Collision recovery eligibility or Northwind access |
| S06 | [Insurance Council of New Zealand — Making a Claim](https://www.icnz.org.nz/individuals/making-a-claim/), accessed 2026-09-09 | Claim evidence, assessor role, emergency works, motor/home/contents context | One insurer's exact workflow or authority |
| S07 | [Financial Markets Authority — Weather Events Claims Insights](https://www.fma.govt.nz/library/reports-and-papers/weather-events-claims-insights/), published 2025-07-30, accessed 2026-09-09 | Third-party roles, oversight, delegated authority, progress visibility, specialist constraints | Routine Northwind prevalence or provider contracts |
| S08 | [NHC — NHCover Insurers' Guide](https://www.naturalhazards.govt.nz/our-publications/nhcover-insurers-guide-july-2024/), published 2026-04-28, accessed 2026-09-09 | Urgent works and insurer/NHC responsibilities | Northwind partner status or authority limits |
| S09 | [FENZ — Official Information Act requests](https://www.fireandemergency.nz/mi_NZ/contact-us/oia/), accessed 2026-09-09 | OIA request inputs, channels, decision timing | Guaranteed incident evidence or insurer API |
| S10 | [FENZ — Privacy statement](https://www.fireandemergency.nz/about-this-website/privacy/), accessed 2026-09-09 | Identity and written-authority boundary for personal information | Northwind-specific disclosure path |
| S11 | [MetService — Analysis and Reporting](https://about.metservice.com/products/analysis-and-reporting), accessed 2026-09-09 | Historical weather report types and insurance relevance | Coverage decisions, Northwind-selected product, final/custom quote, licence, procurement, or Northwind access |
| S12 | [NHC — About NHCover](https://www.naturalhazards.govt.nz/insurance-and-claims/about-nhcover/), accessed 2026-09-09 | Residential building/land scope and insurer contact model | Generic contents cover |
| S13 | [NHC — Make a new claim](https://www.naturalhazards.govt.nz/insurance-and-claims/claims/make-a-new-claim/), accessed 2026-09-09 | Insurer-managed and limited direct-NHC lodgement paths | Northwind partner or technical integration status |
| S14 | [NHC — Claims process](https://www.naturalhazards.govt.nz/insurance-and-claims/claims/claims-process/), accessed 2026-09-09 | Claimant, broker, insurer, evidence and specialist responsibilities | Northwind workflow contract |
| S15 | [ACC — Lodging a claim for a patient](https://www.acc.co.nz/for-providers/lodging-claims/lodging-a-claim-for-a-patient), published 2026-08-28, accessed 2026-09-09 | Eligible providers, required information, consent, lodgement and result path | Northwind authority or insurance coverage decision |
| S16 | [Twilio — Programmable Messaging](https://www.twilio.com/docs/messaging), accessed 2026-09-09 | Messaging channels, API resources, delivery tooling and verification capability | Northwind sender registration, consent basis or procurement |
| S17 | [Microsoft — Data, privacy, and security for Document Intelligence](https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/document-intelligence/data-privacy-security), updated 2026-07-28, accessed 2026-09-09 | Authentication, processing, result form, regional storage and documented retention | Northwind subscription, approved region or claim-fact authority |
| S18 | [Auth0 — Data Privacy and Compliance](https://auth0.com/docs/secure/data-privacy-and-compliance), accessed 2026-09-09 | Identity-platform protocols and compliance resources | Business-action authority or Northwind tenant readiness |
| S19 | [Google — Compute Routes overview](https://developers.google.com/maps/documentation/routes/compute-route-over), updated 2026-09-01, accessed 2026-09-09 | Route inputs and route/distance/duration outputs | Recovery provider or Northwind project access |
| S20 | [Google Maps Platform Terms of Service](https://cloud.google.com/maps-platform/terms), accessed 2026-09-09 | Commercial service, customer obligations and licence constraints | Northwind acceptance of terms or approved data use |
| S21 | [OpenAI — Data controls in the OpenAI platform](https://developers.openai.com/api/docs/guides/your-data), accessed 2026-09-09 | Official API data-control documentation | Northwind account, model approval, retention choice or deployment |
| S22 | [AWS — Amazon Bedrock](https://aws.amazon.com/bedrock/), accessed 2026-09-09 | Managed foundation-model capability | Northwind model access, region, guardrails or production approval |
| S23 | [AWS — Amazon Bedrock security and privacy](https://aws.amazon.com/bedrock/security-compliance/), accessed 2026-09-09 | Generic security, privacy, access-control and audit capabilities | Completed Northwind risk assessment |
| S24 | [AWS — Amazon Textract FAQs](https://aws.amazon.com/textract/faqs/), accessed 2026-09-09 | Supported inputs, extraction features, outputs and confidence | Northwind configuration or confirmation of extracted facts |
| S25 | [Sendbird — Chat documentation](https://sendbird.com/docs/chat), accessed 2026-09-09 | Chat SDKs/APIs, files, receipts, retrieval and webhooks | Northwind identity, visibility, retention or procurement |
| S26 | [Tractable — Home](https://tractable.ai/), accessed 2026-09-09 | Generic vehicle-damage analysis, confidence and API-integration claims | Northwind access, regional availability, thresholds or operational fitness |
| S27 | [Tractable — Privacy](https://tractable.ai/privacy/), accessed 2026-09-09 | Vendor privacy contact and published security-assurance claims | Northwind security review, data-use agreement or production approval |
| S28 | [Office of the Privacy Commissioner — Principle 11](https://www.privacy.org.nz/privacy-principles/11/), accessed 2026-09-09 | General New Zealand personal-information disclosure limits | Service-specific legal advice or Northwind consent design |

## P3.3 acceptance result

This reconciled catalogue supplies the governed-document output required by #588:

- All 12 final claim-journey participant IDs and all eight enabling-platform IDs have an explicit
  P3.2/P3.3 disposition, service/access form, input/output boundary, authority boundary,
  provenance coordinate and Validation Prototype boundary.
- The final P3.1 `S01-S28` register and links are preserved.
- Research service stages are explicitly separated from and mapped to the canonical external-task
  operation, delivery, result-verification and reconciliation contracts.
- Every retained P3.3 gap has an owner, research/access status, safe boundary and deterministic
  next action for #589.
- Unsupported Northwind authority, access, procurement, credential, service-level and data-use
  questions remain unresolved, unavailable or simulation-only instead of becoming capability
  claims.

The evidence level is research and governed documentation only. This delivery does not claim API,
persistence, Runtime, browser-route, live-provider, or full-journey implementation evidence.
