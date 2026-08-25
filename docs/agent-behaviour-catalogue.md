# FNOL Agent Behaviour Catalogue

## Status and Use

This catalogue is the bounded behaviour deliverable for issue #233. It defines the target
behaviour contract that the route dispatcher and later Runtime work must implement. It does
not claim that every target action or provider is already implemented. Current transport
schemas remain in `docs/api.md`; target Runtime objects and delivery levels remain in
`docs/agent-runtime-target.md`.

Each behaviour is described through the same fields so another contributor can review the
boundary without inferring rules from a model prompt or a code path:

- **FNOL problem** - the claimant or staff problem this behaviour solves;
- **Trigger / intent** - the natural-language or explicit signal that selects it;
- **Input context** - the Claim State, WorkItems, evidence, identity, and permissions it may read;
- **Output** - the claimant, staff, and Runtime-facing result;
- **Target actions** - namespaced proposals or controls in the target Runtime;
- **Permitted actions** - the bounded effects the Agent or server may request;
- **Prohibited actions** - effects that must be rejected;
- **Claim State effect** - the authoritative revision and authority boundary;
- **Failure behaviour** - the safe result when understanding, tools, or providers fail;
- **Visibility** - role-specific projections;
- **Proof** - the repeatable fixture, contract check, scenario, or demo path;
- **Delivery level** - `Challenge/MVP target` or `Post-MVP target`.

The catalogue uses one primary route per input. A route may produce several proposals in one
turn, but every material state effect still passes one Claim State revision and authority
boundary.

## Route Precedence

When more than one signal is present, the dispatcher evaluates routes in this order:

1. `urgent_interruption` for explicit injury, continuing danger, or an approved immediate safety signal;
2. `human_support` for a repeated, distressed, accessibility-related, or explicit human request;
3. `resume` when the claimant is returning to an existing session or Claim;
4. `explicit_command` for a recognised command with a declared target and authority;
5. `status_query` when the claimant asks for progress without new claim facts;
6. `pending_evidence` when the message supplies or asks about outstanding evidence;
7. `policy_or_history_lookup` when the purpose is a bounded evidence query;
8. `evidence_assistance` when an image or document is being supplied or explained;
9. `multi_intent_intake` when one message contains several ordinary FNOL needs;
10. `ordinary_intake` for a clear single-purpose FNOL account;
11. `staff_agent_assistance` when the actor is staff and the request is within Claim scope;
12. `claim_creation` when the claimant or staff requests a validated creation step;
13. `unknown_or_unsafe_intent` when no declared route is safe or applicable.

Urgent and human-support rules are not delayed by ordinary form collection. `claim_creation`
is selected only after the current Claim State and authority checks show that creation is a
permitted next action; it is not a keyword shortcut.

## Behaviour Entries

### ordinary_intake

- **FNOL problem:** A straightforward claimant should not be forced through an insurer's field order or asked to repeat a clear account.
- **Trigger / intent:** A credible loss description with one dominant purpose and no higher-precedence urgent, human, resume, command, or lookup signal.
- **Input context:** Current Claim State, current-action fields, unresolved WorkItems, recent claimant message, channel, locale, and claimant scope.
- **Output:** Claimant receives acknowledgement and the smallest useful next question or next step; staff receives nothing unless a handoff or review is required; Runtime returns a bounded plan and limitations.
- **Target actions:** `conversation.acknowledge`, `conversation.ask`, `claim.propose_update`, `runtime.continue` or `runtime.wait_for_user`.
- **Permitted actions:** Extract explicit facts as proposals, preserve confirmed facts, ask for a required-now field, and record a later evidence commitment.
- **Prohibited actions:** Inventing facts, confirming an inference, exposing internal signals, declaring coverage or fraud, or creating a claim without authority.
- **Claim State effect:** Proposed fields remain `proposed`; a validated claimant confirmation or correction advances one revision; conversational text alone does not rewrite Claim State.
- **Failure behaviour:** If the model or route classifier fails, preserve the current Claim revision and ask a bounded clarification or offer human support.
- **Visibility:** Claimant sees safe acknowledgement, question, and next step; staff sees the shared Claim projection; internal diagnostics remain restricted.
- **Proof:** Repeatable clear-claim trajectory with no repeated confirmed-fact question and one inspectable proposed/confirmed field transition.
- **Delivery level:** `Challenge/MVP target`.

### multi_intent_intake

- **FNOL problem:** Claimants commonly combine incident facts, injury or danger information, evidence status, and a support request in one message; sequential questioning wastes turns.
- **Trigger / intent:** One input contains two or more recognised FNOL intents that can be handled without contradicting safety or authority rules.
- **Input context:** Same claimant context as `ordinary_intake`, plus the route candidates, active content branches, safety signals, support preference, and current WorkItems.
- **Output:** Claimant receives one coherent acknowledgement and only the unresolved question that matters for the next safe action; Runtime returns multiple bounded proposals and one primary route; staff receives a complete handoff context only if required.
- **Target actions:** `conversation.acknowledge`, multiple `claim.propose_update` actions, `human.request_handoff` when requested, and one `runtime.continue`, `runtime.wait_for_user`, or `runtime.interrupt` directive.
- **Permitted actions:** Record each explicit fact separately, identify conflicts, preserve source and confidence, and select one primary route while retaining other proposals.
- **Prohibited actions:** Collapsing distinct intents into one opaque action, silently prioritising a lower-safety intent, asking for facts already supplied, or executing several material mutations without validation.
- **Claim State effect:** Each accepted field or handoff effect is validated against the same current revision; rejected proposals do not create partial competing state.
- **Failure behaviour:** Partial understanding may preserve valid proposals only if the server can validate them independently; otherwise keep Claim State unchanged and ask one focused clarification.
- **Visibility:** Claimant sees a concise combined response; staff sees source-linked proposals and unresolved work; internal route candidates remain restricted unless policy allows them.
- **Proof:** A synthetic message containing a motor incident, no injury, and a human request produces several namespaced proposals, one primary route, no repeated question, and no conflicting write.
- **Delivery level:** `Challenge/MVP target`.

### explicit_command

- **FNOL problem:** Explicit requests such as “show my status” or “connect me to a person” must be predictable without exposing hidden developer-agent commands.
- **Trigger / intent:** A recognised command or clearly expressed task that matches a published command definition and the actor's scope.
- **Input context:** Actor identity, role, Claim scope, command registry version, current Claim State, relevant WorkItems, and required authority.
- **Output:** Claimant or staff receives the command result and next step; Runtime returns a declared command proposal or a bounded rejection.
- **Target actions:** `conversation.acknowledge`, a registered `claim.*`, `human.*`, `external.*`, or `runtime.*` action, and an explicit result status.
- **Permitted actions:** Dispatch only to a published command, validate inputs and revision, and request the authority required by that command.
- **Prohibited actions:** Treating arbitrary text after a slash or @ marker as authority, inventing commands, bypassing confirmation, or executing an unregistered tool.
- **Claim State effect:** Read-only commands do not mutate state; mutations require a typed command, current revision, idempotency where needed, and deterministic or staff authority.
- **Failure behaviour:** Unknown, malformed, or unauthorised commands return a safe explanation and do not mutate Claim State.
- **Visibility:** The actor sees the bounded command result; claimant projections never expose internal command names or diagnostics; staff-only details remain role-scoped.
- **Proof:** Route fixtures cover a declared status command, an undeclared command, malformed arguments, and an unauthorised mutation.
- **Delivery level:** `Challenge/MVP target`.

### human_support

- **FNOL problem:** A claimant who asks for a person should not be trapped in a question loop or lose context during handoff.
- **Trigger / intent:** Explicit human request, repeated request, distress, accessibility need, or a support preference that requires staff involvement and is not superseded by urgent safety handling.
- **Input context:** Claimant message, support history, current Claim State, unresolved WorkItems, handoff queue capability, and claimant-safe communication rules.
- **Output:** Claimant receives a bounded handoff acknowledgement and responsibility/next step; staff receives a source-preserving handoff packet; Runtime returns handoff status and any dispatch limitation.
- **Target actions:** `conversation.acknowledge`, `human.request_handoff`, `runtime.pause_for_review` or `runtime.wait_for_external`.
- **Permitted actions:** Create or update a handoff, preserve the conversation and unresolved work, and continue only safe non-blocked work.
- **Prohibited actions:** Repeatedly resisting the request, exposing internal risk signals, promising a staff contact time not known, or allowing the Agent to accept a staff handoff on behalf of staff.
- **Claim State effect:** Handoff responsibility and WorkItems are recorded through the shared Claim revision; confirmed incident facts remain unchanged.
- **Failure behaviour:** If dispatch is unavailable, retain the handoff and tell the claimant the bounded limitation; never discard the request or pretend staff accepted it.
- **Visibility:** Claimant sees support status and safe next step; staff sees the full packet and internal reasons permitted by role; internal diagnostics stay restricted.
- **Proof:** Human-request fixture proves one handoff, preserved context, claimant-safe projection, and retryable dispatch failure without lost progress.
- **Delivery level:** `Challenge/MVP target`.

### urgent_interruption

- **FNOL problem:** Injury or continuing danger must interrupt ordinary intake immediately instead of waiting for a complete form.
- **Trigger / intent:** Explicit injury, continuing danger, or another approved immediate safety signal.
- **Input context:** Latest claimant text, current safety attributes, Claim State, channel, location only when already authorised, and urgent-handoff capability.
- **Output:** Claimant receives concise bounded safety guidance and urgent handoff status; staff receives priority, reason, and context; Runtime returns an interrupt directive.
- **Target actions:** `conversation.acknowledge`, `human.urgent_handoff`, `runtime.interrupt`.
- **Permitted actions:** Stop ordinary intake, record the approved urgency reason, create an urgent handoff, and preserve already confirmed facts.
- **Prohibited actions:** Diagnosing injury, claiming emergency services were contacted, inferring urgency from a negative safety statement, or continuing ordinary questions before the urgent path is handled.
- **Claim State effect:** Urgency and handoff status change only through approved deterministic authority and one revision; no coverage or liability decision is created.
- **Failure behaviour:** If the queue or provider fails, preserve the urgent state and provide bounded guidance without claiming completion.
- **Visibility:** Claimant sees safe guidance and handoff status; staff sees urgent reason and context; internal signals remain staff-only.
- **Proof:** Urgent injury and continuing-danger fixtures interrupt intake; negative safety wording remains ordinary; queue failure preserves the urgent record.
- **Delivery level:** `Challenge/MVP target`.

### status_query

- **FNOL problem:** Claimants and staff need a reliable current status without receiving a stale session summary or internal workflow code.
- **Trigger / intent:** A request for current progress, responsibility, outstanding work, or next step without a new material fact.
- **Input context:** Authoritative Claim State, lifecycle projection, WorkItems, handoff status, claimant/staff visibility, and current revision.
- **Output:** Claimant receives a safe status and next step; staff receives the operational projection and ownership; Runtime returns a read-only result.
- **Target actions:** `conversation.answer_status`, `claim.read`, `runtime.continue`.
- **Permitted actions:** Read the latest authorised projection and identify pending work or responsible party.
- **Prohibited actions:** Reading stale private session state, exposing internal risk or provider detail, changing status to satisfy the question, or implying an external completion that is unknown.
- **Claim State effect:** None; a status query must not advance the Claim revision.
- **Failure behaviour:** If the current state cannot be read, return a bounded unavailable response and do not substitute a stale snapshot.
- **Visibility:** Claimant sees claimant-safe status; staff sees role-appropriate operational detail; internal diagnostics remain restricted.
- **Proof:** Status fixture compares current Claim State with a stale session snapshot and proves the current state wins without a write.
- **Delivery level:** `Challenge/MVP target`.

### resume

- **FNOL problem:** A returning claimant should continue from confirmed facts and outstanding work instead of restarting the interview.
- **Trigger / intent:** Session resume, explicit “continue where I left off”, or a detected active Claim with resumable work.
- **Input context:** Latest Claim revision, session summary, confirmed facts, unresolved WorkItems, prior commitments, evidence lifecycle, and claimant scope.
- **Output:** Claimant receives a concise resume summary and next safe step; staff sees restored responsibility and unresolved work; Runtime returns a resume result.
- **Target actions:** `claim.read`, `conversation.summarise_resume`, `runtime.continue` or `runtime.wait_for_user`.
- **Permitted actions:** Reload current Claim State, restore unresolved work, and ask only the next focused question.
- **Prohibited actions:** Overwriting newer Claim State with an old session snapshot, requesting confirmed facts again, or treating an interruption as an adverse customer signal.
- **Claim State effect:** Normally read-only; a new claimant answer creates a new revision after ordinary validation.
- **Failure behaviour:** If the session summary is stale or unavailable, reload Claim State and explain only the safe limitation.
- **Visibility:** Claimant sees confirmed facts and their next step; staff sees full authorised resume context; internal summaries are not exposed wholesale.
- **Proof:** Resume fixture rejects stale snapshot state, restores confirmed facts and pending police evidence, and avoids repeated questions.
- **Delivery level:** `Challenge/MVP target`.

### pending_evidence

- **FNOL problem:** Missing, unofficial, incomplete, or not-yet-generated evidence should be tracked without blocking unrelated safe progress.
- **Trigger / intent:** Claimant reports missing evidence, asks about an outstanding item, uploads an item, or a service records a future evidence commitment.
- **Input context:** Evidence metadata and lifecycle, WorkItems, current action dependencies, Claim State, source references, and storage/processing capability.
- **Output:** Claimant receives what is pending and what can continue; staff receives evidence state, source, and blocked action; Runtime returns a work-item or evidence result.
- **Target actions:** `claim.record_evidence`, `claim.create_work_item`, `conversation.explain_next_step`, `runtime.continue` or `runtime.wait_for_external`.
- **Permitted actions:** Record evidence state and provenance, create a bounded WorkItem, process accepted uploads, and continue actions that do not depend on the missing item.
- **Prohibited actions:** Treating pending evidence as proof, blocking all claim progress, silently replacing an occupied field, or claiming an external document exists.
- **Claim State effect:** Evidence metadata and WorkItems update through their own validated records linked to the current Claim revision; material facts remain proposed until accepted.
- **Failure behaviour:** Storage or processing failure preserves the evidence commitment and returns a retryable or bounded unavailable result.
- **Visibility:** Claimant sees safe evidence status and responsibility; staff sees lifecycle, provenance, and blocked action; provider details remain restricted.
- **Proof:** Pending police-report fixture allows controlled claim progress while retaining a later-action WorkItem and its source state.
- **Delivery level:** `Challenge/MVP target`.

### policy_or_history_lookup

- **FNOL problem:** Staff and claimants need evidence-grounded answers without treating generic document retrieval or a provider outage as a coverage decision.
- **Trigger / intent:** A bounded question about policy wording, policy facts, or relevant claim history.
- **Input context:** Claim scope, authorised purpose, policy/history reference, effective time, role, visibility, and retrieval capability.
- **Output:** Claimant receives only an approved safe explanation when permitted; staff receives facts, citations, uncertainty, and limitations; Runtime returns evidence status.
- **Target actions:** `external.policy_lookup` or `external.claim_history_lookup`, `conversation.explain_evidence`, `runtime.continue` or `runtime.pause_for_review`.
- **Permitted actions:** Query an authorised structured record or filtered knowledge source, preserve source/version/time, and create a professional-review WorkItem for ambiguity.
- **Prohibited actions:** Returning another customer's record, treating RAG text as authority, declaring fraud or coverage, or widening purpose through free text.
- **Claim State effect:** Persist retrieval evidence and limitations; do not directly mutate coverage, fraud, liability, or approval state.
- **Failure behaviour:** Unavailable or ambiguous retrieval returns an explicit limitation and preserves Claim State; it may route to professional review.
- **Visibility:** Claimant sees only permitted facts and citations; staff sees source-linked evidence and uncertainty; raw provider payloads remain restricted.
- **Proof:** Policy/history fixtures cover evidence found, no evidence, ambiguous, wrong-purpose, and unavailable results.
- **Delivery level:** `Challenge/MVP target`.

### evidence_assistance

- **FNOL problem:** Images or documents can reduce repetitive description work, but extracted facts must remain traceable and claimant-confirmed where material.
- **Trigger / intent:** Claimant or staff supplies an image/document or asks the Agent to explain an evidence requirement.
- **Input context:** Evidence metadata, protected object reference, processing state, current Claim form, field registry, source visibility, and extraction capability.
- **Output:** Claimant sees upload/processing status and a safe proposed fact for confirmation; staff sees source-linked extraction and conflicts; Runtime returns an evidence proposal or failure.
- **Target actions:** `external.evidence_extract`, `claim.propose_update`, `conversation.request_confirmation`, `runtime.wait_for_external` or `runtime.continue`.
- **Permitted actions:** Register accepted evidence, request typed extraction, create proposed fields with source references, and ask for confirmation.
- **Prohibited actions:** Treating extraction as confirmation, overwriting an occupied field, exposing protected object details, or inferring a coverage/fraud result from an image.
- **Claim State effect:** Evidence lifecycle and proposed facts update through the evidence boundary; claimant confirmation or staff authority creates the next revision.
- **Failure behaviour:** Upload, extraction, or storage failure leaves existing Claim State unchanged and preserves a retryable evidence status.
- **Visibility:** Claimant sees safe status and proposed fact; staff sees source/provenance and conflicts; object references and diagnostics remain restricted.
- **Proof:** Image-assisted fixture proves proposed status, source reference, claimant confirmation/correction, and occupied-field protection.
- **Delivery level:** `Challenge/MVP target`.

### claim_creation

- **FNOL problem:** A claimant needs progress when the current safe action is ready, but claim creation is a high-impact external side effect that must not be triggered by persuasive model prose.
- **Trigger / intent:** A validated next-action request after required-now facts, confirmation, evidence rules, and authority checks pass.
- **Input context:** Current Claim revision, confirmed form, evidence refs, pending WorkItems, authorised decision, idempotency key, route, and claims-service capability.
- **Output:** Claimant receives created, pending, or failed status and next step; staff receives external result and limitations; Runtime returns a typed external outcome.
- **Target actions:** `claim.prepare_creation`, `external.claim_create`, `runtime.wait_for_external`, `runtime.continue`, or `runtime.fail_safely`.
- **Permitted actions:** Prepare and submit an idempotent provider-neutral creation request after deterministic or staff authority.
- **Prohibited actions:** Creating from an unconfirmed proposal, treating pending evidence as silently resolved, retrying an unknown outcome without reconciliation, or exposing provider payloads.
- **Claim State effect:** Record an authorised decision and external operation status; preserve the working Claim and revision regardless of provider result.
- **Failure behaviour:** Timeout becomes an unknown external outcome requiring status/reconciliation; explicit failure is retryable only when the contract permits it.
- **Visibility:** Claimant sees safe creation status and responsibility; staff sees decision, provider state, and reconciliation work; raw credentials and payloads remain restricted.
- **Proof:** Controlled creation journey covers confirmed form, pending later evidence, idempotent replay, provider failure, and unknown outcome handling.
- **Delivery level:** `Challenge/MVP target`.

### staff_agent_assistance

- **FNOL problem:** Staff need source-linked summaries, comparison, and next-step help without rereading every message or delegating professional judgement to a chatbot.
- **Trigger / intent:** A staff member invokes `@Agent` in an authorised Claim scope using natural language.
- **Input context:** Staff identity, role, task, Claim State, evidence, WorkItems, handoff context, permitted retrieval/tool capabilities, and visibility rules.
- **Output:** Staff receives a source-linked answer, proposal, comparison, or draft; claimant receives nothing until staff explicitly sends an authorised update; Runtime returns advisory status.
- **Target actions:** `conversation.summarise`, `conversation.explain_evidence`, `human.propose_next_step`, `external.retrieve`, or `runtime.wait_for_staff`.
- **Permitted actions:** Read authorised context, retrieve evidence, explain uncertainty, propose next steps, and draft communication.
- **Prohibited actions:** Autonomous Claim mutation, claimant send, disclosure, high-impact decision, unrestricted cross-claim search, or treating read permission as execution authority.
- **Claim State effect:** Advisory assistance is read-only; staff acceptance creates a separate authorised action and revision.
- **Failure behaviour:** Bounded unavailable or incomplete suggestions preserve the staff workflow and expose the limitation without inventing certainty.
- **Visibility:** Staff sees sources, limitations, and advisory label; claimant sees only an explicitly authorised staff update; internal diagnostics remain restricted.
- **Proof:** Staff fixture proves source-linked suggestion, accept/ignore distinction, no automatic claimant message, and role-scope enforcement.
- **Delivery level:** `Challenge/MVP target`.

### unknown_or_unsafe_intent

- **FNOL problem:** Ambiguous, malicious, or unsupported input must not cause a hidden action, schema invention, or unsafe confidence.
- **Trigger / intent:** No declared route matches safely, the input attempts prompt injection, the requested action exceeds scope, or model output cannot be validated.
- **Input context:** Raw claimant/staff input, current Claim State, actor scope, route registry, policy, capability set, and validation result.
- **Output:** Claimant or staff receives a bounded clarification or limitation; Runtime returns a rejected proposal or safe failure with no hidden side effect.
- **Target actions:** `conversation.clarify`, `runtime.stop_without_mutation`, or `runtime.fail_safely`.
- **Permitted actions:** Ask one focused clarification, explain an unavailable capability, preserve context, and offer an authorised human path.
- **Prohibited actions:** Executing inferred commands, obeying retrieved or user-supplied prompt overrides, parsing free text into a side effect, or exposing hidden policy/instructions.
- **Claim State effect:** None unless a separately validated safe input is later provided; no partial mutation from a rejected turn.
- **Failure behaviour:** Reject malformed or unsafe output, record bounded diagnostics, preserve Claim State, and return a retryable or non-retryable safe response according to the failure layer.
- **Visibility:** Actor sees actionable safe wording; staff may see the bounded reason and evidence; hidden prompts, credentials, and internal diagnostics remain restricted.
- **Proof:** Unknown-command, prompt-injection, malformed-output, unsupported-capability, and provider-failure tests prove no hidden action and no Claim revision.
- **Delivery level:** `Challenge/MVP target`.

## Catalogue Invariants

- Claim State is the only authoritative current claim truth.
- A primary route may emit multiple proposals, but execution validates each effect against one current Claim revision and authority boundary.
- Model output, retrieved evidence, and extracted facts are proposals or evidence, not authority.
- Claimant, staff, and internal projections are separate; internal signals never enter claimant output.
- A provider, tool, storage, or external-service failure preserves accepted progress and reports an explicit limitation.
- The eight-action compatibility transport is not a target action definition in this catalogue.
- Every target action and route has an owner, contract, failure case, visibility rule, and repeatable proof path before promotion to implemented status.
