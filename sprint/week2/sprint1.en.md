# Sprint 1 SPEC: Full-Path Adaptive FNOL Prototype

## 1. Document Status

- **Sprint:** Sprint 1
- **Dates:** 2026-08-10 to 2026-08-14
- **Presentation:** 2026-08-14 Prototype Presentation
- **Team capacity:** 5 people, 40 hours per person, 200 person-hours total
- **Product basis:** [`project/project_soul.md`](../../../project/project_soul.md)
- **Status:** Pending team confirmation before backlog and member tasks are finalized

## 2. Sprint Goal

> **By the end of Sprint 1, build and demonstrate a breadth-complete, depth-limited adaptive FNOL Prototype. It must start with a claimant's natural-language report, maintain a confirmable structured claim form, use AWS-provided policy, evidence, and claim-history data, and select a safe next step across fast, complex, urgent, human-requested, pending-evidence, and resumed-session paths. It must ultimately create or correctly hand off the claim, maintain internal claim state and tags and a Claim Operations Workbench, and record model and human effort.**

## 3. Prototype Definition

The Prototype must demonstrate the core path structure of the future product rather than only a happy path. Controlled rules, limited data, mock services, and simplified interfaces are allowed, but every core path must change system state and produce a verifiable result. Static slides or verbal explanations cannot replace a real state change.

## 4. Actors and System Boundary

- **Claimant:** Describes the event, answers necessary questions, uploads evidence, confirms or corrects the form, views status, resumes a session, or requests human help.
- **FNOL Agent:** Understands, extracts, clarifies, retrieves information, selects the next action, updates state, calls tools, and prepares handoffs.
- **Claims Professional / Fraud Professional:** Receives structured context requiring professional judgement and performs the requested action.
- **Claims Operations user:** Uses the system-maintained Workbench to view queues, filter claims, process tags/signals, assign work, and advance the next action.
- **AWS-backed data and tools:** Policy documents, historical claims, session/claim persistence, a mock claims system, and mock assessor booking.

## 5. Functional Requirements

### FR-01 Identity, Claim, and Session

- The system must create or identify `customer_id`, `claim_id`, and `session_id`.
- One customer may have multiple claims, and one claim may span multiple sessions.
- When a user resumes a session, the system must return to the current claim state and unresolved questions rather than starting again.

### FR-02 Conversational Form

- A claimant can describe the event in natural language.
- The Agent must write information into a structured form rather than keeping only chat text.
- Each form field must record its value, source, status, purpose, and update time.
- At request and at key confirmation, creation, and handoff points, the user must be able to view, confirm, and correct key fields.

### FR-03 Adaptive Questioning

- The Agent should ask only for information required by the current next safe action.
- Confirmed fields must not be repeated without a reason.
- Ambiguity, conflict, missing information, or low-quality evidence must trigger targeted clarification.
- The Agent must allow the user to say "I don't know", "I will provide it later", or that they cannot continue. It must not guess or give a policy-violating answer.

### FR-04 Multimodal Evidence

- The Prototype must accept at least images and PDF files.
- Extracted image or file results must be linked to evidence and the relevant form fields.
- Extracted content must be marked with its evidence source and must be confirmable or correctable by the user.

### FR-05 Policy Retrieval

- The Agent must query AWS-provided structured policy data and anonymised policy documents.
- Coverage/excess output must include supporting retrieval evidence or clearly state uncertainty.
- If a conclusion cannot be made safely, the Agent must hand off to a Claims Professional rather than fabricate certainty.

### FR-06 Fast and Complex Paths

- When information and rules are clear enough, the Agent should reduce questions and use the fast path.
- Complex, conflicting, or high-impact decisions should use a guided or professional-judgement path.
- Path selection must leave a reason code and an auditable record.

### FR-07 Urgent Path

- Clear injury, ongoing danger, or urgent assistance needs must interrupt the ordinary FNOL flow.
- The system must provide a clear safety message and create a high-priority human handoff.
- The Prototype must not provide medical diagnosis or pretend that emergency services have been contacted.

### FR-08 User Request for Human Help

- The system must identify an explicit request for a human and possible reasons for it.
- It may offer one short, transparent self-service option, but must not create a loop that prevents handoff.
- Repeated requests, accessibility needs, clear distress, or urgent circumstances must be handed off immediately.
- The exact first-request strategy must be confirmed by the team before implementation.

### FR-09 Next-Action-Ready and Evidence Status

- Evidence must support at least `received`, `incomplete`, `missing`, `pending_generation`, and `needed_later`.
- Future evidence must not automatically block a safe action that does not depend on it.
- The Agent must explain when the evidence is needed, who is responsible for providing it, and how it can be added to the same claim.

### FR-10 Persistent Memory and Token Control

- Complete messages must be stored in an external persistence layer rather than sending the entire history to the model on every turn.
- Each turn should use the current claim snapshot, unresolved questions, the most recent necessary messages, and relevant policy/history retrievals.
- The system must maintain a structured summary and demonstrate resuming a session after a simulated 8-10 day gap.
- Each turn must record input/output tokens, retrieval volume, and summary or compression events.

### FR-11 Historical Claims and Fraud Signals

- The Agent must query relevant historical claims for the current customer.
- Each signal must include supporting information and a reason code.
- A signal may enter Fraud Professional review, but must not become a fraud determination or accusation to the customer.
- Fraud review must not block claim creation without a justified reason.

### FR-12 Claim Creation, Routing, and Assessor

- When creation conditions are met, the Agent must call the mock claims system to create a claim.
- The system must return and display the claim number, route, status, and expected timeline.
- Assessor booking may be called only when controlled rules determine that it is needed.

### FR-13 Context-Preserving Handoff

- The handoff packet must contain the confirmed summary, form, evidence, sources, missing/conflicting information, handoff reason, priority, and requested human action.
- The Staff view must be able to consume this packet.
- Testing must show that a human does not need to re-collect key information already confirmed by the Prototype.

### FR-14 State and Customer Updates

- Every pause, handoff, or completion must state the current status, whether the customer must act, the next responsible party, and the expected time.
- Pending evidence and future actions must be visible in the claim state.

### FR-15 Multidimensional Claim State and Internal Tags

- The system must maintain `severity`, `coverage`, `evidence`, `fraud_signal`, `customer_support`, `urgency`, `workflow_state`, and `next_action` separately. A single mutually exclusive route must not replace these dimensions.
- One claim must support composable attributes such as `severity: standard`, `coverage: clear`, `evidence: police_report_pending`, and `next_action: create_claim` at the same time.
- Each internal tag/signal must record its code, category, visibility, source, evidence references, confidence, status, required action, assigned queue, and audit time.
- High-impact signals may start only as `proposed` or `review_required`. Staff must be able to confirm, dismiss, override, or resolve them.
- Sensitive internal signals must not be exposed directly to the claimant. The customer should receive an appropriate status and next-step explanation instead.

### FR-16 Claim Operations Workbench

- The system must maintain the Workbench from claim state and must not require staff to enter a second, separate claim record.
- The Workbench must provide at least Urgent, New/Untriaged, Ready to Progress, Awaiting Evidence, Professional Review, Ready to Create, and Created/Routed views.
- Enterprise users must be able to filter by status, tag, priority, assignee, next action, and SLA.
- Claim detail must show the form, evidence, sources, conflicts, internal attributes, handoff packet, and customer communication.
- Staff must be able to assign claims, process proposed tags/signals, perform the next action, and write the result back to claim state.
- A Workbench action must trigger an appropriate claimant status update.

## 6. Agent Decision Contract

Each turn must return at least:

```text
action
reason_code
claim_state_changes
internal_attributes
internal_tags_proposed
visibility
questions_or_message
required_tools
next_action_requirements
handoff_priority
customer_visible_next_step
```

Allowed actions are `ASK`, `CLARIFY`, `CONFIRM`, `PROCEED`, `UPDATE`, `HANDOFF`, `URGENT_HANDOFF`, and `CREATE_CLAIM`.

Authorization and rule checks for high-impact actions must run outside the model output. A model suggestion must not bypass policy or professional-judgement boundaries.

## 7. Minimum Data Contract

The Prototype must include at least:

- `customers`: User identity and permitted preferences;
- `claims`: Claim form, workflow state, route, and current next action;
- `claim_attributes`: Composable state such as severity, coverage, evidence, fraud/customer support, urgency, and next action;
- `internal_tags`: Source, evidence, visibility, status, processing queue, and audit record;
- `sessions`: Session state and structured summary;
- `messages`: Complete conversation records;
- `evidence`: Evidence, source, status, and linked fields;
- `decisions`: Action, reason code, basis, and execution result;
- `handoffs`: Human handoff packet and status;
- `staff_actions`: Assignment, confirm/dismiss/override, processing result, and claimant update;
- `claim_events`: Auditable state changes.

Do not create a separate physical table for every user. Use shared data models partitioned and related by `customer_id`, `claim_id`, and `session_id`.

## 8. Acceptance Scenarios

| ID | Scenario | Required observable result |
| --- | --- | --- |
| AT-01 | Clear minor motor accident | A small number of targeted questions, form confirmation, fast progression, and mock claim creation |
| AT-02 | Policy wording or event applicability is unclear | Show the basis and uncertainty, then hand off the context to a Claims Professional |
| AT-03 | Complex event or conflicting evidence | Record the conflict, avoid an overconfident conclusion, and request professional judgement |
| AT-04 | Clear injury or danger at the scene | Interrupt the ordinary flow, provide a safety message, and create an urgent handoff |
| AT-05 | Claimant requests a human | Apply the confirmed strategy, eventually hand off, and preserve context |
| AT-06 | Police document has not been generated | Mark `pending_generation`, advance actions that do not depend on it, and explain how it will be added later |
| AT-07 | Image contains extractable accident information | Extract proposed fields and allow the user to confirm or correct them |
| AT-08 | Simulated continuation after ten days | Restore the claim snapshot, outstanding work, and previous commitment without restarting |
| AT-09 | Historical claim creates a supported fraud signal | Send the signal with evidence to professional review without making a fraud determination |
| AT-10 | Controlled scenario requires an assessor | Create and route the claim, call the mock assessor, and show the timeline |
| AT-11 | Multiple claim-state attributes coexist | Pending evidence does not overwrite clear coverage or incorrectly block `create_claim`; attributes and next action remain traceable |
| AT-12 | Internal signal enters the Workbench | The claim enters the correct queue; staff can view evidence, confirm or override the signal, perform the action, write back the result, and update the claimant |

These are the Sprint 1 path acceptance scenarios. They do not replace the final Brief requirement for 5 motor, 3 home, and 2 contents test sets.

## 9. Non-Functional Requirements

### NFR-01 Traceability

Key fields, policy decisions, fraud signals, internal tags, staff overrides, routes, and handoffs must be traceable to their source and reason code.

### NFR-02 Cost Observability

The Prototype must record tokens, tool calls, reasons for human intervention, event/execution effort, cognitive effort, and handoff packet completeness as a baseline for later optimization.

### NFR-03 Demonstration Reliability

All acceptance scenarios must use repeatable fixtures. The core demonstration path must not depend on temporary manual data edits.

### NFR-04 Data Boundary

Do not write secrets, real personal information, or unnecessary complete histories into prompts, logs, documents, or presentation material.

### NFR-05 User Control

Customers must be able to correct the form, understand Agent uncertainty, see the next step, and access a human path.

### NFR-06 Permissions and Visibility

The Prototype must distinguish customer-visible, shared, and internal-only information. Sensitive tags/signals must be visible only to authorised enterprise users.

### NFR-07 High-Fidelity Desktop and Mobile Interface

The claimant interface must be delivered as a working HTML web experience with separately designed desktop and mobile layouts. The mobile interface must not be a scaled-down desktop layout. Both layouts must preserve the same core information, actions, and business states while adapting navigation, the claim summary, conversation area, evidence upload, and fixed input area to the available space.

Use 1440 x 900 desktop and 390 x 844 mobile viewports as the primary design baselines, and also check usability at 1280 x 800 and 360 x 800. Default, loading, empty, error, disabled, upload, urgent-handoff, and human-handoff states must have complete visual treatments. Typography, spacing, colour, icons, borders, control dimensions, and information hierarchy must follow one consistent system. Fixed-viewport screenshots must be used to identify overflow, occlusion, misalignment, and missing states. Until a Figma source file exists, "Figma-level precision" means this level of high-fidelity completion; once an approved design is available, screen-by-screen visual comparison must be added.

## 10. Effort Metrics

The Prototype must report at least:

- Question count, completion time, correction count, and repeated-question count per scenario;
- Token, retrieval, and tool-call volume per scenario;
- Handoff rate, reason, priority, and packet completeness;
- Number of human interventions, processing time, transfers, and follow-ups;
- The number of fields a human would need to ask for again after handoff, and the time required to understand the initial claim and unresolved questions;
- The number of steps from session recovery to the next valid action.

## 11. Delivery Artifacts

- A runnable claimant-facing Prototype;
- A visible and correctable structured form;
- Agent orchestration and action/state contracts;
- AWS data access, policy RAG, session/claim persistence, and mock tools;
- A system-maintained Claim Operations Workbench with queues, internal attributes/tags, handoff processing, and claimant updates;
- Acceptance fixtures, test results, and effort metrics;
- A Friday demonstration script and repeatable demonstration environment;
- The Sprint 1 multi-lane convergence diagram using an overview page and a complete dependency register: Chinese [draw.io source](sprint1-prototype-delivery-flow.zh.drawio) / [overview SVG](sprint1-prototype-delivery-flow.zh.drawio.svg) / [dependency register SVG](sprint1-prototype-dependencies.zh.drawio.svg), English [draw.io source](sprint1-prototype-delivery-flow.en.drawio) / [overview SVG](sprint1-prototype-delivery-flow.en.drawio.svg) / [dependency register SVG](sprint1-prototype-dependencies.en.drawio.svg).

## 12. Workflow Framework (Members Not Assigned Yet)

The following five workflows are continuing categories of work, not five permanent positions. Members may move between workflows based on current blockers and progress. Each individual task must still have one current owner.

### Workflow A: Product Rules and Agent Behaviour

This workflow answers "What should the system do in each situation?" It includes:

- Writing clear inputs and expected outcomes for fast, complex, urgent, human-requested, pending-evidence, and cross-session scenarios;
- Defining form fields, claim state, internal tags, next-action-ready rules, and handoff conditions;
- Defining executable Agent actions, prohibited behaviour, reason codes, and customer-visible wording boundaries;
- Defining what counts as passing for each acceptance scenario.

The main outputs are behaviour rules, scenario fixtures, acceptance conditions, and shared contracts. Frontend, Agent, data, and test work depend on these outputs so that each stream does not invent its own business logic.

### Workflow B: Claimant and Staff Experience

This workflow owns what users see and operate:

- Claimant conversation, form viewing/correction, image/PDF upload, evidence status, progress, and next step;
- The Staff Claim Operations Workbench, queues, filters, claim detail, tag/signal processing, and handoff;
- Urgent notices, human requests, error states, waiting states, and cross-session recovery;
- Showing the same claim state in a way appropriate to each user's permissions and work.

The main outputs are operable interfaces and interaction states. This workflow uses the behaviour rules from Workflow A and the data/API from Workflow D; it must not invent business judgements.

### Workflow C: Agent Runtime and Orchestration

This workflow makes the Agent follow rules rather than merely generate a reply:

- Select `ASK`, `CLARIFY`, `PROCEED`, `HANDOFF`, and other actions from the current claim state;
- Call policy, historical claim, evidence, claim-creation, and assessor tools;
- Maintain sessions, structured summaries, and the model context for each turn;
- Control tokens, retries, error handling, and rule checks for high-impact actions;
- Write execution results back to the unified claim state and expose them to the frontend and Workbench.

The main outputs are the Agent action contract, orchestration logic, tool calls, and state transitions.

### Workflow D: Data, Knowledge, and AWS Integration

This workflow answers where data comes from, where it is stored, and how other modules call it:

- Inspect AWS-provided data and mock services and build an adapter layer;
- Store customers, claims, sessions, messages, evidence, tags, handoffs, and events;
- Build data interfaces for policy retrieval/RAG, historical claims, and fraud signals;
- Connect image/PDF storage, mock claim creation, and assessor booking;
- Provide deployment, permissions, logging, and environment configuration.

The main outputs are data schemas, API/tool contracts, persistence, and the AWS cloud environment.

### Workflow E: Cross-Testing, Integration, and Delivery

This workflow does not make one person responsible for all testing. It coordinates continuous integration across all modules:

- Connect A-D outputs into an end-to-end flow and verify a runnable version every day;
- Run AT-01 to AT-12 with fixed fixtures and record actual results and defects;
- Check that Claimant, Agent, data, and Staff Workbench interpret the same claim state consistently;
- Collect token, human effort, error, latency, and handoff completeness data;
- Maintain the cloud demonstration environment, test checklist, demonstration script, and backup demonstration path.

The main outputs are a continuously runnable integrated build, test evidence, and the final Prototype. Testing remains the responsibility of each task owner; Workflow E coordinates cross-module verification and delivery.

The current multi-lane convergence baseline was drawn in draw.io with Chinese and English counterparts. The horizontal axis is Day 1 to Day 5. The six vertical delivery streams are Product Rules, Claimant Experience, Staff Workbench, Agent Orchestration, Data/AWS, and Integration, QA, and Delivery. Lanes are not tied to permanent members. The overview keeps only dependencies that can block downstream work; the complete prerequisite relationships are listed in the second-page register. See [Delivery Artifacts](#11-delivery-artifacts) for the source and SVG files. Member names and 1-4 hour leaf tasks are assigned dynamically in Kanban. All streams converge on **Prototype Delivery**.

## 13. Collaboration and Integration Gates

An integration gate is a point where the team checks whether current outputs connect and run. It is not an administrative approval step waiting for one person.

### Gate 1: Shared Language and Interfaces Available (Monday)

On Monday, the team first agrees on the shared claim state, form/data schema, Agent action contract, API/tool contract, and acceptance fixtures. After this, frontend, Agent, data, and testing work can proceed in parallel using the same fields, actions, and scenarios.

### Gate 2: Minimum End-to-End Skeleton Runs (Tuesday)

After a claimant enters natural language, the system can update the form, persist a claim, call one mock tool, and show the same state in the Claimant interface and Workbench. The features may still be simple, but data must travel through every major layer.

### Gate 3: All Core Branches Connected (Wednesday)

Fast, complex, urgent, human-requested, pending-evidence, and session-resume paths reach the correct next action. Claim state and internal tags enter the Workbench automatically, and Staff results can be written back.

### Gate 4: Prototype Scope Locked (Thursday noon)

AT-01 to AT-12, effort metrics, internal tag processing, Staff handoff, and claimant updates are connected. After this point, stop adding features and fix only defects that block the demonstration or break acceptance.

On Thursday afternoon, complete the final test pass and rehearse the demonstration. Friday is reserved for final checks and the Prototype Presentation.

### Dependency Management

"Dependency" means an input that must be available before a task can start or finish. Examples include:

- Field and state names must be agreed before frontend and backend share a claim state;
- Workbench development depends on the claim attributes, internal tags, and staff-action contract;
- Policy/history paths depend on an AWS data adapter or a replaceable fixture;
- Agent route tests depend on behaviour rules, reason codes, and expected results;
- The final demonstration depends on all core paths entering the same integrated cloud build.

Only tasks whose dependencies are satisfied may enter `Ready`. When a new dependency appears, write down what is needed, which task provides it, and which acceptance scenario it affects rather than leaving a member to wait without context.

The backlog uses four levels: Sprint Goal -> capability outcome -> verifiable work package -> 1-4 hour leaf task. Each leaf task has one current owner. A reviewer is selected dynamically according to the task's interfaces, available people, and required cross-functional perspective; there are no fixed reviewer pairs. Each member may have at most one `In progress` task at a time.

## 14. Out of Scope for Sprint 1

- Production-grade security, capacity, disaster recovery, and complete compliance implementation;
- Complete coverage of all real policy wording and abnormal data;
- A final accuracy commitment for all ten scenarios;
- Real writes to production claims or assessor systems;
- Automatic fraud determination, claim approval/denial, or medical diagnosis;
- Full lifecycle tracking after claim creation;
- Unconfirmed voice capability;
- Final technology architecture, permanent member responsibilities, and final slide-template adaptation.

## 15. Definition of Done

Sprint 1 is complete only when all of the following are true:

- AT-01 to AT-12 can be repeated and have recorded results;
- Core paths are real interactions rather than static demonstrations, and system state and tool calls change with input;
- Claimants can see and correct the form;
- The claimant interface is delivered as working HTML with high-fidelity desktop and mobile layouts and passes the required viewport screenshot checks;
- Policy, history, evidence, and session data participate in at least one path through the defined interfaces;
- Fast, professional-judgement, urgent, human-requested, pending-evidence, and resume paths can all be demonstrated end to end;
- Mock claim creation, route, claim number, next step, and timeline are visible;
- The Staff handoff packet can be consumed by the Staff view without re-collecting confirmed information;
- The Workbench is maintained from claim state, and Staff can filter, process proposed tags/signals, perform the next action, and write back the result;
- Sensitive internal signals and claimant-visible status are correctly separated;
- Token and human-effort metrics are viewable;
- No secret, real personal information, or unsupported coverage/fraud conclusion is present;
- After scope lock, the demonstration environment completes one full final test pass and rehearsal.

## 16. Known Constraints, Technical Recommendations, and Open Decisions

### Known Constraints

- The actual schemas, access methods, and availability of AWS data and mock services are not yet known. Use fixtures and an adapter matching the expected contract until the real data is available, then replace the adapter.
- The technology stack is selected by the team; the deployment target is an AWS cloud environment.
- The code repository was previously named `Northwind-FNOL-agent`, but its current remote existence must be reconfirmed. Branch protection, PR, CI/CD, and local-material migration rules are still open.
- The five members are not tied to permanent capability roles. They pull tasks according to workflow progress, and reviewers are selected dynamically.
- The multi-lane convergence diagram has a 16:9 working baseline and **Prototype Delivery** as its final node. Dependencies come from actual task inputs and outputs; only dimensions and density should be adapted to the final slide template.

### Recommended Technical Baseline (Pending Team Confirmation)

- **Frontend:** React + TypeScript + Vite, deployed to AWS Amplify Hosting;
- **Agent/API:** Python + FastAPI, with explicit claim state and action contracts. Use API Gateway + Lambda for standard APIs; evaluate Bedrock AgentCore Runtime for long-running or streaming Agent execution;
- **Model:** Amazon Bedrock. Select the specific model after data and account permissions are known;
- **Data:** DynamoDB for claim/session/state/event data and S3 for images and PDFs;
- **Policy retrieval:** Select Bedrock Knowledge Bases/OpenSearch or direct structured queries according to the AWS data format;
- **Identity and permissions:** Amazon Cognito;
- **Logs and metrics:** CloudWatch for tokens, tool calls, paths, human event/execution effort, and cognitive effort;
- **Infrastructure:** AWS CDK for repeatable cloud deployment.

This recommendation prioritises forming a cloud-hosted full-path Prototype within one week. Finalise it after the team obtains the actual AWS data, permissions, and service constraints.

### Business Rules Still to Confirm

- **First human-request strategy:** When a claimant first says "I want a human", should the system transfer immediately, or should the Agent give one sentence explaining that the claimant can transfer now or complete the current step first? Repeated requests, urgent circumstances, distress, or accessibility needs should still transfer immediately.
- **Controlled business rules:** Conditions written explicitly or configured for a stable Prototype demonstration, such as "clear injury -> urgent handoff" or "coverage cannot be confirmed from the available evidence -> professional review". These are test rules, not claims about Northwind's final production rules.
- **Fixture:** An anonymous or simulated input package for one path, including customer, policy, claim history, conversation, image/PDF status, and expected result. Fixtures let the team trigger the same path repeatedly and determine whether it passes.
- **Specific rule values:** Final trigger conditions for coverage, severity, fraud signals, assessor booking, and the first human request require AWS data and mentor feedback.
- **Draw.io layout:** The current layout uses a 16:9 canvas, Day 1-5 horizontal axis, and six delivery-stream lanes. The final slide template should change only size and density, not Gate or dependency meaning.
