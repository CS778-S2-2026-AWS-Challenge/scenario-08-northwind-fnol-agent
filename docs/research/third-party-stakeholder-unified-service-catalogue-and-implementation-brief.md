# P3.3 Unified Third-Party Service Catalogue and Implementation Brief

**Sprint:** Sprint 3 Week 6  
**Issue:** #588  
**Contributors:** LLL263, jxu316-arch  
**Scope:** Motor, Home and Contents FNOL in New Zealand  
**Status:** Final P3.3 merged delivery

## 1. Purpose

This document merges the P3.1 third-party technology/vendor research with the P3.2 independent challenge review into one implementation-facing catalogue.

The merged review identifies two different external layers that must not be treated as the same thing:

1. **Claim-journey stakeholders and business services** — organisations or professionals that participate in, produce evidence for, or perform work within a real claim journey.
2. **Enabling technology vendors and platforms** — software or infrastructure that may help Northwind communicate, authenticate, extract data, route work, or analyse evidence.

A technical API, SDK, webhook, or SaaS product does not by itself prove that Northwind has business authority to contact a stakeholder, obtain evidence, dispatch a provider, or act for a claimant. Conversely, a real claim service may exist even when Northwind has no direct technical integration.

This distinction is the central P3.3 implementation rule.

## 2. Merged conclusions

### 2.1 Claim-journey stakeholder layer

The P3.2 review supports the following business-service categories, with qualifications where evidence or authority is incomplete:

- New Zealand Police reporting and later Traffic Crash Report evidence.
- Vehicle recovery / towing as a business need, without assuming a particular provider arrangement.
- Repairers and repair quotations, with claimant-selected and insurer-authorised paths kept distinct.
- Assessors and engineers as later professional work rather than minimum FNOL input.
- Fire and Emergency New Zealand information as asynchronous external evidence.
- MetService weather evidence as supporting evidence only.
- Natural Hazards Commission handling for Home natural-hazard claims through an insurer-mediated pathway.
- Retailer, bank, service-centre, manufacturer, and valuer evidence for Contents claims.
- Tractable-style vehicle-damage analysis as a candidate claim-domain capability whose access and data-use authority remain unproven.

### 2.2 Enabling-technology layer

The P3.1 research identifies the following technology/vendor candidates:

- Twilio for messaging, voice, notification, and verification.
- Azure AI Document Intelligence for document extraction and evidence structuring.
- Auth0 by Okta for claimant/staff identity and authentication.
- Google Maps Platform Routes API for distance, ETA, and routing support.
- OpenAI API or Amazon Bedrock for controlled AI assistance.
- Amazon Textract as an AWS document-extraction alternative.
- Sendbird for in-app customer/staff messaging and service conversations.
- Tractable for vehicle-damage analysis.

These vendors are not automatically claim stakeholders. Their role is to enable a Northwind-controlled business process.

## 3. Unified service catalogue

| Layer | Stakeholder / service / vendor | Scenario | Business capability | Service form / access form | Primary inputs | Expected output / state | Authority / consent boundary | Provenance | Simulation / implementation boundary |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Claim stakeholder | NZ Police 105 reporting | Motor / theft | Record an incident with Police when relevant | Claimant-facing reporting channel | Incident details supplied by claimant | Report or acknowledgement; reference may be pending | Claimant acts directly unless another authority path is explicitly established | P3.2 source register: NZ Police “Use 105” and traffic reporting sources | Guidance/link is supportable; Northwind must not claim unrestricted Police API access |
| Claim stakeholder | Traffic Crash Report | Motor | Obtain later authoritative crash evidence | Separate information-request process | Crash/report details; authority evidence where required | Requested / pending / received / unavailable | Northwind authority to act for claimant remains unresolved | P3.2 source register: NZ Police “Request a Traffic Crash Report” | Treat as pending external evidence until a real request path and authority are proven |
| Claim service | Vehicle recovery / towing | Motor | Move an undriveable vehicle or restore mobility | Claimant-arranged, insurer-arranged, network dispatch, or guidance; exact Northwind path unresolved | Incident location, vehicle state, claimant/contact details as required | Prepared / accepted / completed / failed | Service authority and provider relationship vary by arrangement | P3.2 review; AA/AMI material used only as journey examples | Model the business need separately from provider identity and integration state |
| Claim service | Repairer / repair quote | Motor | Determine repair option and expected cost | Claimant-selected repairer or insurer-authorised/panel repairer | Vehicle damage evidence, appointment/referral details | Quote / repair status / appointment status | Appointment and approval authority depend on pathway | P3.2 review; Tower example shows insurer-repairer digital integration can exist | Do not infer that a private insurer/provider integration is available to Northwind |
| Claim service | Emergency contractor | Home | Stop continuing damage or make property safe | Physical service arranged by claimant or insurer | Property location, damage type, urgency | Job accepted / in progress / completed / failed; evidence may follow | Situation-dependent service authority | P3.2 analysis of mitigation-before-assessment | Represent as urgent mitigation service; do not wait for full assessment when safety or continuing loss requires action |
| Claim professional | Assessor / engineer | Motor / Home | Professional damage or structural assessment | Usually insurer-appointed professional work | Claim context and evidence; appointment details | Appointment / in progress / report pending / report received | Normally insurer/staff-owned work; exact trigger must be decided | P3.2 review | Create an insurer-owned task/work item; FNOL may continue while report is pending |
| Claim evidence source | FENZ information | Home / fire | Obtain authoritative fire/emergency information | Information request / official information process | Event details and request authority | Request pending / response received / unavailable | Requesting party and authority need to be defined for prototype | P3.2 source register: FENZ official information requests | Do not model as a synchronous FNOL completion requirement |
| Claim evidence source | MetService evidence | Home | Support weather/event verification | Public information, formal report/service, or simulation — exact form unresolved | Date, location, weather/event parameters | Evidence retrieved / unavailable | Access and product choice remain unresolved | P3.2 source register: MetService weather analysis/reporting | Evidence only; must not be converted directly into coverage/liability decisions |
| Claim process stakeholder | Natural Hazards Commission (NHC) | Home natural hazard | Coordinate NHCover handling | Insurer-mediated process | Claim/event information through insurer process | Process/status | Private insurer remains central point of contact; agency framework applies | P3.2 source register: NHC NHCover and claims-process sources | Home pathway only unless new evidence supports another role |
| Claim evidence source | Retailer / bank / service centre / manufacturer / valuer | Contents | Support proof of ownership, value, or condition | Usually claimant retrieval and upload | Receipt, statement, serial number, valuation, service evidence | Evidence available / unavailable / alternative evidence required | Claimant-controlled by default | P3.2 analysis | Do not turn these parties into direct Northwind integrations without a proven service arrangement |
| Enabling vendor | Twilio | Cross-cutting | SMS, voice, messaging status, reminders, OTP verification | SaaS API + webhook | Contact detail, minimal notification content, verification parameters | Accepted / delivered / failed / opted-out / verification result | Contact preferences, consent basis, opt-out status, and minimum-necessary disclosure must be preserved | P3.1 official Twilio documentation | Candidate live integration only after procurement/configuration; does not itself authorise claim decisions or third-party disclosure |
| Enabling vendor | Azure AI Document Intelligence | Cross-cutting evidence | Extract text, tables, key-value pairs, signatures, and structured fields | Cloud document-analysis API | Uploaded evidence document | Extracted fields, confidence, model output | Evidence must be processed under approved data/privacy terms; extraction is not authoritative claim fact | P3.1 Microsoft documentation | Machine extraction + human confirmation; never silently promote low-confidence output to claim fact |
| Enabling vendor | Auth0 by Okta | Cross-cutting identity | Claimant login, staff SSO/MFA, token and scope support | Identity platform | Credentials / identity assertions | Authenticated session / token / claim scopes | Identity proves actor/session, not business authority for claim actions | P3.1 Auth0/Okta documentation | Candidate replacement for development identity after procurement and deployment design |
| Enabling vendor | Google Maps Routes API | Motor / Home dispatch support | Distance, ETA, routing, provider comparison | Maps API | Location and service-point inputs | Route / ETA / distance matrix | Location consent and minimum-data handling required; routing is advisory | P3.1 Google Maps documentation | Support provider ranking/dispatch planning only; not a towing/repair provider itself |
| Enabling vendor | OpenAI API / Amazon Bedrock | Cross-cutting AI assistance | Summaries, structured drafts, knowledge-grounded explanations, next-step drafts | Model gateway | Minimum-necessary text/context | Draft / suggestion / extracted candidate fields | No high-impact decision authority; minimise personal data; preserve deterministic/staff boundaries | P3.1 OpenAI/AWS documentation | Advisory capability only; must not claim evidence received, liability decided, fraud determined, or claim accepted/rejected |
| Enabling vendor | Amazon Textract | Cross-cutting evidence | OCR, forms, tables, handwriting/signature extraction | AWS document-analysis service | Evidence images/documents | Extracted text/fields/confidence | Data-use, region, access and opt-out controls must be reviewed before real evidence use | P3.1 AWS documentation | Alternative to Azure document extraction; treat output as machine-derived evidence candidate |
| Enabling vendor | Sendbird | Cross-cutting communication | In-app claimant/staff messaging, files, routing, handoff | Chat/desk platform | Claim-linked messages/files | Message/thread/ticket states | Claim visibility rules must separate claimant-visible and internal-only information | P3.1 Sendbird documentation | Candidate communication platform; not an authority source for claim actions |
| Enabling vendor / claim-domain tool | Tractable | Motor | Vehicle damage analysis and triage support | Enterprise partner/service integration | Vehicle damage photos and related metadata | Analytical damage evidence / recommendation | Commercial/API access, permitted data use, governance and thresholds are not proven for Northwind | P3.1 vendor material + P3.2 challenge | Simulation/candidate capability unless contract, access, data use and operational boundaries are separately evidenced |

## 4. Conflicts resolved by the merged review

### 4.1 Do not classify infrastructure vendors as claim stakeholders

P3.1 is primarily a technology/vendor integration study. P3.2 is primarily a real-claim stakeholder and authority review. The merged result keeps both, but places them on different layers.

For example:

- Twilio is a communication platform, not the party that owns a towing, Police, assessment, or repair task.
- Azure Document Intelligence and Amazon Textract are evidence-processing tools, not evidence sources.
- Auth0 is an identity platform, not a source of claim authority.
- Google Routes is routing infrastructure, not the recovery/repair service provider.
- OpenAI and Bedrock are model infrastructure, not claim decision-makers.
- Tractable can be a claim-domain analytical service, but availability to Northwind remains a commercial/access question.

### 4.2 Technical access does not establish business authority

The merged catalogue keeps these dimensions separate:

- Claimant consent.
- Authority to act for the claimant.
- Staff authority.
- Provider eligibility.
- Provider authentication.
- Commercial/provider relationship.
- Technical API access.
- Delivery/result verification.

No one field or vendor capability proves the others.

### 4.3 Evidence does not equal a claim decision

Police reports, repair quotes, assessor reports, engineering opinions, weather evidence, OCR output, and AI damage-analysis output can support a claim. None of them, by itself, establishes coverage, liability, fraud, claim acceptance, rejection, or settlement.

## 5. Unified external-service lifecycle for implementation

Every external interaction should be represented using the same logical questions even when the real provider differs:

1. **Need** — What business problem is being solved?
2. **Owner** — Who is responsible for the next action: claimant, staff, insurer, external stakeholder, or system?
3. **Authority** — What consent, appointment, staff permission, provider eligibility, or contractual authority is required?
4. **Access form** — Guidance/link, manual request, phone, portal, B2B service, webhook/API, or simulation.
5. **Preparation state** — Not required / required / prepared.
6. **Submission state** — Not submitted / submitted / accepted / failed.
7. **Result state** — Pending / received / unavailable / invalid / superseded / disputed where applicable.
8. **Verification** — What proves the external action or result actually occurred?
9. **Claim impact** — Can FNOL continue while the external item remains pending?
10. **Simulation boundary** — Is the prototype showing a real external event, a prepared request, or a simulated result?

A service accepting a request is not the same as Northwind accepting a claim. A provider acknowledgement is not the same as a completed report. A simulated response is not proof of a live external integration.

## 6. Decisions for the Validation Prototype

The merged evidence supports these implementation decisions:

- Trigger external work from claimant/claim need, not from vendor availability.
- Keep operational services, evidence sources, professional assessments, and enabling platforms as distinct categories.
- Give every pending external item an explicit owner.
- Allow FNOL to continue when later evidence is not needed for the next safe action.
- Preserve provenance, status, limitation, and verification evidence for external outputs.
- Default unproven external integrations to guidance, manual/staff workflow, or clearly labelled simulation.
- Keep high-impact claim decisions under deterministic rules or authorised staff control.

## 7. Unresolved items retained for implementation owners

The merged research does not responsibly answer the following questions:

- The exact Northwind authority and operating process for requesting a Police Traffic Crash Report for a claimant.
- Whether the prototype's vehicle recovery path is claimant-arranged, staff-arranged, insurer-network dispatch, or guidance only.
- Which repair pathway is canonical for the prototype: claimant-selected, insurer-authorised, or both.
- Who can appoint assessors/engineers and which status is externally observable.
- Whether FENZ information is claimant-requested, staff-prepared, or simulated in the prototype.
- Which MetService product/access form Northwind would actually use.
- Whether Northwind has any commercial/API/data-use agreement with Tractable.
- The precise Home workflow state used for NHC handling.
- Whether Northwind would ever request retailer/bank/valuer evidence directly.
- Whether any P3.1 vendor has been procured, security-reviewed, contractually approved, or configured for real Northwind data.

These items must remain unresolved rather than being inferred from generic vendor documentation.

## 8. Handoff to P5 and implementation work

P5 should use this catalogue to define service-specific sharing and consent rules. It should not write one global third-party consent rule.

For each service, P5 should determine:

- Which fields may be recorded internally.
- Which fields may be sent externally.
- Who can authorise the send.
- Whether claimant consent is required and how withdrawal affects future sends.
- Which audit evidence must be stored.
- Which result fields are claimant-visible versus staff-only.
- What happens when authority is missing, withdrawn, expired, or disputed.

Later implementation work should bind adapters and Runtime actions to this catalogue rather than creating provider-specific semantics in isolation.

## 9. Source and provenance register

### 9.1 P3.1 technology/vendor sources supplied by LLL263

The P3.1 input supplied explicit official links. These links are preserved here because they are part of the upstream research evidence:

- Twilio Programmable Messaging: https://www.twilio.com/docs/messaging
- Twilio A2P 10DLC: https://www.twilio.com/docs/messaging/compliance/a2p-10dlc
- Twilio Privacy Notice: https://www.twilio.com/en-us/legal/privacy
- Microsoft Azure Document Intelligence data, privacy, and security: https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/document-intelligence/data-privacy-security
- Microsoft Azure custom document models: https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/train/custom-model?view=doc-intel-4.0.0
- Auth0 Data Privacy and Compliance: https://auth0.com/docs/secure/data-privacy-and-compliance
- Okta Privacy Policy: https://www.okta.com/privacy-policy/
- Google Maps Routes API overview: https://developers.google.com/maps/documentation/routes/overview
- Google Maps Routes API usage and billing: https://developers.google.com/maps/documentation/routes/usage-and-billing
- Google Maps Platform Terms of Service: https://cloud.google.com/maps-platform/terms/
- OpenAI Services Agreement: https://openai.com/policies/business-terms/
- OpenAI API data controls: https://developers.openai.com/api/docs/guides/your-data
- Amazon Bedrock: https://aws.amazon.com/bedrock/
- Amazon Textract FAQs: https://aws.amazon.com/textract/faqs/
- AWS Data Privacy Center: https://aws.amazon.com/compliance/data-privacy/
- Sendbird customer support: https://sendbird.com/features/customer-support
- Sendbird Chat documentation: https://sendbird.com/docs/chat
- Tractable auto insurance solutions: https://www.tractable.ai/solutions/auto-insurance/
- Tractable Trust Center: https://www.tractable.ai/trust-center/
- New Zealand Office of the Privacy Commissioner — Complying with the Privacy Act: https://www.privacy.org.nz/responsibilities/your-obligations/

### 9.2 P3.2 claim-stakeholder sources supplied by jxu316-arch

The P3.2 source register identifies:

- Insurance Council of New Zealand — Annual Report 2025.
- Insurance Council of New Zealand — North Island weather events claims 96% settled.
- New Zealand Police — Use 105.
- New Zealand Police — Traffic crash reporting.
- New Zealand Police — Request a Traffic Crash Report.
- Natural Hazards Commission Toka Tū Ake — About NHCover.
- Natural Hazards Commission Toka Tū Ake — Claims process.
- Fire and Emergency New Zealand — Official information requests.
- ACC — Lodging a claim for a patient.
- MetService — Weather analysis and reporting.
- Tower — Hello Claims and Panel Quote integration.
- Office of the Privacy Commissioner — Principle 11: Disclosure of personal information.
- AA Insurance — Motor accident and repair guidance.
- AMI — Roadside Rescue.
- Tractable — Auto insurance solutions.

The supplied P3.2 PDF does not reproduce the exact URLs for these sources. The merged catalogue therefore preserves the source titles and their evidence limits without inventing links. Exact URLs should be recovered from the original research notes or verified separately before a repository document claims source-link completeness.

## 10. P3.3 acceptance summary

This final merged output provides one catalogue covering:

- Stakeholder or vendor identity.
- Business capability.
- Service/access form.
- Inputs.
- Outputs and lifecycle states.
- Consent and authority boundaries.
- Provenance.
- Failure and pending-state treatment.
- Simulation/live-integration boundary.

It deliberately preserves unresolved access, authority, procurement, and provider-relationship questions instead of converting generic public documentation into false Northwind capability claims.

---

This is the final merged P3.3 delivery assembled from the supplied P3.1 and P3.2 materials. I am leaving #588 open for the normal team review/acceptance flow rather than closing or changing Kanban state manually.
