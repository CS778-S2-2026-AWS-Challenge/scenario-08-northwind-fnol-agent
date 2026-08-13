# Research-to-Prototype Traceability

## Purpose

This document traces supported research findings to claimant, Agent, and workbench prototype changes. It consolidates existing evidence and implementation status without changing the underlying research, survey data, product specification, or API contract.

The traceability chain used throughout is:

> Evidence → pain point → user type → prototype change → validation boundary

This is a prioritisation and audit record. A mapped change is not evidence that the change has already been implemented or that the underlying finding represents all Northwind customers or employees.

## Evidence and Decision Rules

- Survey findings refer to the exploratory sample and retain the question-specific denominators recorded in the [FNOL Evidence Sheet](./fnol-evidence-sheet.md#41-exploratory-survey-register). They are not population estimates.
- Published and public evidence establishes process context or a supported mechanism, not Northwind-specific prevalence.
- Employee findings are evidence-informed operational needs. Direct staff research remains limited, as stated in the [employee research boundary](./fnol-evidence-sheet.md#51-research-boundary).
- A row marked **Supported** is grounded in existing evidence and is consistent with the current specification.
- A row marked **Hypothesis** remains a validation question and must not become a product requirement without further evidence or an authorised product decision.
- Implementation status is descriptive only: **Implemented**, **Partial**, or **Planned**.

## Claimant Traceability

| ID | Existing evidence | Pain point | User type | Traceable prototype change | Status | Boundary and validation |
|---|---|---|---|---|---|---|
| C01 | Survey findings S01, S03, S09 and S10; observation findings OBS-01 to OBS-03; [P1](./pain-point-analysis.md#p1-unclear-immediate-actions-and-evidence-requirements) | A claimant may not know how to begin, what information matters, or what evidence to collect. | [First-Time Claimant](./user-personas.md#persona-1-first-time-claimant) | Let the claimant begin in plain language, ask focused follow-up questions, and show the structured facts for review and correction. | **Implemented** in the versioned claimant conversation and form-confirmation path. | **Supported.** The survey and observation are exploratory; they justify guided design, not a universal abandonment or comprehension rate. |
| C02 | Survey findings S04 and S12; [P2](./pain-point-analysis.md#p2-lack-of-progress-timing-ownership-and-next-step-visibility) and [P7](./pain-point-analysis.md#p7-unclear-ownership-delays-and-decision-explanations) | Claimants may not know the current status, owner, next action, or expected timing. | First-Time Claimant; [Efficiency-Seeking Claimant](./user-personas.md#persona-2-efficiency-seeking-claimant) | Show claimant-safe status, responsible party, next step, and expected timing from the shared claim state. | **Partial.** Current claim and integration responses contain next-step and timing fields; the complete progress-update experience remains planned. | **Supported.** S04 uses `n=60` and S12 uses the previous-claim branch `n=48`; neither is a Northwind prevalence estimate. |
| C03 | Survey findings S05, S10 and S11; [P3](./pain-point-analysis.md#p3-repeated-information-and-fragmented-document-requests) | Evidence requirements can be unclear, fragmented, or repeated. | First-Time Claimant; Efficiency-Seeking Claimant | Register received, incomplete, unofficial, inconsistent, or pending evidence; show what is needed and allow later submission without restarting. | **Partial.** Evidence registration, listing, upload-target and completion APIs exist; the claimant upload interface remains planned. | **Supported.** Evidence prompts must remain claim-specific and must not imply that every listed document is required for every claim. |
| C04 | Previous-claim survey findings and interview evidence on repeated explanation; [P3](./pain-point-analysis.md#p3-repeated-information-and-fragmented-document-requests) | Returning claimants may have to repeat confirmed information after an interruption or channel change. | Efficiency-Seeking Claimant | Resume the same working claim with a bounded summary, unresolved questions, pending items, prior commitments, and confirmed facts. | **Partial.** Cross-session resume and persistence are implemented; the dedicated claimant resume entry experience remains planned. | **Supported.** Resume must use the current formal claim state and must not expose internal notes or replay the complete transcript by default. |
| C05 | Survey findings S07, S13 and S14; observation findings OBS-04 and OBS-05; [P4](./pain-point-analysis.md#p4-unclear-human-escalation-and-loss-of-context-during-handoff) | Urgent, stressful, inaccessible, disputed, or complex situations may require human support without loss of context. | [Urgent or Complex Claimant](./user-personas.md#persona-3-urgent-or-complex-claimant) | Provide a visible human-support path and transfer confirmed facts, evidence state, unresolved work, handoff reason, and requested action. | **Planned** in the support-request and handoff contracts. | **Supported need; controlled rule.** The exact first-request behaviour remains an authorised prototype rule, not a research-derived universal rule. |

## Agent Traceability

| ID | Existing evidence | Pain point | Agent change | Status | Boundary and validation |
|---|---|---|---|---|---|
| A01 | S01, S03, S09, S10 and S11; [P1](./pain-point-analysis.md#p1-unclear-immediate-actions-and-evidence-requirements) | A rigid form can ask irrelevant questions or assume knowledge the claimant does not have. | Use claim state and confirmed answers to select the next focused question; distinguish information needed now from information needed later. | **Implemented** for the current controlled claimant-intake path. | **Supported.** Required-field and route rules remain deterministic; the Agent must not invent requirements. |
| A02 | S06 and S08; [P5](./pain-point-analysis.md#p5-ai-misunderstanding-loss-of-control-and-unclear-decision-boundaries) | Claimants are concerned about AI misunderstanding facts or making decisions that should remain controlled. | Keep extracted or inferred fields proposed until confirmation; require deterministic validation or authorised staff control for high-impact actions. | **Implemented** for form confirmation, evidence proposals, message decisions, and authorised claim creation. | **Supported.** Survey concerns describe trust conditions, not observed model failure rates or legal authority. |
| A03 | S05, S10 and S11; employee evidence W01, W02 and W07 | Evidence needed later can incorrectly stop unrelated safe work if all completeness is treated as one binary state. | Represent evidence independently as received, unofficial, incomplete, pending generation, or inconsistent; progress only actions whose current prerequisites are satisfied. | **Implemented** in claim and evidence state with repeatable pending-evidence fixtures. | **Supported mechanism.** The business action attached to each item must be explicit; the system must not silently waive a real prerequisite. |
| A04 | S07, S13 and S14; [P4](./pain-point-analysis.md#p4-unclear-human-escalation-and-loss-of-context-during-handoff) | Automation cannot safely resolve every urgent, complex, disputed, or accessibility-sensitive situation. | Select `HANDOFF` or `URGENT_HANDOFF` under controlled conditions and produce a claimant-safe next step plus a complete receiving context. | **Planned.** The action contract exists; end-to-end support-request and handoff behaviour remains to be implemented. | **Supported need; rule requires approval.** Survey preference does not define priority, staffing, or service-level thresholds. |
| A05 | [P8](./pain-point-analysis.md#p8-verification-that-feels-accusatory-or-unfair) and the evidence boundaries recorded for fraud research | Unsupported or opaque verification can feel accusatory and can turn a risk indicator into an unjustified conclusion. | Treat policy, history, and fraud-related outputs as cited evidence or proposed internal signals; never present them as an automated fraud conclusion. | **Partial.** Visibility boundaries and synthetic signal fixtures exist; policy/history retrieval and staff signal decision paths remain planned. | **Supported governance boundary.** Signal thresholds and production fraud rules are not established by the current research. |

## Workbench Traceability

| ID | Existing evidence | Employee pain point | User type | Traceable workbench change | Status | Boundary and validation |
|---|---|---|---|---|---|---|
| W01 | Employee evidence W01, W02 and W06; [E1](./pain-point-analysis.md#e1-information-intensive-and-claim-specific-intake) | Staff must reconstruct a claim when narrative, fields, evidence, gaps, and sources are not presented together. | [Claims Professional](./user-personas.md#persona-4-claims-professional) | Show one claim detail projection containing confirmed facts, field sources, evidence state, gaps, conflicts, decisions, handoff context, and requested action. | **Planned.** Shared persistence models exist; the functional workbench detail view remains to be implemented. | **Supported operational need.** Public requirements establish information complexity, not measured staff effort or system usability. |
| W02 | W03, W07 and W08; [E3](./pain-point-analysis.md#e3-multi-party-evidence-and-handoff-coordination) | Internal and external participants can lose ownership, requested action, or evidence context during handoff. | Claims Professional; [Claims Operations Lead](./user-personas.md#persona-5-claims-operations-lead) | Make owner, priority, requested action, timing, evidence state, handoff reason, and action history visible from the same claim record. | **Planned.** The shared-state and handoff contracts exist; staff actions and write-back remain to be implemented. | **Supported mechanism.** Multi-party involvement does not prove that every insurer or routine claim currently loses information. |
| W03 | W04, W05 and W09; [E2](./pain-point-analysis.md#e2-high-and-event-driven-workload-pressure) | Event-driven volume and scarce specialist capacity increase the need for visible prioritisation and complete referrals. | Claims Operations Lead | Provide queue views for urgent, new or untriaged, awaiting-evidence, professional-review, and ready-to-progress claims, with ownership and service timing. | **Planned** in the workbench list contract. | **Evidence-informed.** Catastrophe evidence supports surge capability but must not be treated as routine Northwind volume or staffing data. |
| W04 | W06, W07 and interview evidence on repeated explanation; [E3](./pain-point-analysis.md#e3-multi-party-evidence-and-handoff-coordination) | Staff decisions can become a second disconnected status record if they do not update the claimant-visible claim state. | Claims Professional; Claims Operations Lead | Record actor, reason, outcome and resulting revision for staff actions; write the appropriate status and next step back to the shared claim while filtering internal details. | **Planned.** Synthetic shared-state tests demonstrate the boundary; the functional staff-action route remains to be implemented. | **Supported design direction.** Direct measurement of employee handling time, frustration, or workbench usability remains unavailable. |

## Explicit Hypotheses and Open Decisions

The following items are not promoted to requirements by the current evidence:

| Hypothesis ID | Hypothesis or open decision | Why it remains open | Required validation |
|---|---|---|---|
| H01 | A specific workbench layout, queue taxonomy, or dashboard will reduce staff handling time. | Current employee evidence supports information and coordination needs but does not measure target-interface usability or handling-time improvement. | Claims-professional and operations-lead interviews, workflow observation, usability testing, and queue analytics. |
| H02 | The first explicit request for a person should always transfer immediately rather than offering one transparent choice to finish the current step. | Research supports access to a human, but it does not establish one universal first-request rule. | Product approval, claimant testing, accessibility review, and service-capacity assessment. |
| H03 | Specific coverage, fraud-review, urgency, or assessor thresholds are suitable for production. | Current rules are controlled prototype decisions and the research does not establish Northwind policy authority or production thresholds. | Northwind policy authority, operational data, governance review, and scenario validation. |

## Coverage and Ownership Summary

| Surface | Supported direction | Current boundary |
|---|---|---|
| Claimant | Guided intake, correctable facts, evidence status, resume, visible progress, and accessible human support | Core conversation and form path is implemented; evidence UI, resume entry, progress updates, and human-support journeys remain incomplete. |
| Agent | Focused questions, proposed rather than silently confirmed facts, independent evidence state, and deterministic high-impact boundaries | Core message, form, evidence, and claim-creation guards are implemented; complete handoff, policy/history, and signal-review paths remain incomplete. |
| Workbench | Shared claim projection, evidence and provenance, queue visibility, traceable staff actions, and claimant-safe write-back | Contracts and shared persistence foundations exist; the functional workbench and staff-action API remain incomplete. |

## Source Set and Maintenance

This traceability record is derived only from existing project material:

- [FNOL Evidence Sheet](./fnol-evidence-sheet.md)
- [Pain Point Analysis](./pain-point-analysis.md)
- [User Personas](./user-personas.md)
- [FNOL As-Is Process and Reporting Fields](./fnol-as-is-process-and-reporting-fields.md)
- [Insurance Industry Interview and User Observation](./insurance-industry-interview-and-user-observation.md)
- [Current product specification](../../SPEC/README.md)
- [Normative API contract](../api.md)

Future updates should add or revise a row only when the underlying evidence, product decision, implementation status, or limitation changes. Weak or conflicting evidence must remain visibly labelled rather than being converted into an unsupported requirement.
