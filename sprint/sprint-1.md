# Sprint 1: Full-path Adaptive FNOL Prototype

## Status

- **Period:** 10-14 August 2026
- **Capacity:** five people, 40 hours each, 200 person-hours total
- **Delivery:** working prototype presentation on Friday
- **Document role:** time-bound Sprint 1 commitment; the initial product specification remains authoritative for long-lived product requirements

## Sprint Goal

Build a full-path, depth-controlled FNOL prototype that lets a claimant describe an incident, inspect and correct a structured claim form, provide evidence, resume later, and either create a mock claim or transfer to staff with context. The same claim state must drive an internal workbench, and all core paths must be repeatable and observable.

In parallel, establish an evidence-based view of claimant pain points so later product decisions can be traced to public evidence and research rather than team assumptions.

## Prototype Standard

"Full-path" means every agreed behaviour branch can be demonstrated end to end. It does not mean production-grade breadth. Controlled rules, anonymous fixtures, AWS-provided data, and mock integrations are allowed, but a user action must cause a real and inspectable state transition rather than trigger a static presentation.

## Actors and Boundary

- **Claimant:** reports the incident, confirms or corrects facts, provides evidence, receives status, and requests support.
- **Agent:** structures input, retrieves evidence, proposes the next action, and operates only within explicit authority.
- **Claims professional:** handles support, ambiguity, review signals, and high-impact decisions through the workbench.
- **Mock or configured services:** policy, history, evidence, claim creation, and assessor interfaces.

The sprint ends at claim creation and routing with a clear next step. Full downstream claim handling, production claim decisions, and autonomous fraud conclusions are out of scope.

## Workstream 1: User Evidence and Requirements

### Purpose

Test whether the team's problem framing reflects real reporting experiences before treating it as settled product truth.

### Activities

- Define the research question, participant boundaries, consent, privacy, and evidence classifications.
- Collect public evidence from industry reports, insurer claim processes, public reviews, and complaint cases.
- Categorise evidence across before reporting, during reporting, and after reporting.
- Prepare and distribute the claimant pain-point survey with informed consent and respondent-profile questions.
- Use structured input from an insurance-industry contact to check question clarity and overlooked operational concerns.
- After sufficient responses arrive, derive pain points, needs, current-state journey, user stories, a story map, personas, and design opportunities in that order.
- Maintain a visible chain from source evidence to pain point, user type, and design opportunity.

### Evidence Thresholds

- A finding must cite at least one traceable source or participant response.
- A repeated pattern should have support from at least three independent participant responses or two independent public source types.
- A single strong complaint or professional observation may define a risk or open question, but not prevalence.
- Northwind-specific claims require Northwind evidence; adjacent industry evidence can support only a hypothesis or mechanism.
- Conflicting evidence remains visible and is not averaged into false certainty.

### Research Deliverables

- research scope, consent, privacy, participant profile, and evidence rules;
- claimant survey and distribution record;
- evidence sheet grouped by journey stage;
- pain-point and need synthesis after the evidence threshold is met;
- current-state journey, user stories, story map, personas, and opportunity map;
- research readout that states evidence strength, limitations, and product implications.

The sprint may establish templates and evidence structure before survey results arrive. It must not invent final pain points, personas, or prioritisation from missing data.

## Workstream 2: Shared Product Contracts

The team must establish a common language before parallel modules diverge:

- claim and session identifiers;
- structured form fields with value, source, status, purpose, and update time;
- independent claim-state dimensions and next action;
- agent actions, reason codes, required tools, and authority checks;
- internal tag and review-signal lifecycle;
- API requests, responses, errors, and versioning;
- repeatable scenario inputs and expected state changes;
- customer-visible, shared, and internal-only information boundaries.

Contracts are versioned team inputs. Frontend, backend, agent, data, and tests must not create incompatible private versions of the same concept.

## Workstream 3: Claimant Experience

The claimant interface must provide:

- start and resume flows;
- multi-turn free-text conversation;
- a visible and correctable structured claim form;
- image and PDF upload with processing and evidence state;
- current progress, pending work, responsible party, and expected timing;
- fast, guided, professional-review, urgent, human-request, pending-evidence, and resume experiences;
- claim creation result with number, route, next step, and timeline;
- working desktop and mobile layouts with complete loading, empty, disabled, error, upload, and transfer states.

The primary layout checks are 1440 x 900 and 390 x 844, with additional checks at 1280 x 800 and 360 x 800.

## Workstream 4: Agent Behaviour and Orchestration

The agent must explicitly select `ASK`, `CLARIFY`, `CONFIRM`, `PROCEED`, `UPDATE`, `HANDOFF`, `URGENT_HANDOFF`, or `CREATE_CLAIM`.

It must:

- update the form and claim state from natural language and evidence;
- avoid repeating confirmed questions;
- retrieve relevant policy and history evidence;
- progress when information is sufficient for the next safe action;
- keep high-impact authorisation outside unconstrained model output;
- preserve context across sessions and handoff;
- compact model context and record token, tool, retry, latency, and error information;
- use bounded behaviour when an external dependency is unavailable.

## Workstream 5: Backend, Data, and Integration

The backend must provide a versioned API and shared persistent state for customers, claims, attributes, sessions, messages, evidence, decisions, tags, handoffs, staff actions, and events.

It must expose replaceable adapters for:

- policy retrieval;
- claim-history retrieval;
- image and document evidence;
- claim creation and routing;
- conditional assessor action.

Actual AWS schemas and service access are unknown at sprint start. The implementation must use contract-compatible fixtures and adapters so confirmed AWS services can replace mocks without rewriting product behaviour.

## Workstream 6: Staff Workbench and Handoff

The workbench must be generated from shared claim state and support:

- Urgent, New/Untriaged, Ready to Progress, Awaiting Evidence, Professional Review, Ready to Create, and Created/Routed views;
- filtering and assignment;
- full claim, evidence, source, conflict, communication, and handoff context;
- confirmation, dismissal, override, and resolution of proposed tags or review signals;
- completion of staff actions with write-back to the claim;
- an appropriate claimant-visible update after staff action.

The handoff packet must give staff enough confirmed context to avoid recollecting known facts.

## Acceptance Scenarios

| ID | Scenario | Observable result |
|---|---|---|
| AT-01 | Clear minor motor incident | Focused intake, confirmation, fast progress, and mock claim creation |
| AT-02 | Ambiguous policy applicability | Evidence and uncertainty shown; context sent for professional review |
| AT-03 | Complex event or conflicting evidence | Conflict recorded and high-impact judgement transferred |
| AT-04 | Explicit injury or continuing danger | Normal intake interrupted and urgent handoff created |
| AT-05 | Claimant requests a person | Agreed first-request rule applied and context preserved |
| AT-06 | Police document not yet generated | Evidence remains pending while unrelated safe actions progress |
| AT-07 | Image contains incident facts | Facts proposed and claimant can confirm or correct them |
| AT-08 | Claimant returns after ten days | State and commitments resume without restarting |
| AT-09 | History supports a review signal | Evidence-linked signal enters professional review without allegation |
| AT-10 | Assessor required by controlled rule | Claim created and routed; mock assessor action and timing shown |
| AT-11 | Multiple state dimensions coexist | One pending item does not overwrite other state or block the wrong action |
| AT-12 | Internal signal reaches workbench | Staff decide the signal, act, write back, and update the claimant |

These scenarios are the prototype path set, not a substitute for the challenge's final five motor, three home, and two contents evaluation cases.

## Integration Gates

### Gate 1: Shared contracts usable by all modules - Monday

Form fields, claim state, agent actions, API/tool interfaces, visibility rules, and scenario expectations are agreed well enough for independent implementation to use the same language.

### Gate 2: Minimum end-to-end state flow - Tuesday

A claimant message updates the form, persists a claim, calls one mock tool, and appears as the same state in both customer and staff interfaces.

### Gate 3: Core branches connected - Wednesday

Fast, complex, urgent, human-request, pending-evidence, and resume behaviours reach the correct action. Staff actions can update shared state and the claimant view.

### Gate 4: Feature scope fixed - Thursday midday

All acceptance paths and required measurements are present. The remaining time is used for defects, integration verification, accessibility, responsive checks, and presentation reliability rather than new features.

Thursday afternoon is reserved for the full scenario run and presentation rehearsal. Friday is limited to final verification and delivery.

## Effort Measurements

The prototype records, per scenario where applicable:

- completion time, questions, corrections, and repeated questions;
- model tokens, retrievals, tool calls, latency, failures, and retries;
- handoff rate, reason, priority, and packet completeness;
- staff actions, transfer count, follow-up count, and simulated handling time;
- facts staff would need to ask again and time to understand the initial report;
- steps from session resume to the next useful action.

## Delivery Contents

- runnable claimant and staff experiences;
- shared form, claim state, and agent decision contracts;
- API, persistence, retrieval, session, evidence, and mock-service integrations;
- repeatable acceptance inputs, results, and effort measurements;
- user-research evidence and synthesis appropriate to the amount of data collected;
- a multi-lane delivery diagram, presentation script, repeatable demonstration environment, and fallback recording or screenshots.

## Definition of Done

Sprint 1 is complete only when:

- all acceptance scenarios can be repeated and their results recorded;
- core paths change system state and do not rely on static screen changes;
- the claimant can inspect and correct the form;
- customer and staff interfaces show role-appropriate views of the same state;
- policy, history, evidence, and session interfaces participate in relevant paths;
- claim creation returns a visible number or state, route, next step, and timing;
- handoff preserves confirmed context and internal signals remain internal;
- token and human-effort measurements can be inspected;
- responsive, accessibility, error, and transfer states are verified;
- no secret, real personal information, unsupported coverage decision, or fraud conclusion is present;
- research outputs distinguish evidence, findings, hypotheses, decisions, and open questions;
- the integrated demonstration passes one complete rehearsal after feature scope is fixed.

## Out of Scope

- production-scale security, compliance, capacity, disaster recovery, and availability;
- every real policy wording or data exception;
- a production claim approval, rejection, fraud determination, or medical assessment;
- the complete post-creation claim lifecycle;
- unconfirmed voice capability;
- final production architecture or fixed role assignments;
- claims that user research has not yet supported.

## Open Decisions

- actual AWS data schemas, access methods, mock-service availability, and deployment constraints;
- production triggers for coverage review, severity, fraud review, assessor action, and urgent transfer;
- immediate transfer versus one transparent choice on a first human request;
- voice scope;
- final model and retrieval services;
- baseline and target values for claimant effort, human effort, and agent cost.
