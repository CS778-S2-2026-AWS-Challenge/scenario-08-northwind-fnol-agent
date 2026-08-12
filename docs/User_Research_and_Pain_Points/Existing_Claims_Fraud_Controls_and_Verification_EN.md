# Fraud Controls and Authenticity Verification in Existing Insurance Claims

## Research Scope

This report reviews publicly available material from State Insurance, Tower Insurance, NZI, Westpac, and the Insurance Council of New Zealand (ICNZ). It focuses on one question:

> **Which fraud controls, verification activities, and authenticity checks already exist in real insurance claim processes?**

In this report, fraud control does not mean only a dedicated fraud-detection system. It also includes controls used during claims to verify that:

- an incident occurred;
- the reported loss is genuine;
- the claimant is entitled to claim;
- the same loss has not been claimed more than once; and
- information provided at different stages is consistent.

Customer-facing claim pages do not disclose every internal fraud rule, scoring method, investigation rule, or decision threshold. This report therefore records only controls that are explicitly supported by public material and does not infer undisclosed internal behaviour.

### Citation provenance note

The Chinese source document contained citation tokens tied to an earlier research session rather than durable public URLs. Those opaque tokens have not been reproduced as if they were valid references. Before this report is used as formal evidence, each claim should be linked to the corresponding current State, Tower, NZI, Westpac, or ICNZ source and checked for currency.

## Main Types of Insurance Fraud Addressed by the Industry

ICNZ describes insurance fraud as dishonest conduct, or intentional failure to meet policy requirements, used to obtain an insurance benefit to which a person is not entitled. ICNZ states that much insurance fraud occurs at claim stage. Public examples include:

- exaggerating a claim;
- reporting an incident or loss that did not occur;
- deliberately causing a loss, such as arson or vehicle theft; and
- intentionally withholding material information requested by an insurer.

Public insurance material shows that fraud control is not a single “fraud check”. It is distributed across the claim process.

| Fraud or risk | Existing control approach |
|---|---|
| Fabricated incident | Incident date, time, location, narrative, police reference, and witness checks |
| Fabricated loss | Photos, receipts, proof of purchase, and assessment |
| Exaggerated loss value | Quotes, estimates, repair reports, and assessor review |
| Claim for property not owned by the claimant | Proof of ownership, purchase date, and ownership confirmation |
| Duplicate claim for the same loss | Insurance Claims Register |
| Non-disclosure of previous claims | Claim history, ICR, and disclosure questions |
| Non-disclosure of driving risk | Licence, previous accidents, offences, and convictions |
| Other insurance covering the same property | Other-insurance information |
| Suspicious theft or intentional damage | Police report, alarm status, and detailed incident information |
| Suspicion reported by an external party | Fraud-reporting channel and investigation team |

## Authenticity Verification at Claim Lodgement

### Identity, Policy, and Insurance-Relationship Checks

NZI Motor Vehicle and Property Electronic Claims Advice forms first establish the insured person's name, address, contact details, policy number, policy wording, name on the policy, excess, and premium status. Before detailed incident handling, the process establishes:

> **Who is claiming → which policy applies → whether the insurance relationship exists.**

For motor claims, the published form also checks:

- whether the driver is the insured person;
- the relationship between the driver and the insured person;
- whether the driver had the owner's permission;
- whether the driver has other motor insurance;
- whether the insured person confirms ownership of the vehicle;
- whether a finance arrangement exists; and
- whether the vehicle or accessories are insured elsewhere.

These questions do not determine fraud. They establish factual relationships needed to verify the claim. Other-insurance information can identify a possible cross-insurer claim, while ownership confirmation helps establish whether the claimant owns the claimed asset.

### Mandatory Authenticity Confirmation

NZI's forms include an **Affirmation Record**. When a separate formal claim form has not been completed, this affirmation is mandatory.

The claimant acknowledges that:

- some claim information may be recorded in the Insurance Claims Register;
- NZI may exchange claim information with other authorised parties;
- the claimant must have authority to provide another person's information;
- personal information is handled under the NZI Privacy Policy; and
- questions must be answered honestly, otherwise the claim or policy may be affected.

The process is therefore not simply:

```text
Customer submits information
        ↓
Insurer accepts it as fact
```

It is closer to:

```text
Customer submits information
        ↓
Customer acknowledges disclosure, data-sharing, and honesty requirements
        ↓
Information becomes part of a verifiable claim record
```

This is consistent with the Fair Insurance Code. A claimant is expected to provide honest, complete, current, and relevant information and to cooperate with reasonable information requests. The insurer should explain what information is required and what steps will follow.

### Historical Information and Risk-Fact Checks

The NZI Motor Vehicle form asks not only about the current incident but also about driver history. Published questions cover whether the driver has previously:

- been refused insurance;
- had a policy cancelled or not renewed;
- had a motor accident in the previous seven years;
- committed a driving or criminal offence; or
- had a licence cancelled, suspended, or restricted.

The form also records licence number, version, issue date, expiry date, and special conditions.

The NZI Property form similarly asks whether the insured person has previously been refused insurance, had a policy cancelled or not renewed, or had a criminal conviction in the previous seven years.

ICNZ's disclosure guidance also identifies previous claims, declined claims, traffic violations, accidents, vehicle use, and non-factory modifications as potentially relevant information.

An important existing fraud-control activity is therefore:

> **Checking consistency between the current claim and historical insurance, claim, or driving information.**

## Evidence, Third-Party Information, and Incident Verification

### Supporting Evidence

Evidence collection is the most common publicly visible authenticity control across the reviewed sources.

ICNZ claim guidance recommends preparing photos, police reports, receipts, and other documents. Property claims may be supported by receipts, invoices, proof of purchase, and photos showing that the claimant owned the item and that it was damaged. A generic product image downloaded from the internet does not establish ownership or loss.

Tower publishes different evidence requirements by claim type, including:

- **Contents:** receipt or proof of purchase, serial number, damage photos, and police file number;
- **House or landlord:** contact details of involved parties, damage photos, repair reports, and police file number;
- **Business:** receipts, photos, invoices, statements, proof of expenses and income, and staff numbers and wages; and
- **Travel:** itinerary, cancellation confirmation, refund details, additional expenses, repair reports, and police report.

Tower states that uploading supporting documents or photos can help it validate a claim more quickly. These files are therefore part of claim validation, not merely attachments.

State's public claim journey also allows customers to answer questions and upload supporting files through the State App or My State. A claim may then enter auto-approval or review, with more complex claims receiving further review. The public page supports the existence of a “supporting information plus review” structure, but it does not disclose a particular fraud model.

### Police Information

Police records are a recurring independent evidence source.

Westpac advises customers to report vehicle accidents involving injury to Police. Theft or intentional damage should also be reported promptly, and the incident number should be retained for the claim. Customers are advised to photograph the scene, damage, surroundings, and other vehicles.

At lodgement, Westpac may request:

- the damage or loss;
- when, why, and how the incident occurred;
- action taken to prevent further loss;
- other driver and witness details; and
- the Police incident report number.

The insurer's team then reviews the supplied information before assessment.

The NZI Motor Vehicle form asks whether Police attended, the attending officer's details, the Police reference, and whether charges were or may be laid.

For burglary, theft, unexplained loss, and intentional damage, the NZI Property form asks whether Police were notified, the Police reference number, whether a burglar alarm existed, and whether it was operating at the time.

For theft and intentional-damage claims, the published verification chain is therefore deeper than for routine damage:

```text
Customer statement
        ↓
Police reference
        ↓
Property or security information
        ↓
Insurer review
```

### Witness and Third-Party Information

Westpac advises customers to collect other drivers' and witnesses' names, phone numbers, vehicle registrations, and insurance details. NZI's Motor Vehicle form separately records witness names, addresses, phone numbers, and whether a witness was a passenger.

This provides information that is not entirely dependent on the claimant's account. Under the Fair Insurance Code, an insurer may rely on relevant third-party information when handling a complex claim, but should request and consider only information that is relevant or material to the claim investigation and decision.

### Assessor Verification

ICNZ states that, for house claims, an insurer will commonly arrange an assessor to inspect damage, record the loss, and identify required repairs.

Tower similarly states that some claims may be approved immediately, while house or vehicle damage may require assessor review.

Verification may therefore extend beyond digital documents:

```text
Submitted information
        ↓
Photos, receipts, and reports
        ↓
Insurer review
        ↓
Assessor inspection where required
        ↓
Claim decision
```

## Insurance Claims Register and Cross-Insurer Checks

The **Insurance Claims Register (ICR)** is one of the clearest publicly documented industry-level fraud controls.

ICNZ states that the ICR is intended to detect and prevent insurance fraud, especially non-disclosure and double dipping. It is an independently operated fraud-prevention tool that records claims received by participating insurers and permits claims-data sharing under applicable permissions.

ICNZ explains that a claim made to an ICR member insurer within the relevant retention period may appear in the register. Participating insurers advise customers that claims will be recorded and provide privacy notices in proposal, renewal, and claim forms. Customers may access and correct their information as provided by law.

NZI Motor Vehicle and Property Electronic Claims Advice forms provide a practical example. Both require the claimant to acknowledge that some claim details will be recorded in the ICR and that the insurer may access relevant claim information.

The publicly documented control can be expressed as:

```text
New claim
        ↓
Claim details recorded
        ↓
Insurance Claims Register
        ↓
Comparison with existing claim history
        ↓
Possible non-disclosure or duplicate-claim indicators
        ↓
Further assessment where required
```

The final steps describe the purpose of the ICR rather than a claim that every insurer uses identical automated decision rules. Public information supports the ICR's role in helping identify non-disclosure, double dipping, and related risk patterns.

## Comparison of Publicly Documented Controls

| Source | Publicly confirmable fraud or verification controls | Disclosure level |
|---|---|---|
| **State Insurance** | Supporting files, auto-approval for some simple claims, review of complex claims, and IAG Fraudline or email reporting route | Customer claim pages do not disclose fraud scoring or internal investigation rules |
| **Tower Insurance** | Supporting documents and photos, proof of purchase, Police reference, repair reports, assessor review, Fraud Report Form, investigation contact, and a published automated fraud/risk-screening initiative | One of the more detailed public source sets reviewed |
| **NZI** | Mandatory affirmation, ICR, authorised information exchange, honesty requirement, other-insurance questions, ownership, driver and licence history, criminal or driving history, Police, witness, and alarm status | Claim forms expose detailed verification fields |
| **Westpac Vehicle Insurance** | Proof of purchase, incident details, photos, other drivers, witnesses, Police incident number, and insurer assessment | Public pages describe evidence and assessment controls but not a dedicated fraud model |
| **ICNZ Making a Claim** | Receipts, invoices, proof of ownership, photos, Police reference, assessor, and detailed incident information | Industry-level verification guidance |
| **ICNZ Claims Register** | Cross-insurer claim history, non-disclosure detection, and double-dipping detection | Explicit industry fraud-prevention infrastructure |
| **ICNZ Fair Insurance Code** | Honest, complete, and current information; materiality; claimant cooperation; relevant-information investigation; and third-party information | Conduct and information framework for ICNZ members |

## Verification Is Not a Fraud Determination

An important distinction must be retained:

> **A verification control is not a finding of fraud.**

A Police reference, receipt, or assessor report is used to verify a claim. The ICR may help identify duplicate claims or non-disclosure. Suspected fraud arises only when relevant evidence and investigation support that concern.

The public material does not establish a rule that “one inconsistent field equals fraud”. The Fair Insurance Code instead requires insurers to request and consider relevant or material information and to explain claim decisions clearly.

## Tower's Published Automated Fraud-Screening Example

In October 2021, Tower publicly announced a partnership with FRISS to further automate fraud and risk screening and distinguish genuine from suspicious claims in real time.

Tower stated that the approach would use predictive models, network analysis, and text mining. The intended outcome was to move lower-risk claims through a faster path while applying more targeted screening to higher-risk claims.

The evidence supports the statement:

> **“Tower announced in 2021 that it would implement FRISS for automated fraud and risk screening.”**

It does not support the broader statement:

> “Tower currently processes every claim through FRISS.”

Current public claim pages do not establish that FRISS now covers every Tower product or claim. The public evidence confirms the 2021 implementation announcement and that Tower continues to provide formal fraud-reporting and investigation contact channels.

Tower permits suspected fraud to be reported through a fraud report form and may contact the reporter for more information. It states that reporter information is handled under the Privacy Act 2020 and Tower's Privacy Policy and is not supplied to the person being reported.

State also provides a separate suspected-fraud reporting path through IAG Fraudline, a fraud email address, and the Insurance Fraud Bureau.

## Reconstructed Existing Fraud-Control Process

The reviewed State, Tower, NZI, Westpac, and ICNZ materials support the following common industry structure. It is not presented as the complete internal process of any one insurer.

```text
Claim is lodged
        ↓
Identify policy and insured person
        ↓
Collect incident details
Date, time, location, cause, and description
        ↓
Confirm material information
Ownership, driver, insurance, and claim history
        ↓
Customer honesty and disclosure confirmation
        ↓
Collect supporting evidence
Photos, receipts, proof of purchase,
Police reference, repair reports,
witness and third-party details
        ↓
Claim-history or cross-insurer check
Insurance Claims Register where applicable
        ↓
Initial claim assessment
        ↓
       ┌───────────────────────┐
       │                       │
Sufficient or lower      More verification
complexity               required
       │                       │
       │                  Assessor
       │                  Third-party information
       │                  Additional documents
       │                  Investigation
       │                       │
       └───────────┬───────────┘
                   ↓
             Claim decision
```

## Five Layers of Publicly Confirmed Fraud Control

### 1. Information Integrity

Policy, driver, incident, ownership, historical information, and honesty affirmation establish a record that can be checked.

### 2. Evidence Verification

Photos, receipts, proof of purchase, repair reports, and Police records support the reported incident and loss.

### 3. External Verification

Witnesses, Police, assessors, and other third parties supplement or test the claimant's account.

### 4. Historical and Cross-Insurer Verification

The Insurance Claims Register supports claim-history checks and helps identify non-disclosure and double dipping.

### 5. Escalation and Investigation

Complex claims may be referred for further review or assessment. State and Tower publish suspected-fraud reporting channels, and Tower has published an automated fraud/risk-screening initiative.

## Conclusion

> **Fraud control in real insurance claims is not one standalone step. It is a layered process comprising identity and policy confirmation, honesty declarations, evidence collection, Police, witness and assessor verification, historical claim checks, the Insurance Claims Register, complex-claim review, and investigation where required.**

NZI's published claim forms show how controls enter the reporting fields. ICNZ provides the ICR and disclosure framework. Tower has publicly described automated fraud/risk screening and independent fraud-reporting mechanisms.

The most important implementation boundary is that verification evidence and risk indicators support professional review. They do not by themselves establish fraud, authorise claim denial, or remove the need for proportionate human judgement.
