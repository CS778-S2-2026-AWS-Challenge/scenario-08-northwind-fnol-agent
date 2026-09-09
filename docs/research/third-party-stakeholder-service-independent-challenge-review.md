# Third-party stakeholder and service independent challenge review

This research record is the formal P3.2 delivery for Issue #587. It reconciles the earlier independent challenge notes against the final P3.1 stakeholder and source register in `third-party-stakeholder-service-research.md`, preserving accepted facts, disputed claims, qualifications, unresolved access limits, and simulation boundaries for P3.3.

This document does not select providers, create a Northwind service contract, or claim live provider access. The disposition labels below are research-review labels only; they are not API, persistence, external-task, or Runtime states.

## Review method

The P3.2 review applies four dispositions:

- **Accepted:** The P3.1 proposition is supported for the bounded purpose stated.
- **Accepted with qualification:** The service or evidence form is supported, but authority, operating form, access, timing, or claim impact needs an explicit boundary.
- **Disputed:** A broader proposition is not supported by the cited evidence and must not pass into P3.3 unchanged.
- **Unresolved:** The public evidence does not establish the Northwind-specific answer required for implementation.

The review uses the final P3.1 stable `P3-*` identifiers and `S01-S28` source coordinates as the upstream research record. It challenges what those sources can support; it does not silently replace the source register or infer Northwind procurement, credentials, authority, service levels, or production readiness.

## Challenge claim-journey participants

The following table covers every final P3.1 claim-journey participant identifier.

| P3.1 ID | P3.2 disposition | Challenge result | Source coordinates |
| --- | --- | --- | --- |
| `P3-NZP-REPORT` | Accepted with qualification | Police 105 and related claimant reporting channels are valid public pathways. Treat claimant reporting, later case updates, and any insurer-side action as separate activities. No evidence establishes Northwind submission or read access. | S01 |
| `P3-NZP-TCR` | Accepted with qualification | A Traffic Crash Report can be requested by a person or representative, but representative authority and identity evidence matter. No standing Northwind authority, guaranteed release, or unrestricted API is established. | S02-S03 |
| `P3-VEHICLE-RECOVERY` | Accepted with qualification | Vehicle recovery is a valid claim-journey need. Roadside breakdown membership must not be treated as collision recovery, and claimant-arranged, staff-arranged, insurer-network, and guidance-only forms remain distinct until Northwind chooses one. | S04-S05 |
| `P3-REPAIRER` | Accepted with qualification | Repair inspection, quotation, repair, and progress evidence are valid. Claimant-selected and insurer-authorised or network repair paths have different appointment and authority boundaries; competitor networks do not prove a Northwind arrangement. | S06-S07 |
| `P3-ASSESSOR` | Accepted with qualification | Assessment or specialist review is a real claims function, normally later than minimum FNOL intake. Northwind appointment authority, provider eligibility, observable external status, and service level remain unresolved. | S06-S07 |
| `P3-EMERGENCY-WORKS` | Accepted with qualification | Urgent mitigation to make property safe is a valid pathway. Public guidance does not establish Northwind contractor networks, spending authority, reimbursement limits, or an electronic dispatch mechanism. | S06, S08 |
| `P3-FENZ-INFO` | Accepted with qualification | FENZ information requests are valid evidence paths, but published request handling is asynchronous and may involve identity or authority checks. It must not be modelled as a guaranteed synchronous FNOL service or insurer API. | S09-S10 |
| `P3-METSERVICE` | Accepted with qualification | Historical weather reporting can support event evidence. It does not establish coverage, cause, liability, or claim acceptance; the specific product, licence, price, and Northwind access form remain unresolved. | S11 |
| `P3-NHC` | Accepted with qualification | The insurer-mediated NHCover pathway is supported for residential building and land. Any extension to generic contents cover is disputed; Northwind partner status and exact workflow remain unresolved. | S12-S14 |
| `P3-CONTENTS-EVIDENCE` | Accepted with qualification | Retailers, banks, manufacturers, service centres, and valuers can be evidence sources for ownership, value, or condition. They are not Northwind integrations by default; claimant retrieval and upload remains the safe baseline until direct retrieval authority and service access are proven. | S06 |
| `P3-BROKER` | Accepted with qualification | Brokers or authorised intermediaries can assist with claim coordination, but authority is bounded by claimant authorisation or delegated arrangements. Broker participation is not universal and does not itself create Northwind delegation. | S07, S14 |
| `P3-ACC-PROVIDER` | Accepted with qualification | Registered providers can lodge ACC injury claims with the patient. This is an adjacent injury-support and authority-boundary example, not evidence that the Northwind FNOL Agent may diagnose, lodge ACC claims, or make an ACC or insurance coverage decision. | S15 |

## Challenge enabling-platform candidates

The enabling candidates are challenged separately because technical capability is not claim-journey authority.

| P3.1 ID | P3.2 disposition | Challenge result | Source coordinates |
| --- | --- | --- | --- |
| `P3-EN-MESSAGING` | Accepted with qualification | Twilio supports generic messaging and verification capability. Sender setup, procurement, consent basis, opt-out handling, credentials, and permitted claim content remain unresolved for Northwind. | S16 |
| `P3-EN-DOC-AZURE` | Accepted with qualification | Azure Document Intelligence supports document analysis. Extracted output remains machine-derived evidence, not a confirmed claim fact; approved region, subscription, retention, and data-use terms are unresolved. | S17 |
| `P3-EN-IDENTITY` | Accepted with qualification | Auth0 supports identity and access-management capability. Authentication does not establish authority to disclose claim data or perform a business action; Northwind tenant and procurement status are unresolved. | S18 |
| `P3-EN-ROUTES` | Accepted with qualification | Google Routes can provide route, distance, and duration information. It is routing infrastructure, not a towing or repair provider; project access, licence, billing, and data-minimisation decisions remain unresolved. | S19-S20 |
| `P3-EN-MODEL` | Accepted with qualification | OpenAI API and Amazon Bedrock demonstrate generic model-inference capability. Model output remains advisory and Northwind model, region, account, retention, personal-data scope, evaluation, and production approval are unresolved. | S21-S23 |
| `P3-EN-DOC-AWS` | Accepted with qualification | Amazon Textract supports document extraction. Extracted fields remain machine-derived evidence; region, IAM, storage, retention, supported claim-document set, and production authority remain unresolved. | S24 |
| `P3-EN-CONVERSATION` | Accepted with qualification | Sendbird supports generic chat capability. Claim identity mapping, claimant/staff visibility, retention, procurement, and Northwind live access remain unresolved. | S25 |
| `P3-EN-DAMAGE-AI` | Unresolved for Northwind use | Tractable material supports generic image-based damage-analysis capability, but commercial access, permitted claim-data use, regional availability, thresholds, result semantics, and operational fitness are not established. P3.3 must retain this as unavailable or simulation-only unless separately evidenced. | S26-S27 |

## Record disputed and qualified propositions

The independent review rejects or narrows the following interpretations before they reach P3.3:

- **Roadside assistance is not collision recovery.** S04-S05 support distinct post-accident and breakdown pathways; membership in a roadside product does not prove collision recovery eligibility or insurer dispatch.
- **NHC is not a generic contents service.** S12-S14 support residential building and land NHCover and insurer-mediated handling; the broader contents interpretation is not supported.
- **Technical access is not business authority.** S16-S27 establish generic platform capabilities only. They do not establish Northwind procurement, credentials, approved data use, disclosure authority, or production readiness.
- **Evidence is not a claim decision.** Police, FENZ, weather, assessment, repair, contents evidence, document extraction, and damage analysis may contribute evidence but do not independently establish coverage, liability, fraud, acceptance, rejection, or settlement.
- **Authentication is not action authority.** Identity evidence can establish who an actor is without establishing permission to submit a report, request a record, appoint a provider, disclose claim data, or decide a claim.
- **An acknowledgement is not completion.** Request acknowledgement, accepted external work, received evidence, verified result, and Northwind claim decision must remain distinguishable in P3.3.

## Challenge the source register

The source-by-source challenge below preserves the final P3.1 `S01-S28` coordinates and records the evidentiary boundary P3.3 must carry forward.

| Source | P3.2 challenge disposition | Boundary retained for P3.3 |
| --- | --- | --- |
| S01 | Accepted with qualification | Supports claimant-facing Police reporting and updates; does not prove Northwind submission or read access. |
| S02 | Accepted with qualification | Supports TCR request routes and access categories; does not prove guaranteed release or API access. |
| S03 | Accepted with qualification | Supports identity and representative-authority requirements; does not prove a standing Northwind authority arrangement. |
| S04 | Accepted with qualification | Shows post-accident towing can exist in an insurer pathway; does not define Northwind cover or dispatch. |
| S05 | Accepted and narrowing | Explicit collision exclusion prevents treating roadside breakdown cover as collision recovery. |
| S06 | Accepted with qualification | Supports evidence, assessor, repair, emergency-work, and contents-evidence categories; does not define one insurer's exact workflow. |
| S07 | Accepted with qualification | Supports third-party oversight, delegated-authority, broker, and specialist boundaries; does not prove routine Northwind arrangements. |
| S08 | Accepted with qualification | Supports urgent works and insurer/NHC responsibilities; does not prove Northwind partner status or spending authority. |
| S09 | Accepted with qualification | Supports FENZ OIA request inputs, channels, and timing; does not prove guaranteed incident evidence or insurer API. |
| S10 | Accepted with qualification | Supports identity and written-authority privacy boundaries; does not establish a Northwind-specific disclosure path. |
| S11 | Accepted with qualification | Supports historical weather-report capability; does not establish claim decisions, pricing, licensing, or Northwind access. |
| S12 | Accepted and narrowing | Supports residential building and land NHCover; contradicts a generic contents interpretation. |
| S13 | Accepted with qualification | Supports insurer-managed and limited direct-NHC lodgement paths; does not establish Northwind partner or integration status. |
| S14 | Accepted with qualification | Supports claimant, broker, insurer, evidence, and specialist responsibilities; does not define a Northwind workflow contract. |
| S15 | Accepted with qualification | Supports provider-led ACC claim lodgement and consent; does not authorise Northwind to diagnose, lodge, or decide ACC or insurance coverage. |
| S16 | Accepted as enabling capability only | Supports messaging tooling; Northwind sender registration, consent basis, procurement, and content policy remain unresolved. |
| S17 | Accepted as enabling capability only | Supports document-analysis processing and data-handling facts; does not prove Northwind subscription, approved region, or claim-fact authority. |
| S18 | Accepted as enabling capability only | Supports identity-platform capability; does not establish business-action authority or Northwind readiness. |
| S19 | Accepted as enabling capability only | Supports route computation; does not establish a recovery provider or Northwind project access. |
| S20 | Accepted as enabling capability only | Establishes commercial terms and licence constraints; does not establish Northwind acceptance or approved data use. |
| S21 | Accepted as enabling capability only | Supports official OpenAI API data-control documentation; does not prove Northwind account, model approval, or retention choice. |
| S22 | Accepted as enabling capability only | Supports generic Bedrock model capability; does not prove Northwind model access, region, guardrails, or production approval. |
| S23 | Accepted as enabling capability only | Supports generic Bedrock security and privacy capabilities; does not substitute for a Northwind risk assessment. |
| S24 | Accepted as enabling capability only | Supports Textract inputs and extraction outputs; does not prove Northwind configuration or confirmation of extracted facts. |
| S25 | Accepted as enabling capability only | Supports chat SDK/API functionality; does not prove Northwind identity, visibility, retention, or procurement. |
| S26 | Accepted for generic capability; unresolved for Northwind | Supports generic vehicle-damage analysis and API-integration claims; Northwind access, regional availability, thresholds, and operational fitness remain unresolved. |
| S27 | Accepted for vendor privacy evidence only | Supports published vendor privacy/security information; does not establish a Northwind security review or data-use agreement. |
| S28 | Accepted with legal-boundary qualification | Supports general New Zealand personal-information disclosure limits; does not provide service-specific legal advice or define Northwind consent design. |

## Hand unresolved questions to P3.3

The following items remain explicit P3.2 outputs. `Unresolved` here is a research status, not an implementation state. P3.3 co-owners are responsible for either retaining the gap with safe boundaries or recording a supported decision.

| Gap | Related P3 IDs | Status | Owner | Required P3.3 action |
| --- | --- | --- | --- | --- |
| Police TCR authority | `P3-NZP-TCR` | Unresolved | #588 co-owners | Define what claimant authority and evidence would permit a Northwind-side request, or preserve claimant/manual handling. |
| Vehicle recovery operating form | `P3-VEHICLE-RECOVERY` | Unresolved | #588 co-owners | Choose or preserve as unknown among claimant-arranged, staff-arranged, insurer-network, and guidance-only forms. |
| Repair pathway and appointment authority | `P3-REPAIRER`, `P3-ASSESSOR` | Unresolved | #588 co-owners | Distinguish claimant-selected from insurer-authorised work and record who can appoint each participant. |
| Observable external completion evidence | Multiple participant IDs | Unresolved | #588 co-owners | State what acknowledgement, accepted work, evidence receipt, verified result, and completion evidence are observable without inventing provider states. |
| FENZ operating form | `P3-FENZ-INFO` | Unresolved | #588 co-owners | Preserve claimant-requested, staff/manual, or simulation-only options until authority and access are established. |
| MetService operating form | `P3-METSERVICE` | Unresolved | #588 co-owners | Distinguish public information, formal report/service, manual procurement, and simulation; do not infer access. |
| NHC prototype state and contents boundary | `P3-NHC`, `P3-CONTENTS-EVIDENCE` | Unresolved | #588 co-owners | Keep NHCover Home-specific and define how separate contents evidence remains outside that pathway. |
| Broker actionability | `P3-BROKER` | Unresolved | #588 co-owners | Decide whether broker is an actionable catalogue service or an authority-boundary participant only. |
| ACC actionability | `P3-ACC-PROVIDER` | Unresolved | #588 co-owners | Keep provider-led ACC lodgement outside Northwind action authority unless a separately authorised pathway is established. |
| Direct evidence retrieval | `P3-CONTENTS-EVIDENCE` | Unresolved | #588 co-owners | Default to claimant retrieval/upload unless direct retrieval service and disclosure authority are separately supported. |
| Enabling-platform production access | All `P3-EN-*` | Unresolved | #588 co-owners | Preserve unknown/unavailable/simulation-only access unless procurement, credentials, permitted data use, regional availability, and governance are evidenced. |

## State the P3.2 result

P3.2 accepts the existence and bounded forms of the final P3.1 claim-journey participants while narrowing claims that could be mistaken for Northwind authority or live technical access. The strongest disputes are the generic-contents interpretation of NHCover and any treatment of roadside breakdown membership as collision recovery.

All eight enabling-platform candidates remain technology capabilities rather than claim stakeholders. Their generic capabilities are supported, but Northwind production access is unresolved; `P3-EN-DAMAGE-AI` in particular must remain unavailable or simulation-only until its access, data-use, regional, threshold, and result boundaries are verified.

This review is the formal independent challenge input to P3.3. P3.3 must reconcile every stable `P3-*` identifier, preserve `S01-S28` provenance, and retain the unresolved gap owner/status/action coordinates above rather than silently defaulting them.
