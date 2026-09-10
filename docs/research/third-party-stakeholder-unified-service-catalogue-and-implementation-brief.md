# P3.3 Unified Third-Party Service Catalogue and Implementation Brief

This research record is the final P3.3 delivery for Issue #588. It reconciles the accepted P3.1
stakeholder/service research with the accepted P3.2 independent challenge into one implementation-facing
catalogue for motor, home, and contents First Notice of Loss (FNOL) journeys in New Zealand.
The P3.4 section extends this indexed record for Issue #589 without revising P3.3's accepted source
authority or implementation boundary.

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

## Close the P3.4 research gaps

This section is the P3.4 gap-closure brief for Issue #589. It rechecks the public evidence behind
every P3.3 high-impact gap and gives each atomic item exactly one `resolved` or `blocked`
disposition. `Resolved` means that authoritative public evidence closes the stated research
question. `Blocked` means that an implementation-ready Northwind fact still needs Northwind
authority or access evidence, even when the public service boundary is well supported.

The source coordinates refer to the linked P3.1 register above. All cited pages were rechecked on
2026-09-09. Confidence applies only to the stated public fact. It never transfers to a Northwind
provider arrangement, legal conclusion, service level, credential, permitted data use, or live
technical access.

| Closure ID | P3.3 gap and stable P3 IDs | Disposition | Verified public fact, source, and evidence limit | Confidence | Northwind access status | Implementation boundary | Owner and next action |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `P3.4-G01` | Police TCR authority: `P3-NZP-TCR` | `blocked` | S02-S03, accessed 2026-09-09: an involved person or authorised agent, including an insurance company, may request a held Traffic Crash Report (TCR); a representative or organisation supplies evidence of authorisation. Release remains subject to the Privacy Act or Official Information Act and is not guaranteed. | High | `unavailable` | Keep the Validation Prototype claimant-led or staff-prepared and manual. Do not represent a Northwind request as authorised or submitted. | @LLL263; obtain an approved Northwind representative-authority process, request evidence, operating owner, and channel before any implementation. |
| `P3.4-G02` | Vehicle-recovery operating form: `P3-VEHICLE-RECOVERY` | `blocked` | S04-S05, accessed 2026-09-09: one insurer describes towing after claim acceptance, while the reviewed roadside service excludes accident vehicles and directs collision cases to the insurer. These examples prove distinct forms, not a Northwind form or entitlement. | High for the distinction; unknown for Northwind | `unavailable`; `simulation-only` for a configured demonstration | Preserve claimant-arranged, staff-arranged, insurer-network, and guidance-only choices. Do not infer collision dispatch from roadside membership. | @LLL263; Northwind Claims Operations must select the operating form, eligibility rule, dispatch owner, service evidence, and recovery path. |
| `P3.4-G03` | Repair and assessment appointment: `P3-REPAIRER`, `P3-ASSESSOR` | `blocked` | S06-S07, accessed 2026-09-09: repairers, assessors, adjusters, engineers, and tradespeople can participate; insurers should explain their roles, oversee third parties, and keep delegated authority within managed parameters. The sources do not name a Northwind network or delegation. | High for roles and oversight; unknown for Northwind authority | `unavailable`; `simulation-only` where the provider is explicitly synthetic | Keep claimant-selected and insurer-appointed work distinct. No quote, appointment, repair approval, or assessment result changes Claim State by itself. | @LLL263; obtain Northwind pathway selection, appointment/delegation rules, provider eligibility, observable events, and service expectations. |
| `P3.4-G04` | Observable completion evidence: all 12 claim-participant IDs | `blocked` | S01-S15, accessed 2026-09-09: the public result forms are mapped by participant in the next table. They prove possible evidence, not that Northwind can receive it electronically or treat it as completion. | High for the mapped public forms; unknown for Northwind observability | `unavailable` unless manually supplied; `simulation-only` for synthetic provider results | Store an actual provider result separately from request delivery, then verify it through the existing result-verification contract. Never infer completion from acknowledgement or `provider_reference`. | @LLL263; for each implemented service, obtain its result schema, delivery channel, provenance, completion rule, service level, and verification owner. |
| `P3.4-G05` | FENZ operating form: `P3-FENZ-INFO` | `blocked` | S09-S10, accessed 2026-09-09: an Official Information Act request names the requester, contact address, requested information, and timeframe; FENZ acknowledges it and normally decides within 20 working days. Personal-information access requires identity proof and written authority for a representative. No insurer API or guaranteed report is described. | High | `unavailable`; `simulation-only` if the asynchronous exchange is demonstrated | Keep this claimant-requested or staff-prepared and manual. Acknowledgement, extension, transfer, charge, refusal, and released information remain distinct outcomes. | @LLL263; obtain Northwind request authority, approved channel, identity/authority evidence, information scope, tracking owner, and response-ingestion process. |
| `P3.4-G06` | MetService operating form: `P3-METSERVICE` | `blocked` | S11, accessed 2026-09-09: MetService publishes weather-station, lightning, historical-forecast, wind-rose, and detailed forensic report forms with starting prices. The page does not establish Northwind's selected product, final or custom quote, licence, procurement, data scope, or access. | High for public products and starting prices; unknown for Northwind | `unavailable`; `simulation-only` for a synthetic report | Treat weather material as external evidence only. It cannot decide cause, coverage, liability, or claim acceptance. | @LLL263; obtain product selection, final quote, licence/data terms, procurement approval, request channel, service level, and result-verification owner. |
| `P3.4-G07A` | NHC Home/contents boundary: `P3-NHC`, `P3-CONTENTS-EVIDENCE` | `resolved` | S06 and S12-S14, accessed 2026-09-09: NHCover is for eligible residential buildings and limited residential land; contents evidence remains a separate private-insurance evidence path. This does not establish any Northwind workflow. | High | `unavailable` for Northwind integration; no simulation is needed to preserve the product boundary | Keep `P3-NHC` Home building/land-specific and keep contents ownership/value evidence under `P3-CONTENTS-EVIDENCE`. | @LLL263; no further public research is required unless the statutory scope changes. |
| `P3.4-G07B` | NHC prototype workflow: `P3-NHC` | `blocked` | S12-S14, accessed 2026-09-09: most claimants contact their insurer, which manages the NHCover portion; NHC manages limited direct paths. The public material does not establish whether Northwind is a partner or its internal state, authority, or technical exchange. | High for the public pathway; unknown for Northwind | `unavailable`; `simulation-only` for a labelled insurer-mediated demonstration | Represent only a Home-specific manual or synthetic coordination step until Northwind's partner and data-exchange evidence exists. | @LLL263; obtain partner status, claim-routing authority, state mapping, data exchange, result evidence, and exception ownership from Northwind and NHC. |
| `P3.4-G08` | Broker actionability: `P3-BROKER` | `blocked` | S07 and S12-S14, accessed 2026-09-09: a broker may manage communication or make a claim when the claimant authorises it; delegated claims authority must stay within managed parameters. The sources do not establish a Northwind broker service or delegation. | High for the public role; unknown for Northwind | `unavailable`; `simulation-only` if a broker handoff is demonstrated | Keep the broker as an authority-boundary participant. Do not expose an external action without claimant authority and an explicit Northwind delegation. | @LLL263; obtain broker identity, claimant-authority evidence, delegation scope, permitted data, action/result contract, and oversight owner. |
| `P3.4-G09` | ACC actionability: `P3-ACC-PROVIDER` | `blocked` | S15, accessed 2026-09-09: eligible registered health providers lodge ACC claims with recorded patient declaration and consent; ACC then requests information or makes its own cover decision. This does not give Northwind diagnosis or lodgement authority. | High | `unavailable`; do not simulate Northwind lodgement | Keep this as an adjacent injury-support and authority-boundary example. The FNOL Agent may recommend appropriate human or health-provider support but cannot diagnose, lodge, or imply ACC acceptance. | @LLL263; require an explicit product-scope and authority decision before treating ACC as a Northwind action target. |
| `P3.4-G10` | Direct contents-evidence retrieval: `P3-CONTENTS-EVIDENCE` | `blocked` | S06, accessed 2026-09-09: receipts, warranties, purchase records, photographs, and independent valuations can support a contents claim, and a retailer may retain a purchase record. The source does not establish a direct insurer retrieval service or disclosure authority. | High for evidence forms; unknown for direct access | `unavailable`; claimant upload is the baseline; synthetic material may be `simulation-only` | Ask the claimant to retrieve and upload the evidence. Record an unavailable item honestly and do not imply Northwind queried a retailer, bank, manufacturer, service centre, or valuer. | @LLL263; identify a specific provider and obtain claimant authority, Northwind purpose, permitted fields, access contract, provenance, and no-result handling before direct retrieval. |
| `P3.4-G11` | Enabling-platform production access: all eight `P3-EN-*` IDs | `blocked` | S16-S27, accessed 2026-09-09: first-party documentation supports the generic capabilities listed in the platform table below. Public vendor material cannot establish Northwind procurement, credentials, approved region or data use, service level, security acceptance, or production access. | High for generic capability; unknown for Northwind production access | `unavailable` for production; `simulation-only` or governed local development until separately approved | Use only repository-authorised provider-neutral adapters and profiles. Never promote a fixture, local credential, or successful test call into a production-capability claim. | @LLL263; retain the per-platform blockers below until Northwind supplies the named approval evidence. |

### Map public result forms without inventing completion states

This table closes the public-fact portion of `P3.4-G04`. A listed result is only a possible
external evidence form. It is not proof that Northwind can observe the result, that the service is
complete, or that Claim State may change.

| P3 ID | Publicly supported result or completion evidence | Source and access date | Northwind observation boundary |
| --- | --- | --- | --- |
| `P3-NZP-REPORT` | Report acknowledgement or Police reference; a later report update where the public channel supports it | S01, accessed 2026-09-09 | Direct read access is `unavailable`; accept claimant-supplied evidence or use `simulation-only` data. |
| `P3-NZP-TCR` | Request decision and a released TCR, or a withholding outcome | S02-S03, accessed 2026-09-09 | Direct request and response access is `unavailable`; manual handling remains authoritative. |
| `P3-VEHICLE-RECOVERY` | Vehicle transport to an eligible destination, or inability to assist | S04-S05, accessed 2026-09-09 | Dispatch and telemetry are `unavailable`; a synthetic acknowledgement is `simulation-only`. |
| `P3-REPAIRER` | Appointment, quote or scope, invoice, progress update, completion evidence, or inability to proceed | S06-S07, accessed 2026-09-09 | Provider status access is `unavailable`; use supplied documents or `simulation-only` records. |
| `P3-ASSESSOR` | Inspection record, damage assessment, specialist report, scope, request for information, or delay | S06-S07, accessed 2026-09-09 | Provider status access is `unavailable`; any synthetic report is `simulation-only`. |
| `P3-EMERGENCY-WORKS` | Evidence that the property was made safe, sanitary, secure, or weathertight, plus available work records | S06 and S08, accessed 2026-09-09 | Contractor dispatch/status is `unavailable`; claimant or staff evidence is required. |
| `P3-FENZ-INFO` | Request acknowledgement, decision, extension, transfer, charge, refusal, or released information | S09-S10, accessed 2026-09-09 | Direct response access is `unavailable`; model the asynchronous exchange manually or as `simulation-only`. |
| `P3-METSERVICE` | Weather-station, lightning, forecast, wind-rose, or forensic report obtained for a specified event | S11, accessed 2026-09-09 | Purchased-report access is `unavailable`; a synthetic report is `simulation-only`. |
| `P3-NHC` | Claim-manager update, assessment, scope of works, expert report, settlement advice, or non-acceptance explanation | S12-S14, accessed 2026-09-09 | Northwind partner exchange is `unavailable`; an insurer-mediated demonstration is `simulation-only`. |
| `P3-CONTENTS-EVIDENCE` | Receipt, warranty, purchase/delivery record, photograph, service record, or independent valuation | S06, accessed 2026-09-09 | Direct source retrieval is `unavailable`; claimant upload remains the baseline. |
| `P3-BROKER` | Authorised claim lodgement, communication relay, or referral to the responsible insurer | S07 and S12-S14, accessed 2026-09-09 | A Northwind broker channel is `unavailable`; any synthetic handoff is `simulation-only`. |
| `P3-ACC-PROVIDER` | Lodgement, request for more information, status shown through an approved provider system, or ACC cover decision | S15, accessed 2026-09-09 | Northwind lodgement/status access is `unavailable` and must not be simulated as a Northwind action. |

The implementation representation remains the existing `ExternalTaskRecord`,
`ExternalTaskDelivery`, `ExternalTaskResult`, and `ExternalTaskResultVerification` contract. The
research words in this table are not new enum values. An `accepted` external task proves provider
acceptance only; a formal result stays separate and does not become a confirmed Claim fact without
the governed reconciliation path.

### Retain per-platform access blockers

The public capability is resolved for research purposes, but each Northwind production-access item
remains blocked. The access labels below are research labels only and are not Runtime states.

| P3 ID | Verified generic capability and source | Northwind access status | Owner and next action |
| --- | --- | --- | --- |
| `P3-EN-MESSAGING` | Programmable messaging, verification, message identifiers, and delivery status: S16, accessed 2026-09-09 | `unavailable` for production; `simulation-only` for a controlled scenario | @LLL263; obtain procurement, sender registration, communication basis, opt-out rule, approved content, credentials, region, and service level. |
| `P3-EN-DOC-AZURE` | Authenticated asynchronous document analysis, job status, extracted JSON, regional temporary storage, and documented retention: S17, accessed 2026-09-09 | `unavailable` for production; `simulation-only` for extracted candidates | @LLL263; obtain subscription, region, model, retention decision, deletion procedure, data-use approval, credentials, and extraction verification rule. |
| `P3-EN-IDENTITY` | Hosted identity protocols and compliance resources: S18, accessed 2026-09-09 | `unavailable` for production; local identity remains governed by repository contracts | @LLL263; obtain tenant procurement, identity mapping, region, security/privacy review, credentials, and explicit separation of authentication from claim-action authority. |
| `P3-EN-ROUTES` | Route computation from origin, destination, travel mode, and selected response fields under commercial terms: S19-S20, accessed 2026-09-09 | `unavailable` for production; `simulation-only` for route planning | @LLL263; obtain project/billing access, accepted licence, approved location-data scope, credentials, quota/service level, and proof that routing is not provider dispatch. |
| `P3-EN-MODEL` | Provider model inference and published data-control, security, privacy, access-control, and audit capabilities: S21-S23, accessed 2026-09-09 | `unavailable` as a generic production claim; only an individually approved profile may be configured | @LLL263; obtain provider/model/region approval, retention and training-use terms, minimum data scope, evaluation, credentials, limits, fallback qualification, and security review. |
| `P3-EN-DOC-AWS` | Image/PDF extraction of text, forms, tables, signatures, layout, coordinates, and confidence: S24, accessed 2026-09-09 | `unavailable` for production; `simulation-only` for machine-derived candidates | @LLL263; obtain account/region/IAM, storage and retention controls, supported claim-document set, data-use approval, credentials, service level, and fact-confirmation rule. |
| `P3-EN-CONVERSATION` | Chat channels, messages, files, receipts, retrieval, moderation, and webhooks: S25, accessed 2026-09-09 | `unavailable` for production; repository conversation fixtures remain separate | @LLL263; obtain procurement, identity mapping, role visibility, retention/deletion, region, approved claim content, credentials, moderation, and service level. |
| `P3-EN-DAMAGE-AI` | Vendor-described image-based vehicle-damage analysis, confidence, and integration capability: S26-S27, accessed 2026-09-09 | `unavailable` for production; `simulation-only` for the Validation Prototype | @LLL263; obtain commercial access, New Zealand availability, permitted image/metadata use, thresholds, result schema and semantics, security review, credentials, service level, and human-verification rule. |

## Record the P3.4 change log

The change log maps every P3.3 handoff row to its P3.4 disposition. A confidence increase below
applies to the public fact only; it does not change the recorded Northwind access status.

| P3.3 gap | P3.4 record | Change from P3.3 |
| --- | --- | --- |
| Police TCR authority | `P3.4-G01` | Confirmed the public representative-authority evidence at high confidence; retained Northwind access as `blocked` and `unavailable`. |
| Vehicle recovery operating form | `P3.4-G02` | Confirmed the collision-towing versus roadside-breakdown distinction; retained Northwind operating form and dispatch as `blocked`. |
| Repair pathway and appointment authority | `P3.4-G03` | Confirmed participant roles, insurer oversight, and bounded delegation; retained Northwind appointment and provider access as `blocked`. |
| Observable external completion evidence | `P3.4-G04` and the 12-row result map | Enumerated the public result form for every claim participant; retained electronic Northwind observability as `blocked`. |
| FENZ operating form | `P3.4-G05` | Confirmed request inputs, acknowledgement, decision timing, and representative evidence; retained Northwind authority and direct access as `blocked`. |
| MetService operating form | `P3.4-G06` | Confirmed public report categories and starting prices; retained product selection, final quote, licence, procurement, and Northwind access as `blocked`. |
| NHC prototype state and contents boundary | `P3.4-G07A` and `P3.4-G07B` | Marked the Home/land versus contents research boundary `resolved`; retained the Northwind partner workflow and access as `blocked`. |
| Broker actionability | `P3.4-G08` | Confirmed authorised broker participation and bounded delegation; retained an actionable Northwind broker service as `blocked`. |
| ACC actionability | `P3.4-G09` | Confirmed the registered-provider and patient-consent pathway; retained Northwind diagnosis, lodgement, and status access as `blocked`. |
| Direct contents-evidence retrieval | `P3.4-G10` | Confirmed the claimant-supplied evidence forms; retained direct Northwind retrieval as `blocked`. |
| Enabling-platform production access | `P3.4-G11` and the eight-row platform table | Rechecked each generic capability source; retained every unapproved production path as `blocked` and `unavailable` or `simulation-only`. |

## State the P3.4 acceptance result

This P3.4 closure records the following bounded result:

- Every P3.3 high-impact gap has a stable P3.4 closure coordinate and exactly one `resolved` or
  `blocked` disposition.
- Every public fact used to narrow a gap names its P3.1 source coordinate, 2026-09-09 access date,
  evidence limit, and fact-level confidence.
- Every remaining Northwind-specific authority, procurement, credential, data-use,
  regional-availability, service-level, and technical-access question is explicitly
  `unavailable` or `simulation-only`, with an owner and next action.
- Public completion evidence is mapped for all 12 claim participants, and production-access
  blockers are retained separately for all eight enabling platforms.
- The research labels do not alter the authoritative external-task lifecycle, delivery, result,
  verification, or reconciliation contracts.
- The existing `docs/README.md` Unified Third-party Service Catalogue and Implementation Brief
  entry resolves to this P3.3/P3.4 record; no second catalogue or index entry is introduced.

The evidence level remains governed research and documentation only. It does not claim API,
persistence, Runtime, browser-route, live-provider, or full-journey evidence.
