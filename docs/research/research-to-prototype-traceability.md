# Research-to-Product Traceability

## Purpose

This document connects existing evidence to pain points, user needs, product principles,
and validation boundaries. It does not define implementation status and does not replace
`SPEC/`, the API contract, or sprint commitments.

The traceability chain is:

> Evidence -> pain point -> user need -> product principle -> validation boundary

## Evidence Rules

- Survey results retain the question-specific denominators in the
  [FNOL Evidence Sheet](./fnol-evidence-sheet.md). They are exploratory, not population
  estimates.
- Public reports and process material establish context or plausible mechanisms, not
  Northwind-specific prevalence.
- Direct staff research remains limited. Employee needs are evidence-informed and require
  further validation with authorised Northwind participants.
- A product decision may respond to evidence without being directly proven by it. Such a
  decision remains labelled as a team or governance decision.
- Implementation and test status belong in current pull requests, tests, and sprint
  evidence rather than this research record.

## Claimant Traceability

| Evidence | Pain point | User need | Product principle | Validation boundary |
| --- | --- | --- | --- | --- |
| Survey S01, S03, S09 and S10; observations OBS-01 to OBS-03; [P1](./pain-point-analysis.md#p1-unclear-immediate-actions-and-evidence-requirements) | A claimant may not know how to begin, what matters now, or which process step comes next. | Start naturally without learning insurance terminology or the insurer's question order. | Accept a non-linear account, structure it internally, and ask only for information needed for safety, material understanding, or the next action. | Validate with task completion, unnecessary-question count, correction rate, and qualitative comprehension; do not infer a universal abandonment rate. |
| Survey S06 and S08; [P5](./pain-point-analysis.md#p5-ai-misunderstanding-loss-of-control-and-unclear-decision-boundaries) | AI misunderstanding and unclear authority can reduce trust. | Correct material misunderstandings and know when a person controls a decision. | Keep extracted or inferred facts proposed, request confirmation only when material, and keep high-impact authority outside the model. | Test material fact correction, unsupported-action rejection, and claimant understanding; survey concern is not a measured model-failure rate. |
| Survey S05, S10 and S11; [P3](./pain-point-analysis.md#p3-repeated-information-and-fragmented-document-requests) | Evidence requirements may be unclear, fragmented, repeated, or impossible to satisfy immediately. | Know what is needed now versus later and continue safe work while evidence is pending. | Represent evidence lifecycle independently and apply the next-action-ready principle. | Verify that real prerequisites still block the dependent action while unrelated work progresses; do not imply that every document applies to every claim. |
| Previous-claim survey responses and interview observations on repeated explanation | Returning claimants may repeat confirmed facts after a pause or channel change. | Resume the same claim context without starting again. | Preserve one authoritative Claim State, compact resume context, unresolved work, and prior commitments across sessions and handoff. | Verify no duplicate claim, no stale-session overwrite, and no unnecessary replay of the complete transcript. |
| Survey S04 and S12; [P2](./pain-point-analysis.md#p2-lack-of-progress-timing-ownership-and-next-step-visibility) and [P7](./pain-point-analysis.md#p7-unclear-ownership-delays-and-decision-explanations) | Status, owner, timing, and responsibility may be unclear after submission. | Understand what happened, who acts next, what remains open, and when to return. | Derive plain-language updates from shared claim state and preserve responsibility and next action. | Retain the original sample limits; test whether users can accurately state status and responsibility after reading an update. |
| Survey S07, S13 and S14; observations OBS-04 and OBS-05; [P4](./pain-point-analysis.md#p4-unclear-human-escalation-and-loss-of-context-during-handoff) | Urgent, stressful, inaccessible, disputed, or complex situations may require human support. | Reach a person without losing known context or being repeatedly resisted. | Provide transparent human-support and urgent paths with structured handoff context. | The need is supported, but first-request routing, staffing, priority, and service levels require product authority and operational evidence. |

## Staff and Operations Traceability

| Evidence | Pain point | User need | Product principle | Validation boundary |
| --- | --- | --- | --- | --- |
| Employee evidence W01, W02 and W06; [E1](./pain-point-analysis.md#e1-information-intensive-and-claim-specific-intake) | Staff may reconstruct a claim from narrative, fields, files, and incomplete sources. | See a concise, source-preserving claim context and the exact action requested. | Workbench detail combines confirmed facts, source references, evidence state, gaps, conflicts, handoff reason, and requested action. | Validate with claims professionals; public complexity evidence does not establish Northwind handling time. |
| W03, W07 and W08; [E3](./pain-point-analysis.md#e3-multi-party-evidence-and-handoff-coordination) | Ownership and evidence context may be lost between internal or external participants. | Know the current owner, expected output, timing, and status of each assigned task. | Coordinate approved participants through task-specific views of one shared claim context. | Multi-party involvement supports the mechanism but does not prove that every current Northwind claim loses context. |
| W04, W05 and W09; [E2](./pain-point-analysis.md#e2-high-and-event-driven-workload-pressure) | Event-driven workload makes prioritisation and referral quality important. | Receive prioritised, actionable work rather than an undifferentiated queue. | Use independent urgency, evidence, review, ownership, and next-action dimensions to drive workbench queues. | Catastrophe evidence does not establish routine Northwind volume, staffing, or exact thresholds. |
| W06, W07 and interview observations on repeated explanation | A staff decision can become a disconnected second status if it does not update shared state. | Record a source-backed decision once and communicate the permitted result to the claimant. | Store staff decisions separately from source evidence, write authorised state once, and produce a claimant-safe update. | Validate revision, source preservation, projection filtering, and staff comprehension. |
| Survey and public evidence concerning waiting, repetition, and unclear progress | Staff time and claimant time can both be spent reconstructing context or chasing information. | Use professional effort where judgement or support adds value. | Measure claimant effort, staff effort, handoff completeness, model cost, and failure rather than assuming automation always saves time. | No current evidence establishes a Northwind ROI, handling-time reduction, or target automation rate. |

## Product and Governance Decisions

The following directions are supported by the needs above but remain explicit product or
governance decisions rather than direct research findings:

| Decision | Rationale | Required validation |
| --- | --- | --- |
| The Agent keeps professional structure internal and exposes only useful customer-facing explanations. | Responds to process-comprehension and cognitive-effort pain points without turning chat into another form review. | Claimant usability tests, correction analysis, and professional review of internal records. |
| Approved knowledge retrieval uses citations while customer policy and history use structured authorised lookup. | Separates general guidance from customer-specific contractual facts and limits unsupported conclusions. | Source applicability, citation support, access, wrong-version rejection, and staff authority tests. |
| A Control Plane manages versioned model, knowledge, rule, integration, access, evaluation, and operational configuration. | The product requires governed change, reproducibility, and rollback as model and knowledge dependencies grow. | Administrator workflow, role, approval, secret, publication, rollback, and audit testing. |
| The longer-term product coordinates assessors, repairers, and other approved participants around shared claim context. | Responds to repeated context and ownership problems without making the claimant carry information between services. | Stakeholder confirmation, task-specific data minimisation, integration authority, service responsibility, and workflow testing. |

## Open Hypotheses

| Hypothesis | Why it remains open | Required validation |
| --- | --- | --- |
| A specific workbench or Control Plane layout reduces handling or configuration time. | Existing evidence supports information and governance needs, not a particular interface. | Role-specific workflow observation, usability testing, error rate, and completion time. |
| The first explicit request for a person should always transfer immediately. | Research supports access to a person but not one universal rule. | Product approval, claimant testing, accessibility review, and service-capacity evidence. |
| Specific coverage, fraud-review, urgency, routing, or configuration-approval thresholds are suitable for production. | Current thresholds are controlled development rules without Northwind production authority. | Northwind policy, operational evidence, governance review, and scenario validation. |
| Fine-tuning will outperform a well-evaluated general model with tools, RAG, and deterministic controls. | No approved training corpus or baseline comparison currently establishes the benefit. | Data rights, label quality, held-out evaluation, safety comparison, cost, and maintainability assessment. |

## Source Set and Maintenance

This record is based on:

- [FNOL Evidence Sheet](./fnol-evidence-sheet.md)
- [Pain Point Analysis](./pain-point-analysis.md)
- [User Personas](./user-personas.md)
- [FNOL As-Is Process and Reporting Fields](./fnol-as-is-process-and-reporting-fields.md)
- [Insurance Industry Interview and User Observation](./insurance-industry-interview-and-user-observation.md)
- [Current Product Specification](../../SPEC/README.md)
- [Current API Contract](../api.md)
- [Data Architecture](../data-architecture.md)

Update this document only when evidence, a product decision, or a validation boundary
changes. Current implementation status belongs in issues, pull requests, tests, and sprint
delivery records.
