# Insurance FNOL Pain Point Analysis

## Purpose and Scope

This document identifies and prioritises user pain points in the First Notice of Loss (FNOL) journey, from the moment an incident occurs through initial reporting, claim creation, and handoff to the next processing stage.

The analysis combines:

- exploratory survey results;
- three user personas: First-Time Claimant, Efficiency-Seeking Claimant, and Urgent or Complex Claimant;
- existing FNOL process and field analysis;
- public customer reviews and complaints;
- official and industry research;
- research into AI-to-human handoff and context continuity.

The percentages in this document are exploratory survey findings. They support early prioritisation but should not be interpreted as population estimates.

## Executive Finding

The central user problem is not simply that claim forms are long. Users lose confidence and control because they do not know:

- what to do immediately after the incident;
- what information or evidence is required;
- whether the insurer has received enough information;
- what will happen next or how long it will take;
- who currently owns the next action;
- whether an AI assistant has understood the incident correctly;
- whether a human will take over when the situation becomes urgent or complex;
- why information is being requested or how a decision was reached.

These gaps create repeated work, avoidable contact, slower handling, and distrust. The desired experience is not full automation. It is a guided, transparent, and continuous journey in which AI assists with information collection while humans remain accessible and accountable.

---

## Prioritisation Method

Pain points were prioritised using four factors:

| Factor | Question |
|---|---|
| **Frequency signal** | Does the survey or public feedback repeatedly identify the issue? |
| **Task impact** | Can the issue prevent or delay successful FNOL completion? |
| **Emotional impact** | Does it increase anxiety, frustration, or distrust? |
| **Operational impact** | Does it cause repeat contact, rework, inconsistent information, or unnecessary escalation? |

Priority levels are comparative research judgements, not statistically validated severity scores.

## Prioritised Pain Point Map

| ID | Pain point | Journey stage | Primary personas | Priority |
|---|---|---|---|:---:|
| **P1** | Users do not know what to do or what evidence to collect | Incident and preparation | First-Time; Urgent/Complex | **Critical** |
| **P2** | Users cannot see progress, timing, ownership, or the next step | After submission | Efficiency-Seeking; Urgent/Complex | **Critical** |
| **P3** | Information and documents are repeatedly requested across channels and staff | Reporting and follow-up | Efficiency-Seeking; all personas | **Critical** |
| **P4** | Human escalation is unclear and context may be lost during handoff | Escalation and triage | Urgent/Complex; all personas | **Critical** |
| **P5** | Users fear that AI may misunderstand the incident or overstep its role | AI-assisted reporting | All personas | **High** |
| **P6** | Insurance terminology, evidence requirements, and coverage are difficult to understand | Reporting and assessment | First-Time; Efficiency-Seeking | **High** |
| **P7** | Responsibility and claim decisions are not explained clearly enough | Follow-up and decision | Efficiency-Seeking; Urgent/Complex | **High** |
| **P8** | Verification can feel accusatory or unfair when discrepancies are not explained | Verification and dispute | Urgent/Complex | **High** |

---

## P1. Unclear Immediate Actions and Evidence Requirements

### User problem

Immediately after an incident, users may need to manage safety, police contact, towing, third-party details, photographs, loss mitigation, and insurance reporting at the same time. The existing process often expects users to know what evidence will be required before they understand the claim journey.

### Survey evidence

For users with no previous claim experience:

| Uncertainty | Survey result |
|---|---:|
| What to do immediately after the incident | 77.8% |
| What photos or evidence to collect | 55.6% |
| Whether police contact is required | 44.4% |
| Whether the damage may be covered | 44.4% |

For users with previous claim experience:

| Difficulty | Survey result |
|---|---:|
| Did not know which photos or evidence were required | 80% |
| Did not know what to do first | 60% |
| Did not know which information to collect | 60% |
| Was unsure whether the incident was covered | 60% |

Across the survey, 64.3% prioritised knowing exactly what information was required.

### User impact

- Important scene evidence may be lost permanently.
- Users may delay reporting because they are unsure how to begin.
- Users may submit incomplete information and receive later document requests.
- Stress increases because users fear that an early mistake will affect the claim.

### Root cause

Insurance processes are organised around structured claim fields, while users think in terms of the event that just happened. Guidance is often separated from the reporting form instead of adapting to the user's situation.

### Pain point statement

> Claimants need situation-specific guidance immediately after an incident because they may not know which safety actions, information, and evidence are time-sensitive.

---

## P2. Lack of Progress, Timing, Ownership, and Next-Step Visibility

### User problem

After submitting an initial report, users often do not know whether enough information has been received, what stage the claim is in, who is responsible, what will happen next, or how long the process is expected to take.

### Survey evidence from previous claim experiences

| Post-submission uncertainty | Survey result |
|---|---:|
| Did not know how long the process would take | 80% |
| Was unsure whether enough information had been provided | 60% |
| Did not know whom to contact if there was a problem | 60% |
| Had to contact the insurer for updates | 60% |
| Did not know what would happen next | 40% |
| Did not know the current claim status | 40% |

Across the survey, 42.9% prioritised knowing what happens next, and 42.9% prioritised being able to track progress.

### Supporting external evidence

Public customer feedback describes unanswered calls, unreturned messages, repeated follow-up, and long periods without meaningful updates. The New Zealand Financial Markets Authority also found that only 43% of surveyed insurers explained in claim acknowledgements how customers would receive progress updates. [FMA Weather Events Claims Insights](https://www.fma.govt.nz/library/reports-and-papers/weather-events-claims-insights/)

### User impact

- Users repeatedly contact the insurer to obtain basic status information.
- Waiting feels longer because there is no visible endpoint or explanation.
- Users cannot coordinate repairers, family, work, transport, or temporary accommodation.
- Silence is interpreted as poor service or lack of action.

### Root cause

Claim status exists internally but is not consistently translated into customer-facing information about stage, responsibility, expected timing, blockers, and next action.

### Pain point statement

> Claimants need visible progress, responsibility, and timing because uncertainty after submission forces them to chase the insurer and reduces trust.

---

## P3. Repeated Information and Fragmented Document Requests

### User problem

Users may provide the same incident description, policy details, or evidence through an online form, chatbot, phone call, email, assessor, or repairer. Different touchpoints may not share one complete claim context.

### Survey evidence

Among users with previous claim experience:

- 40% reported having to repeat information already provided;
- 40% experienced difficulty uploading photos or documents;
- additional information or documents were requested once in 20% of cases and multiple times in 20%;
- 60% were unsure whether they had provided enough information.

### Supporting external evidence

Public reviews include customers being asked again for information already submitted online and having to explain the same situation to different staff members. Salesforce research reports that 56% of customers often have to repeat or re-explain information to different representatives. [Salesforce — Customer Expectations](https://www.salesforce.com/small-business/what-are-customer-expectations/)

The FMA recommends consolidating information requests from internal staff and third parties and ensuring that systems can capture and manage the information supplied. [FMA Weather Events Claims Insights](https://www.fma.govt.nz/library/reports-and-papers/weather-events-claims-insights/)

### User impact

- Claimants spend more time repeating stressful events.
- Staff repeat work already completed elsewhere.
- Later descriptions may differ because of fatigue, time, or question wording.
- Repeated requests make users believe that information has been lost or ignored.
- Inconsistent records may create avoidable verification concerns.

### Root cause

Channels and participants are treated as separate interactions rather than parts of one claim journey. Transcripts, structured fields, attachments, and request history may not remain connected to the same claim record.

### Pain point statement

> Claimants need a “tell us once” experience because repeated collection increases effort, creates inconsistent records, and weakens trust.

---

## P4. Unclear Human Escalation and Loss of Context During Handoff

### User problem

When an AI assistant or digital form cannot handle an urgent, unusual, complex, or disputed situation, users need to know how to reach a human. A transfer is not successful if the human does not receive the previous conversation, confirmed fields, attachments, completed steps, and escalation reason.

### Survey evidence

| Situation in which human support is preferred | Survey result |
|---|---:|
| Immediately after a serious or stressful incident | 64.3% |
| The situation is complex or unusual | 50.0% |
| The digital process is difficult to use | 50.0% |
| There is a disagreement about the claim | 50.0% |
| The required information is not understood | 42.9% |
| Usually prefers fully independent self-service | 7.1% |

### Supporting external evidence

Genesys reports that 95% of consumers consider it important for context to be retained when switching channels. [Genesys — State of Customer Experience](https://www.genesys.com/resources/state-of-cx)

Microsoft's bot-to-human handoff guidance explicitly identifies handoff context and the conversation transcript as information that can accompany an escalation. This supports the need for the human agent to understand why the transfer occurred and what has already been collected. [Microsoft Learn — Transition Conversations from Bot to Human](https://learn.microsoft.com/en-us/azure/bot-service/bot-service-design-pattern-handoff-human?view=azure-bot-service-4.0)

### User impact

- Users must restart the claim conversation after already completing digital steps.
- Urgent cases are delayed by repeated identity and incident questions.
- Repeating a distressing event increases emotional burden.
- Staff cannot distinguish confirmed facts from missing or uncertain information.
- Users may become trapped in automation when they need judgement or authority.

### Root cause

Many services treat escalation as a channel transfer rather than a transfer of claim ownership and information. Technical handoff may occur without operational continuity.

### Pain point statement

> Claimants need a visible human path and complete context transfer because complex claims cannot safely restart whenever the channel changes.

---

## P5. AI Misunderstanding, Loss of Control, and Unclear Decision Boundaries

### User problem

Users are open to AI assistance only when they can verify what the AI understood, correct errors, request a human, and trust that high-impact decisions remain under human responsibility.

### Survey evidence

| Concern about AI-assisted claims | Survey result |
|---|---:|
| AI may misunderstand what happened | 78.6% |
| AI may struggle with a complex or unusual situation | 64.3% |
| AI may make decisions that should be made by a human | 57.1% |
| Personal information may not be secure | 42.9% |
| It may be unclear when a human becomes involved | 21.4% |

Comfort with AI assistance averaged approximately 3.07 out of 5 when human help could be requested at any time. This indicates conditional acceptance rather than support for fully automated claim handling.

### User impact

- Users may avoid the tool or provide less detail if they do not trust it.
- Incorrect extraction may create inaccurate claim records.
- Users may feel unable to challenge how their description was interpreted.
- Automation of coverage, liability, or fraud decisions can create perceived unfairness.

### Root cause

The user cannot always see what the AI extracted, how confident it is, which decisions it is allowed to influence, or when a human will review the case.

### Pain point statement

> Claimants need to confirm AI-generated information and understand its decision boundary because accuracy, control, and human accountability determine whether AI assistance is trusted.

---

## P6. Difficult Terminology, Coverage Uncertainty, and Unclear Requirements

### User problem

Insurance language is often designed around policies, compliance, and internal processing rather than the user's immediate understanding. Terms such as excess, exclusion, non-disclosure, liability, betterment, or insufficient evidence may not explain what the user needs to do.

### Survey evidence

- 60% of users with previous claim experience found insurance terminology difficult;
- 60% were unsure whether the incident was covered when it first happened;
- 50.0% of the overall survey prioritised understanding whether the incident may be covered;
- 64.3% prioritised knowing exactly what information was required.

### Supporting external evidence

The FMA found that consumers had limited understanding of exclusions, cover limits, gradual damage, pre-existing damage, and betterment. It recommended clearer explanations of claim processes, evidence requirements, and customer rights. [FMA Weather Events Claims Insights](https://www.fma.govt.nz/library/reports-and-papers/weather-events-claims-insights/)

### User impact

- Users answer questions without understanding why the information matters.
- They may interpret a request as a sign that the claim will be rejected.
- Coverage expectations formed at purchase may conflict with the claim outcome.
- Users struggle to challenge or correct a decision they do not understand.

### Root cause

Policy language is presented without enough connection to the user's incident, evidence, and required action.

### Pain point statement

> Claimants need plain-language, situation-specific explanations because technical terms do not tell them what a policy condition means for their claim.

---

## P7. Unclear Ownership, Delays, and Decision Explanations

### User problem

Claims may involve service staff, claims handlers, managers, brokers, assessors, repairers, and specialists. Users may not know who owns the current step, where a delay occurred, or who can make a decision.

Public customer feedback also describes broad reasons such as “under review,” “conditions not met,” “misrepresentation,” or “insufficient evidence” without identifying the specific fact, document, policy clause, or action required.

### Evidence

- 60% of users with previous claim experience did not know whom to contact when there was a problem;
- 60% had to contact the insurer for updates;
- 80% did not know how long the process would take;
- public reviews report unanswered calls, inconsistent information from different staff, and unfulfilled callback promises;
- the FMA identified claim ownership confusion created by multiple contact points and recommended clearer lifecycle, role, and responsibility communication.

### User impact

- Users become the coordinators of an internal process they cannot see.
- Delays appear arbitrary even when a valid dependency exists.
- Vague explanations make fair decisions appear predetermined or defensive.
- Disputes escalate because the user cannot identify the relevant evidence or decision-maker.

### Root cause

Internal workflow status is not translated into a clear customer-facing explanation of ownership, dependency, timing, evidence, and decision rationale.

### Pain point statement

> Claimants need clear ownership and specific decision explanations because a claim cannot feel fair or controlled when responsibility and reasoning remain invisible.

---

## P8. Verification That Feels Accusatory or Unfair

### User problem

Claim verification legitimately requires identity, policy, ownership, driver, police, witness, receipt, assessor, and claim-history information. However, users may feel accused when ordinary omissions or inconsistencies are framed using fraud or non-disclosure language without a specific explanation.

### Evidence

Public feedback includes frustration with decisions that cited misrepresentation, document discrepancies, fraud-related clauses, or non-disclosure without clearly identifying:

- what statement was considered inaccurate;
- which document contained a discrepancy;
- which material fact was allegedly omitted;
- what evidence was relied upon;
- how the policy clause applied to the incident.

Official and insurer materials show that verification is distributed across information integrity, evidence checks, third-party information, claim-history checks, assessor review, and escalation. These controls do not mean that every discrepancy is fraud.

### User impact

- Users become defensive and less willing to engage with further questions.
- Normal differences in memory or wording may be perceived as evidence of dishonesty.
- Trust declines when the insurer appears to be searching for a reason not to pay.
- Disputes last longer because the user does not know which fact must be corrected or supported.

### Root cause

The purpose of verification and the difference between validation, inconsistency, suspicion, and a final fraud conclusion are not communicated clearly enough.

### Pain point statement

> Claimants need transparent and proportionate verification because unexplained fraud-related language turns a legitimate evidence check into a perceived accusation.

---

## Journey-Based Pain Point Map

| FNOL stage | User task | Main pain points | Emotional effect |
|---|---|---|---|
| **Incident occurs** | Stay safe, prevent further loss, record the scene | P1: unclear actions and evidence | Shock, confusion, fear of missing something |
| **Choose a channel** | Decide between app, website, chat, phone, broker, or specialist | P4: human path unclear; fragmented channels | Uncertainty about choosing the wrong route |
| **Describe the incident** | Explain what, when, where, cause, and damage | P5: AI misunderstanding; P6: terminology | Fear of being misinterpreted |
| **Answer conditional questions** | Provide driver, third-party, police, witness, injury, or property details | P1: unclear relevance; P6: difficult requirements | Cognitive overload |
| **Submit evidence** | Upload photos, receipts, reports, and references | P3: upload and repeated requests; P8: unexplained verification | Frustration and concern about sufficiency |
| **Claim creation and triage** | Confirm submission and understand the path | P2: no visibility; P4: poor handoff | Temporary relief followed by uncertainty |
| **Wait and follow up** | Track progress, provide missing items, coordinate next steps | P2: silence; P3: repetition; P7: unclear ownership | Anxiety, irritation, loss of trust |
| **Decision or dispute** | Understand, accept, correct, or challenge the outcome | P6: jargon; P7: vague reasoning; P8: perceived unfairness | Distrust, anger, helplessness |

## Root-Cause Themes

### 1. Narrative-to-structure gap

Customers describe an event as a story, while insurers require structured and verifiable fields. Static forms push the translation burden onto the user.

### 2. Context fragmentation

Digital channels, staff, brokers, assessors, repairers, and specialists may operate from different views of the claim. Information continuity is not guaranteed by the existence of multiple channels.

### 3. Visibility and ownership gap

Internal workflow states are not consistently converted into information users can act on: current stage, responsible party, blocker, expected timing, and next step.

### 4. Automation-boundary gap

Users do not always know what AI can do, what requires human judgement, how to request a human, or whether context will follow the transfer.

### 5. Trust and explanation gap

Evidence requests, delays, exclusions, and decisions are often presented as outcomes rather than understandable reasoning connected to facts, policy terms, and user actions.

---

## Pain Points by Persona

| Pain point | First-Time Claimant | Efficiency-Seeking Claimant | Urgent or Complex Claimant |
|---|:---:|:---:|:---:|
| P1. Immediate action and evidence uncertainty | **Primary** | High | **Primary** |
| P2. Progress and timing invisibility | Medium | **Primary** | High |
| P3. Repetition and fragmented documents | Medium | **Primary** | High |
| P4. Human escalation and context loss | High | High | **Primary** |
| P5. AI misunderstanding and control | High | High | **Primary** |
| P6. Terminology and coverage uncertainty | **Primary** | High | High |
| P7. Ownership and decision transparency | Medium | **Primary** | **Primary** |
| P8. Verification and perceived unfairness | Medium | High | **Primary** |

## Prioritised Problem Statements

### Problem Statement 1: Guided FNOL

First-time and unfamiliar claimants need situation-specific guidance because they may not know which immediate actions, evidence, and information are required to protect their claim.

### Problem Statement 2: Continuous Claim Context

Claimants and staff need one continuous claim context because repeated questions, document requests, and channel changes create rework, inconsistent records, and frustration.

### Problem Statement 3: Visible Progress and Ownership

Claimants need proactive progress, timing, and ownership information because silence forces them to chase the insurer and makes delays appear unmanaged.

### Problem Statement 4: Safe Human Escalation

Urgent and complex claimants need an accessible human path with complete handoff context because automation cannot safely resolve every situation.

### Problem Statement 5: Transparent and Accountable AI

Claimants need to confirm AI-generated information and understand its boundaries because trust depends on accuracy, control, privacy, and human accountability.

### Problem Statement 6: Explainable Verification and Decisions

Claimants need specific, plain-language explanations of evidence requests and decisions because vague technical or fraud-related language creates distrust and prolonged disputes.

## Design Implications

The pain points suggest that future concepts should be evaluated against the following requirements:

- guide users before asking for the full claim record;
- separate information required now from information that may be added later;
- adapt questions to claim type and previous answers;
- let users review and correct structured information extracted by AI;
- preserve transcripts, fields, attachments, and request history across channels;
- show claim number, completeness, status, ownership, next step, and expected timing;
- send proactive updates even when the expected timing changes;
- provide a visible human option and clear escalation triggers;
- transfer full context rather than only transferring the conversation channel;
- retain human oversight for liability, coverage, fraud, denial, and other high-impact decisions;
- explain why information is required and how decisions connect to facts, evidence, and policy terms;
- provide correction, review, complaint, and accessibility pathways.

These are evaluation criteria derived from pain points, not a commitment to a specific technical implementation.

## Research Limitations

- The survey sample was small and exploratory; percentages should not be treated as population estimates.
- The previous-claim branch was especially limited, so its percentages support persona and pain-point formation rather than prevalence claims.
- Some questions allowed multiple selections, so percentages are not expected to total 100%.
- Public reviews are self-selected individual experiences and cannot measure issue frequency.
- Official weather-event findings may not represent every routine claim type.
- Agent-to-human context loss is supported as an industry risk, but its presence in a specific insurer must be confirmed through journey testing or interviews.
- Further validation should include semi-structured interviews, usability testing, staff research, and direct testing of existing FNOL channels.

## Key Sources

- [FMA — Weather Events Claims Insights](https://www.fma.govt.nz/library/reports-and-papers/weather-events-claims-insights/)
- [FMA — Insurance companies have improved their processes but more to do in extreme events](https://www.fma.govt.nz/news/all-releases/media-releases/insurance-processes-improved-but-more-to-do-extreme-events/)
- [Reddit — State Insurance claim communication example](https://www.reddit.com/r/newzealand/comments/12i6icr/any_advice_on_how_to_get_a_reply_from_state/)
- [Trustpilot — State Insurance public reviews](https://www.trustpilot.com/review/state.co.nz?page=7)
- [Salesforce — Customer Expectations](https://www.salesforce.com/small-business/what-are-customer-expectations/)
- [Genesys — State of Customer Experience](https://www.genesys.com/resources/state-of-cx)
- [Microsoft Learn — Bot-to-human handoff](https://learn.microsoft.com/en-us/azure/bot-service/bot-service-design-pattern-handoff-human?view=azure-bot-service-4.0)

## Summary

> The most important FNOL pain is the loss of control created by unclear requirements, fragmented context, invisible progress, and uncertain human support.

Users do not simply want a faster form. They want to know what to do, provide information once, understand what is happening, correct misunderstandings, and reach a responsible human when the situation requires judgement.

