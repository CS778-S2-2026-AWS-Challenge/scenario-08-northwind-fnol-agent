# Third-party stakeholder and service research

This research record identifies external participants and enabling services that may appear in
New Zealand motor, home, and contents First Notice of Loss (FNOL) journeys. It is the P3.1 input
for Issue #587's independent challenge review; it is not a provider selection, service contract,
or statement that Northwind has live access.

## Research boundary

The research separates two layers that later work must not collapse:

- **Claim-journey participants** perform work, hold information, or supply evidence in a real
  claim journey.
- **Enabling platforms** provide communication, identity, routing, document-processing, or model
  technology to a Northwind-controlled process.

A real-world service does not imply that Northwind can invoke it electronically. An application
programming interface (API) does not establish Northwind's authority to share claim data, appoint a
provider, or act for a claimant. Public documentation also does not prove procurement, credentials,
approved data use, New Zealand availability, service levels, or production readiness.

This document records source facts and bounded interpretations. `SPEC/`, current engineering
contracts, and authorised Northwind decisions remain authoritative for product behaviour.

## Apply the evidence method

Sources were checked on 2026-09-09. The register favours New Zealand statutory bodies, regulators,
industry bodies, and first-party service documentation. Insurer material is used only as evidence
that a pathway can exist; it does not establish a Northwind arrangement.

Confidence describes the support for the fact in this record:

- **High:** A first-party or statutory source directly describes the service, access form, and
  relevant input or output.
- **Medium:** Authoritative evidence supports the service category, but the exact operating form,
  authority, or result for Northwind is unknown.
- **Unknown:** The source or access condition could not be verified. Later work must preserve the
  gap rather than infer an answer.

## Record claim-journey participant facts

The participant register uses stable research identifiers so #587 can challenge each entry without
copying this fact table into a second source of truth.

| ID | Participant and need | Service or access form | Inputs established by sources | Output or observable result | Authority and access boundary | Confidence | Sources |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `P3-NZP-REPORT` | New Zealand Police; report non-emergency crime or an incident and retain a Police reference | Claimant uses Police 105 online or another Police channel; a case/report update can later add information, photos, or documents | Incident information required by the selected Police channel; exact fields vary by report type | Police report acknowledgement or reference; later update state | Emergency situations use 111, not the FNOL service. No source proves that Northwind may submit a 105 report or read its state through an API | High for public claimant channels; unknown for Northwind access | S01 |
| `P3-NZP-TCR` | New Zealand Police; obtain a Traffic Crash Report (TCR) after a crash | A person or representative requests the held report online, by email, or by post | Location and time, Police file number when known, reason, identity evidence, and evidence of authorisation for a representative | Request decision and, when releasable, a TCR; information may be withheld | The claimant and an authorised representative have different evidence requirements. No unrestricted insurer API or guaranteed release is established | High | S02-S03 |
| `P3-VEHICLE-RECOVERY` | Towing or recovery operator; move an unsafe or undriveable vehicle | Claimant-arranged assistance, insurer-arranged towing, or an approved network are distinct possible forms | Vehicle location and condition; policy or service eligibility and safe physical access may also be required | Vehicle transported to a safe location or repairer, or assistance declined/unavailable | Roadside breakdown membership must not be treated as collision recovery. The canonical Northwind arrangement and dispatch access are unknown | Medium | S04-S05 |
| `P3-REPAIRER` | Motor or property repairer; inspect damage, quote, repair, and report progress | Claimant-selected repairer, insurer-authorised repairer, preferred network, or managed repair are distinct forms | Damage evidence, property or vehicle details, scope or referral, appointment details, and any insurer authority required by the pathway | Appointment, quote or scope, invoice, file note, progress, completion, or inability to proceed | A competitor's preferred network and portal do not prove Northwind eligibility or technical access. The insurer retains oversight obligations for appointed providers | High for the service category; unknown for Northwind arrangement | S06-S07 |
| `P3-ASSESSOR` | Loss assessor, adjuster, engineer, or other specialist; inspect and form a professional view of loss or repair needs | Usually insurer-appointed work, which may be physical or remote; the exact profession depends on the loss | Claim context, damage evidence, location, appointment details, and a bounded question or scope | Inspection record, assessment or specialist report, repair scope, request for more information, or delay | Assessment is normally later claim work, not a minimum FNOL input. Appointment authority, provider eligibility, visible status, and service level are unknown for Northwind | High for the role; medium for exact form | S06-S07 |
| `P3-EMERGENCY-WORKS` | Emergency contractor or tradesperson; make a home safe and prevent continuing damage | Claimant or insurer arranges urgent work; non-essential repairs may require insurer approval | Property location, damage and hazard, urgency, safe access, requested mitigation, and approval where required | Safe, sanitary, secure, or weathertight mitigation; work record, photos, and invoice | Immediate safety takes priority. Public guidance does not define Northwind's contractor network, spending authority, or reimbursement rule | Medium | S06, S08 |
| `P3-FENZ-INFO` | Fire and Emergency New Zealand (FENZ); supply held fire or emergency information | Official Information Act (OIA) request or Privacy Act request for personal information | Requester name, contact address, specific information, and relevant timeframe; identity or authority may be required for personal information | Acknowledgement and decision, information released in full or part, extension, transfer, charge, or refusal | The published OIA decision limit is up to 20 working days, so this is asynchronous evidence. No direct insurer request API or guaranteed incident report is established | High | S09-S10 |
| `P3-METSERVICE` | MetService; provide historical weather evidence for an event location and time | Weather-station, lightning, or detailed forensic report; free public resources are a separate form | Date, location, and the weather question or report type | Verified station or lightning report, detailed analysis, or no suitable observation | Weather evidence can support investigation but cannot decide coverage, cause, liability, or claim acceptance. Product choice, price, licence, and Northwind access are unknown | High for service existence; medium for Northwind form | S11 |
| `P3-NHC` | Natural Hazards Commission Toka Tū Ake (NHC); coordinate statutory residential building and land cover | In most cases the claimant lodges with the private insurer, which manages the NHCover portion; limited direct-NHC paths also exist | Natural-hazard event and damage details, insured home or land information, photographs, and requested supporting documents | Insurer-managed or NHC-managed claim progress, assessment, request for information, acceptance or non-acceptance explanation, and specialist reports where applicable | This is a Home building/land pathway. The reviewed source explicitly excludes generic contents cover. The exact Northwind partner status and workflow remain unknown | High | S12-S14 |
| `P3-CONTENTS-EVIDENCE` | Retailer, bank, manufacturer, service centre, or independent valuer; support ownership, value, or condition | Claimant normally retrieves and uploads a receipt, statement, serial record, service record, or valuation | Item identity and the source's proof of purchase, ownership, value, or condition | Supporting document, alternative evidence, or an unavailable record | These parties are evidence sources, not Northwind integrations by default. Direct retrieval requires a separately proven service and disclosure authority | High for evidence types; unknown for direct access | S06 |
| `P3-BROKER` | Insurance broker or authorised intermediary; help lodge and coordinate a claim | Broker communicates with the insurer or acts under a bounded delegation | Claimant authority, policy and incident context, and the information required by the insurer | Claim lodged or coordinated, communication relayed, or referral to the responsible insurer | A broker may act only where authorised. Delegated claims authority must stay within managed parameters and is not universal | High | S07, S14 |
| `P3-ACC-PROVIDER` | Registered health provider and Accident Compensation Corporation (ACC); record and lodge an injury claim | Eligible registered provider completes an electronic or paper ACC claim with the patient | Patient identity and contact details, accident date and place, specific injury, provider details, and recorded patient declaration and consent | Lodgement, request for more information, and later ACC cover decision | This is an adjacent injury-support pathway, not a Northwind insurance-claim decision. The FNOL Agent must not diagnose or imply that it can lodge an ACC claim | High | S15 |

## Record enabling-platform candidates

These candidates are technology inputs, not claim stakeholders. Their product documentation proves
only the listed generic capability.

| ID | Candidate capability | Service form, inputs, and outputs | Northwind boundary | Confidence | Sources |
| --- | --- | --- | --- | --- | --- |
| `P3-EN-MESSAGING` | Twilio messaging and verification | Authenticated SaaS APIs accept recipient, sender, content, and configuration and return message or verification identifiers and delivery states | Procurement, New Zealand sender setup, claimant communication basis, opt-out handling, credentials, and allowed claim content are unknown | High for generic capability; unknown for Northwind access | S16 |
| `P3-EN-DOC-AZURE` | Azure AI Document Intelligence extraction | An authenticated asynchronous analysis accepts documents and returns job status plus extracted JSON; submitted data and results are temporarily stored | Extraction creates machine-derived candidates, not confirmed claim facts. Approved region, subscription, model, retention decision, and data terms are unknown | High for generic capability; unknown for Northwind access | S17 |
| `P3-EN-IDENTITY` | Auth0 identity and access management | Hosted identity protocols and APIs can authenticate users and issue identity or authorisation claims | Authentication proves actor or session identity, not authority for claim, disclosure, or provider actions. Procurement and tenant configuration are unknown | High for generic capability; unknown for Northwind access | S18 |
| `P3-EN-ROUTES` | Google Maps Platform Routes API | An authenticated request uses origin, destination, travel mode, and field mask and can return route, distance, and duration data | Routing is advisory infrastructure, not a towing or repair service. Billing, licence, data minimisation, and enabled project access are unknown | High for generic capability; unknown for Northwind access | S19-S20 |
| `P3-EN-MODEL` | OpenAI API or Amazon Bedrock model inference | Provider APIs accept bounded model inputs and return generated or structured output | Model output remains advisory. Provider approval, model, region, retention, evaluation, personal-data scope, and production access require separate governance | High for generic capability; unknown for Northwind production access | S21-S23 |
| `P3-EN-DOC-AWS` | Amazon Textract document extraction | API or console accepts supported images or PDFs and returns text, handwriting, forms, tables, signatures, layout, coordinates, and confidence | Output is machine-derived evidence. Region, identity and access management, storage, retention, supported document set, and production authority are unknown | High for generic capability; unknown for Northwind access | S24 |
| `P3-EN-CONVERSATION` | Sendbird in-app conversation and support tooling | Client software development kits and server APIs provide channels, messages, files, receipts, moderation, retrieval, and webhooks | Claim visibility, staff-only content, identity mapping, retention, procurement, and live access are unknown | High for generic capability; unknown for Northwind access | S25 |
| `P3-EN-DAMAGE-AI` | Tractable vehicle-damage analysis candidate | Vendor material describes image-based vehicle-damage detection and assessment with certainty scores and system integration through APIs | Treat as unavailable or simulation-only until commercial access, permitted data use, regional availability, thresholds, and result semantics are independently verified | High for generic capability; unknown for Northwind access | S26-S27 |

## Preserve cross-cutting constraints

The sources support the following bounded conclusions:

- Northwind should tell claimants who owns each external step, why it is needed, and how pending
  work affects the next safe action.
- Northwind remains accountable for oversight of insurer-appointed third parties, even when a
  provider performs the work.
- Recording information internally and disclosing it externally are different permissions.
- Personal information is generally disclosed only for its collection purpose, a directly related
  purpose, with the person's authorisation, or another applicable legal ground. P5 must define the
  actual service-level rule; this research does not make a legal determination.
- A request acknowledgement, accepted provider job, received report, and Northwind claim decision
  are different events.
- External evidence and machine extraction may inform a claim but do not independently establish
  coverage, liability, fraud, acceptance, rejection, or settlement.

## Hand unresolved questions to later work

P3.2 should challenge the fact entries above. P3.3 or P3.4 must retain an owner and explicit
unresolved status for each unanswered question:

1. What authority and evidence would Northwind use to request a Police TCR for a claimant?
2. Is vehicle recovery claimant-arranged, staff-arranged, insurer-network dispatch, or guidance in
   the Validation Prototype?
3. Which repair pathway is demonstrated, and who may appoint each repairer or assessor?
4. Which external states and completion evidence can Northwind actually observe?
5. Is FENZ or MetService evidence claimant-requested, staff-prepared, manually requested, or
   simulated?
6. What exact Home state represents insurer-mediated NHCover work, and which contents evidence
   remains outside that pathway?
7. Are broker and ACC examples actionable services or authority-boundary examples only?
8. Has any enabling platform been procured, security-reviewed, configured, and approved for the
   minimum necessary claim data?

Until those questions are resolved, later implementation must use guidance, staff-mediated manual
work, unavailable state, or clearly labelled simulation. It must not claim a live provider action.

## Source register

The register records what each source supports and what it does not establish.

| ID | Source and date | Supports | Does not establish |
| --- | --- | --- | --- |
| S01 | [New Zealand Police — All online options](https://www.police.govt.nz/advice-services/all-online-options), accessed 2026-09-09 | 105 reporting and later case/report updates | Northwind submission or read access |
| S02 | [New Zealand Police — Request a Traffic Crash Report](https://www.police.govt.nz/advice-services/accessing-information/request-traffic-crash-report-tcr), accessed 2026-09-09 | TCR request routes and legal access categories | Guaranteed release or API access |
| S03 | [New Zealand Police — Request a TCR when involved in the crash](https://www.police.govt.nz/advice-services/accessing-information/request-traffic-crash-report-tcr/request-traffic-crash-report), accessed 2026-09-09 | Identity, representative authority, request details, and channels | A standing Northwind authority arrangement |
| S04 | [AA Insurance — What should I do if I have been in a car accident?](https://www.aainsurance.co.nz/help/article/360001231555-What-should-I-do-if-I-ve-been-in-a-car-accident), accessed 2026-09-09 | Post-accident towing can form part of an accepted motor claim | Northwind cover or dispatch process |
| S05 | [AMI — Roadside Rescue](https://www.ami.co.nz/car-insurance/roadside-rescue), accessed 2026-09-09 | Breakdown service form and explicit collision exclusion | Collision recovery eligibility or Northwind access |
| S06 | [Insurance Council of New Zealand — Making a Claim](https://www.icnz.org.nz/individuals/making-a-claim/), accessed 2026-09-09 | Claim evidence, assessor role, emergency works, and motor/home/contents context | One insurer's exact workflow or authority |
| S07 | [Financial Markets Authority — Weather Events Claims Insights](https://www.fma.govt.nz/library/reports-and-papers/weather-events-claims-insights/), published 2025-07-30, accessed 2026-09-09 | Third-party roles, oversight, delegated authority, progress visibility, and specialist constraints | Routine Northwind prevalence or provider contracts |
| S08 | [NHC — NHCover Insurers' Guide](https://www.naturalhazards.govt.nz/our-publications/nhcover-insurers-guide-july-2024/), published 2026-04-28, accessed 2026-09-09 | Urgent works and insurer/NHC responsibilities | Northwind's partner status or authority limits |
| S09 | [FENZ — Official Information Act requests](https://www.fireandemergency.nz/mi_NZ/contact-us/oia/), accessed 2026-09-09 | OIA request inputs, channels, and decision timing | Guaranteed incident evidence or insurer API |
| S10 | [FENZ — Privacy statement](https://www.fireandemergency.nz/about-this-website/privacy/), accessed 2026-09-09 | Identity and written-authority boundary for personal information | A Northwind-specific disclosure path |
| S11 | [MetService — Analysis and Reporting](https://about.metservice.com/products/analysis-and-reporting), accessed 2026-09-09 | Historical weather report types and insurance relevance | Coverage decisions, pricing, licence, or Northwind access |
| S12 | [NHC — About NHCover](https://www.naturalhazards.govt.nz/insurance-and-claims/about-nhcover/), accessed 2026-09-09 | Residential building and land scope and insurer contact model | Generic contents cover |
| S13 | [NHC — Make a new claim](https://www.naturalhazards.govt.nz/insurance-and-claims/claims/make-a-new-claim/), accessed 2026-09-09 | Insurer-managed and limited direct-NHC lodgement paths | Northwind partner or technical integration status |
| S14 | [NHC — Claims process](https://www.naturalhazards.govt.nz/insurance-and-claims/claims/claims-process/), accessed 2026-09-09 | Claimant, broker, insurer, evidence, and specialist responsibilities | A Northwind workflow contract |
| S15 | [ACC — Lodging a claim for a patient](https://www.acc.co.nz/for-providers/lodging-claims/lodging-a-claim-for-a-patient), published 2026-08-28, accessed 2026-09-09 | Eligible providers, required information, consent, lodgement, and result path | Northwind authority or an insurance coverage decision |
| S16 | [Twilio — Programmable Messaging](https://www.twilio.com/docs/messaging), accessed 2026-09-09 | Messaging channels, API resources, delivery tooling, and verification capability | Northwind sender registration, consent basis, or procurement |
| S17 | [Microsoft — Data, privacy, and security for Document Intelligence](https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/document-intelligence/data-privacy-security), updated 2026-07-28, accessed 2026-09-09 | Authentication, processing, result form, regional storage, and documented retention | Northwind subscription, approved region, or claim-fact authority |
| S18 | [Auth0 — Data Privacy and Compliance](https://auth0.com/docs/secure/data-privacy-and-compliance), accessed 2026-09-09 | Identity-platform protocols and documented compliance resources | Business-action authority or Northwind tenant readiness |
| S19 | [Google — Compute Routes overview](https://developers.google.com/maps/documentation/routes/compute-route-over), updated 2026-09-01, accessed 2026-09-09 | Required route inputs and route, distance, and duration outputs | A recovery provider or Northwind project access |
| S20 | [Google Maps Platform Terms of Service](https://cloud.google.com/maps-platform/terms), accessed 2026-09-09 | Commercial service, customer obligations, and licence constraints | Northwind acceptance of terms or approved data use |
| S21 | [OpenAI — Data controls in the OpenAI platform](https://developers.openai.com/api/docs/guides/your-data), accessed 2026-09-09 | Official API data-control documentation | Northwind account, model approval, retention choice, or deployment |
| S22 | [AWS — Amazon Bedrock](https://aws.amazon.com/bedrock/), accessed 2026-09-09 | Managed foundation-model capability | Northwind model access, region, guardrails, or production approval |
| S23 | [AWS — Amazon Bedrock security and privacy](https://aws.amazon.com/bedrock/security-compliance/), accessed 2026-09-09 | Generic security, privacy, access-control, and audit capabilities | A completed Northwind risk assessment |
| S24 | [AWS — Amazon Textract FAQs](https://aws.amazon.com/textract/faqs/), accessed 2026-09-09 | Supported inputs, extraction features, outputs, and confidence | Northwind configuration or confirmation of extracted facts |
| S25 | [Sendbird — Chat documentation](https://sendbird.com/docs/chat), accessed 2026-09-09 | Chat software development kits, APIs, files, receipts, retrieval, and webhooks | Northwind identity, visibility, retention, or procurement |
| S26 | [Tractable — Home](https://tractable.ai/), accessed 2026-09-09 | Generic vehicle-damage analysis, confidence, and API-integration claims | Northwind access, regional availability, thresholds, or operational fitness |
| S27 | [Tractable — Privacy](https://tractable.ai/privacy/), accessed 2026-09-09 | Vendor privacy contact and published security-assurance claims | A Northwind security review, data-use agreement, or production approval |
| S28 | [Office of the Privacy Commissioner — Principle 11](https://www.privacy.org.nz/privacy-principles/11/), accessed 2026-09-09 | General New Zealand personal-information disclosure limits | Service-specific legal advice or Northwind consent design |

## State the P3.1 result

The public evidence confirms the existence and broad form of Police reporting and TCR requests,
vehicle recovery, repair, assessment, emergency works, FENZ information requests, MetService
reports, insurer-mediated NHCover, contents evidence, broker coordination, and provider-led ACC
lodgement. It does not establish Northwind's provider relationships, delegated authority, live API
access, data-use approval, or service levels.

The enabling-platform sources confirm generic technical capabilities. All Northwind access remains
unknown. P3.2 can therefore review the source facts immediately, while P3.3 and P3.4 must preserve
the unresolved operating decisions before P5 or P11 defines consent or implements an external
action.
