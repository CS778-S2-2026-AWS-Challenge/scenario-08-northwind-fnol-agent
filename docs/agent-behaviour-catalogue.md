# FNOL Agent Behaviour Catalogue

## Status and Use

This catalogue is the bounded behaviour deliverable for issue #233. It defines the target
behaviour contract that the route dispatcher and later Runtime work must implement. It does
not claim that every target action or provider is already implemented. Current transport
schemas remain in `docs/api.md`. Target Runtime objects and delivery levels are defined by
the coordinated design in PR #314 and `docs/agent-runtime-target.md`. This catalogue is
reviewed first as the behavioural baseline; PR #314 merges first so that its target contract
exists before this dependent catalogue merges. The two PRs are intentionally sequenced, and
this catalogue does not duplicate the target object definitions.

Each behaviour is described through the same fields so another contributor can review the
boundary without inferring rules from a model prompt or a code path:

- **FNOL problem** - the claimant or staff problem this behaviour solves;
- **Trigger / intent** - the natural-language or explicit signal that selects it;
- **Input context** - the Claim State, WorkItems, evidence, identity, and permissions it may read;
- **Output** - the claimant, staff, and Runtime-facing result;
- **Target actions** - namespaced proposals or controls in the target Runtime;
- **Authority** - the actor or deterministic boundary that may authorise an effect;
- **Tool allow-list** - the declared tools available to the behaviour, including `none`;
- **Permitted actions** - the bounded effects the Agent or server may request;
- **Prohibited actions** - effects that must be rejected;
- **Claim State effect** - the authoritative revision and authority boundary;
- **Failure behaviour** - the safe result when understanding, tools, or providers fail;
- **Visibility** - role-specific projections;
- **Claimant-visible response** - the response rule for claimant-facing output;
- **Handoff condition** - the exact condition for no handoff, optional handoff, or required handoff;
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
5. `correction_confirmation` for a claimant correction or material confirmation response;
6. `status_query` when the claimant asks for progress without new claim facts;
7. `pending_evidence` when the message supplies or asks about outstanding evidence;
8. `policy_or_history_lookup` when the purpose is a bounded evidence query;
9. `evidence_assistance` when an image or document is being supplied or explained;
10. `professional_review_handoff` when evidence or authority requires professional judgement;
11. `multi_intent_intake` when one message contains several ordinary FNOL needs;
12. `ordinary_intake` for a clear single-purpose FNOL account;
13. `staff_agent_assistance` when the actor is staff and the request is within Claim scope;
14. `claim_creation` when the claimant or staff requests a validated creation step;
15. `unknown_or_unsafe_intent` when no declared route is safe or applicable.

Urgent and human-support rules are not delayed by ordinary form collection. `claim_creation`
is selected only after the current Claim State and authority checks show that creation is a
permitted next action; it is not a keyword shortcut.

## Behaviour Entries

### ordinary_intake

- **FNOL problem:** A straightforward claimant should not be forced through an insurer's field order or asked to repeat a clear account.
- **Trigger / intent:** A credible loss description with one dominant purpose and no higher-precedence urgent, human, resume, command, or lookup signal.
- **Input context:** Current Claim State, current-action fields, unresolved WorkItems, recent claimant message, channel, locale, and claimant scope.
- **Output:** Claimant receives acknowledgement and the smallest useful next question or next step; staff receives nothing unless a handoff or review is required; Runtime returns a bounded plan and limitations.
- **Target actions:** `conversation.acknowledge`, `conversation.ask`, `claim.propose_fact_patch`, `runtime.continue`, or `runtime.wait_for_user`.
- **Authority:** The model may propose facts and wording; claimant confirmation and deterministic field/revision validation authorise Claim State changes.
- **Tool allow-list:** `none` for ordinary intake unless a separately selected behaviour exposes a declared tool.
- **Permitted actions:** Extract explicit facts as proposals, preserve confirmed facts, ask for a required-now field, and record a later evidence commitment.
- **Prohibited actions:** Inventing facts, confirming an inference, exposing internal signals, declaring coverage or fraud, or creating a claim without authority.
- **Claim State effect:** Proposed fields remain `proposed`; a validated claimant confirmation or correction advances one revision; conversational text alone does not rewrite Claim State.
- **Failure behaviour:** If the model or route classifier fails, preserve the current Claim revision and ask a bounded clarification or offer human support.
- **Visibility:** Claimant sees safe acknowledgement, question, and next step; staff sees the shared Claim projection; internal diagnostics remain restricted.
- **Claimant-visible response:** Acknowledge the account, preserve stated facts, and ask only the smallest required-now question or state the next safe step.
- **Handoff condition:** No handoff by default; select a declared support, urgent, or professional-review behaviour when its condition is present.
- **Proof:** Repeatable clear-claim trajectory with no repeated confirmed-fact question and one inspectable proposed/confirmed field transition.
- **Delivery level:** `Challenge/MVP target`.

### multi_intent_intake

- **FNOL problem:** Claimants commonly combine incident facts, injury or danger information, evidence status, and a support request in one message; sequential questioning wastes turns.
- **Trigger / intent:** One input contains two or more recognised FNOL intents that can be handled without contradicting safety or authority rules.
- **Input context:** Same claimant context as `ordinary_intake`, plus the route candidates, active content branches, safety signals, support preference, and current WorkItems.
- **Output:** Claimant receives one coherent acknowledgement and only the unresolved question that matters for the next safe action; Runtime returns multiple bounded proposals and one primary route; staff receives a complete handoff context only if required.
- **Target actions:** `conversation.acknowledge`, multiple `claim.propose_fact_patch` actions, `human.create_handoff` when authorised, and one `runtime.continue`, `runtime.wait_for_user`, or `runtime.interrupt_urgent` directive.
- **Authority:** Each proposal is independently validated; one primary runtime directive controls the turn and higher-precedence safety/support authority wins.
- **Tool allow-list:** Union of the tools declared by the selected bounded behaviours; no undeclared tool becomes available because several intents coexist.
- **Permitted actions:** Record each explicit fact separately, identify conflicts, preserve source and confidence, and select one primary route while retaining other proposals.
- **Prohibited actions:** Collapsing distinct intents into one opaque action, silently prioritising a lower-safety intent, asking for facts already supplied, or executing several material mutations without validation.
- **Claim State effect:** Each accepted field or handoff effect is validated against the same current revision; rejected proposals do not create partial competing state.
- **Failure behaviour:** Partial understanding may preserve valid proposals only if the server can validate them independently; otherwise keep Claim State unchanged and ask one focused clarification.
- **Visibility:** Claimant sees a concise combined response; staff sees source-linked proposals and unresolved work; internal route candidates remain restricted unless policy allows them.
- **Claimant-visible response:** Address every material claimant need coherently, state what was understood, and ask at most the focused question needed for the primary route.
- **Handoff condition:** Required only when the selected urgent, configured human-support, or professional-review behaviour requires it.
- **Proof:** A synthetic message containing a motor incident, no injury, and a human request produces several namespaced proposals, one primary route, no repeated question, and no conflicting write.
- **Delivery level:** `Challenge/MVP target`.

### explicit_command

- **FNOL problem:** Explicit requests such as “show my status” or “connect me to a person” must be predictable without exposing hidden developer-agent commands.
- **Trigger / intent:** A recognised command or clearly expressed task that matches a published command definition and the actor's scope.
- **Input context:** Actor identity, role, Claim scope, command registry version, current Claim State, relevant WorkItems, and required authority.
- **Output:** Claimant or staff receives the command result and next step; Runtime returns a declared command proposal or a bounded rejection.
- **Target actions:** `conversation.acknowledge`, a registered `claim.*`, `human.*`, `external.*`, or `runtime.*` action, and an explicit result status.
- **Authority:** The command registry defines required authority; command syntax or natural-language phrasing never grants authority.
- **Tool allow-list:** Only tools named by the matched published command and permitted for the actor, Claim scope, and purpose.
- **Permitted actions:** Dispatch only to a published command, validate inputs and revision, and request the authority required by that command.
- **Prohibited actions:** Treating arbitrary text after a slash or @ marker as authority, inventing commands, bypassing confirmation, or executing an unregistered tool.
- **Claim State effect:** Read-only commands do not mutate state; mutations require a typed command, current revision, idempotency where needed, and deterministic or staff authority.
- **Failure behaviour:** Unknown, malformed, or unauthorised commands return a safe explanation and do not mutate Claim State.
- **Visibility:** The actor sees the bounded command result; claimant projections never expose internal command names or diagnostics; staff-only details remain role-scoped.
- **Claimant-visible response:** State the supported result or explain that the command is unknown, malformed, or unauthorised without exposing internals.
- **Handoff condition:** Only when the matched command or configured support rule requires handoff; unknown commands do not create handoffs automatically.
- **Proof:** Route fixtures cover a declared status command, an undeclared command, malformed arguments, and an unauthorised mutation.
- **Delivery level:** `Challenge/MVP target`.

### human_support

- **FNOL problem:** A claimant who asks for a person should not be trapped in a question loop or lose context during handoff.
- **Trigger / intent:** Explicit human request, repeated request, distress, accessibility need, or a support preference that requires staff involvement and is not superseded by urgent safety handling.
- **Input context:** Claimant message, support history, current Claim State, unresolved WorkItems, handoff queue capability, and claimant-safe communication rules.
- **Output:** Claimant receives a bounded handoff acknowledgement and responsibility/next step; staff receives a source-preserving handoff packet; Runtime returns handoff status and any dispatch limitation.
- **Target actions:** `conversation.acknowledge`, `human.offer_support` or `human.create_handoff`, and `runtime.continue` or `runtime.pause_for_review`.
- **Authority:** A versioned configured rule controls the first ordinary request; repeated requests, urgency, distress, and accessibility needs deterministically require immediate handoff.
- **Tool allow-list:** `handoff.create` and `handoff.status` when permitted; no staff-acceptance or high-impact decision tool.
- **Permitted actions:** Create or update a handoff, preserve the conversation and unresolved work, and continue only safe non-blocked work.
- **Prohibited actions:** Repeatedly resisting the request, exposing internal risk signals, promising a staff contact time not known, or allowing the Agent to accept a staff handoff on behalf of staff.
- **Claim State effect:** Handoff responsibility and WorkItems are recorded through the shared Claim revision; confirmed incident facts remain unchanged.
- **Failure behaviour:** If dispatch is unavailable, retain the handoff and tell the claimant the bounded limitation; never discard the request or pretend staff accepted it.
- **Visibility:** Claimant sees support status and safe next step; staff sees the full packet and internal reasons permitted by role; internal diagnostics stay restricted.
- **Claimant-visible response:** Acknowledge the support need and truthfully state the configured next step, responsibility, and any known limitation without promising acceptance or timing.
- **Handoff condition:** First ordinary request follows the configured, versioned rule; repeated requests, urgency, distress, or accessibility needs require immediate handoff.
- **Proof:** Human-request fixture proves one handoff, preserved context, claimant-safe projection, and retryable dispatch failure without lost progress.
- **Delivery level:** `Challenge/MVP target`.

### correction_confirmation

- **FNOL problem:** A claimant must be able to correct a material misunderstanding or confirm a proposed fact without restarting intake or allowing the Agent to preserve the wrong version.
- **Trigger / intent:** The claimant explicitly corrects an existing fact, confirms or rejects a proposed material interpretation, or answers a focused confirmation request.
- **Input context:** Current Claim revision, the referenced confirmed or proposed field, its source and status, the claimant message, unresolved conflicts, and claimant scope.
- **Output:** Claimant receives the corrected or confirmed interpretation and its next effect; staff sees the revised source-preserving fact and any remaining conflict; Runtime returns a bounded update proposal and continuation directive.
- **Target actions:** `claim.correct_fact`, `conversation.acknowledge`, `conversation.confirm_material`, and `runtime.continue` or `runtime.wait_for_user`.
- **Authority:** The claimant authorises corrections to claimant-controlled facts; deterministic field, conflict, and revision validation authorises the resulting Claim State revision.
- **Tool allow-list:** `claim.read` and `claim.apply_patch` for the referenced current revision only.
- **Permitted actions:** Preserve the original source, record the claimant correction or confirmation, resolve only the referenced conflict, and recalculate the next safe action from the new revision.
- **Prohibited actions:** Silently overwriting an unrelated field, treating an ambiguous reply as confirmation, deleting provenance, rewriting staff-controlled decisions, or preserving an obsolete interpretation in claimant output.
- **Claim State effect:** One validated correction or confirmation advances one Claim revision with actor, source, prior value, new value, and outcome; rejected or ambiguous input creates no partial mutation.
- **Failure behaviour:** A stale revision, ambiguous reference, or validation failure preserves current Claim State and asks one focused clarification rather than guessing the intended field.
- **Visibility:** Claimant sees the corrected or confirmed fact and next step; staff sees provenance and conflict history; internal validation diagnostics remain restricted.
- **Claimant-visible response:** Acknowledge exactly what changed or was confirmed, identify any material consequence, and ask only for an unresolved ambiguity.
- **Handoff condition:** Required only when the correction conflicts with protected evidence, a staff-controlled decision, or a high-impact judgement that the claimant cannot authorise.
- **Proof:** Correction fixture proves source-preserving replacement, stale-revision rejection, ambiguous-reference clarification, and recalculation from the accepted revision.
- **Delivery level:** `Challenge/MVP target`.

### urgent_interruption

- **FNOL problem:** Injury or continuing danger must interrupt ordinary intake immediately instead of waiting for a complete form.
- **Trigger / intent:** Explicit injury, continuing danger, or another approved immediate safety signal.
- **Input context:** Latest claimant text, current safety attributes, Claim State, channel, location only when already authorised, and urgent-handoff capability.
- **Output:** Claimant receives concise bounded safety guidance and urgent handoff status; staff receives priority, reason, and context; Runtime returns an interrupt directive.
- **Target actions:** `conversation.acknowledge`, `human.create_handoff`, and `runtime.interrupt_urgent`.
- **Authority:** Only an approved deterministic urgent trigger may authorise the urgent state and handoff; model recognition alone is a proposal.
- **Tool allow-list:** `handoff.create` and `handoff.status`; no diagnosis, emergency-service, coverage, or liability tool.
- **Permitted actions:** Stop ordinary intake, record the approved urgency reason, create an urgent handoff, and preserve already confirmed facts.
- **Prohibited actions:** Diagnosing injury, claiming emergency services were contacted, inferring urgency from a negative safety statement, or continuing ordinary questions before the urgent path is handled.
- **Claim State effect:** Urgency and handoff status change only through approved deterministic authority and one revision; no coverage or liability decision is created.
- **Failure behaviour:** If the queue or provider fails, preserve the urgent state and provide bounded guidance without claiming completion.
- **Visibility:** Claimant sees safe guidance and handoff status; staff sees urgent reason and context; internal signals remain staff-only.
- **Claimant-visible response:** Give concise bounded safety guidance and accurate urgent-handoff status before ordinary intake resumes.
- **Handoff condition:** Required immediately for an approved explicit injury, continuing danger, or other approved immediate safety signal.
- **Proof:** Urgent injury and continuing-danger fixtures interrupt intake; negative safety wording remains ordinary; queue failure preserves the urgent record.
- **Delivery level:** `Challenge/MVP target`.

### status_query

- **FNOL problem:** Claimants and staff need a reliable current status without receiving a stale session summary or internal workflow code.
- **Trigger / intent:** A request for current progress, responsibility, outstanding work, or next step without a new material fact.
- **Input context:** Authoritative Claim State, lifecycle projection, WorkItems, handoff status, claimant/staff visibility, and current revision.
- **Output:** Claimant receives a safe status and next step; staff receives the operational projection and ownership; Runtime returns a read-only result.
- **Target actions:** `conversation.answer` and `runtime.continue`.
- **Authority:** Authorised current-state read access supplies the answer; neither model wording nor the query itself may change state.
- **Tool allow-list:** `claim.read` only for the actor's authorised Claim scope.
- **Permitted actions:** Read the latest authorised projection and identify pending work or responsible party.
- **Prohibited actions:** Reading stale private session state, exposing internal risk or provider detail, changing status to satisfy the question, or implying an external completion that is unknown.
- **Claim State effect:** None; a status query must not advance the Claim revision.
- **Failure behaviour:** If the current state cannot be read, return a bounded unavailable response and do not substitute a stale snapshot.
- **Visibility:** Claimant sees claimant-safe status; staff sees role-appropriate operational detail; internal diagnostics remain restricted.
- **Claimant-visible response:** State current progress, outstanding work, responsible party, and only timing that the authoritative projection actually knows.
- **Handoff condition:** None unless current authoritative state already requires support or professional review.
- **Proof:** Status fixture compares current Claim State with a stale session snapshot and proves the current state wins without a write.
- **Delivery level:** `Challenge/MVP target`.

### resume

- **FNOL problem:** A returning claimant should continue from confirmed facts and outstanding work instead of restarting the interview.
- **Trigger / intent:** Session resume, explicit “continue where I left off”, or a detected active Claim with resumable work.
- **Input context:** Latest Claim revision, session summary, confirmed facts, unresolved WorkItems, prior commitments, evidence lifecycle, and claimant scope.
- **Output:** Claimant receives a concise resume summary and next safe step; staff sees restored responsibility and unresolved work; Runtime returns a resume result.
- **Target actions:** `claim.resume_draft`, `conversation.summarise`, `runtime.continue`, or `runtime.wait_for_user`.
- **Authority:** Current Claim State overrides session summaries; ordinary validation authorises any new claimant answer.
- **Tool allow-list:** `claim.read` and an authorised session-summary read; no historical write or cross-Claim search.
- **Permitted actions:** Reload current Claim State, restore unresolved work, and ask only the next focused question.
- **Prohibited actions:** Overwriting newer Claim State with an old session snapshot, requesting confirmed facts again, or treating an interruption as an adverse customer signal.
- **Claim State effect:** Normally read-only; a new claimant answer creates a new revision after ordinary validation.
- **Failure behaviour:** If the session summary is stale or unavailable, reload Claim State and explain only the safe limitation.
- **Visibility:** Claimant sees confirmed facts and their next step; staff sees full authorised resume context; internal summaries are not exposed wholesale.
- **Claimant-visible response:** Summarise confirmed facts, unresolved work, and the next safe step without replaying the full history or repeating answered questions.
- **Handoff condition:** None by default; retain or create a handoff only when the restored authoritative state requires one.
- **Proof:** Resume fixture rejects stale snapshot state, restores confirmed facts and pending police evidence, and avoids repeated questions.
- **Delivery level:** `Challenge/MVP target`.

### pending_evidence

- **FNOL problem:** Missing, unofficial, incomplete, or not-yet-generated evidence should be tracked without blocking unrelated safe progress.
- **Trigger / intent:** Claimant reports missing evidence, asks about an outstanding item, uploads an item, or a service records a future evidence commitment.
- **Input context:** Evidence metadata and lifecycle, WorkItems, current action dependencies, Claim State, source references, and storage/processing capability.
- **Output:** Claimant receives what is pending and what can continue; staff receives evidence state, source, and blocked action; Runtime returns a work-item or evidence result.
- **Target actions:** `claim.set_evidence_state`, `claim.upsert_work_item`, `conversation.explain`, `runtime.continue`, or `runtime.wait_for_external`.
- **Authority:** Evidence metadata rules and Claim revision validation authorise records; extracted or promised evidence never authorises a material fact by itself.
- **Tool allow-list:** `evidence.register`, `evidence.verify`, and declared upload or processing tools for the actor and evidence state.
- **Permitted actions:** Record evidence state and provenance, create a bounded WorkItem, process accepted uploads, and continue actions that do not depend on the missing item.
- **Prohibited actions:** Treating pending evidence as proof, blocking all claim progress, silently replacing an occupied field, or claiming an external document exists.
- **Claim State effect:** Evidence metadata and WorkItems update through their own validated records linked to the current Claim revision; material facts remain proposed until accepted.
- **Failure behaviour:** Storage or processing failure preserves the evidence commitment and returns a retryable or bounded unavailable result.
- **Visibility:** Claimant sees safe evidence status and responsibility; staff sees lifecycle, provenance, and blocked action; provider details remain restricted.
- **Claimant-visible response:** Distinguish what is pending, what can continue, who is responsible, and any known timing without treating absence as failure.
- **Handoff condition:** Required only when evidence conflict, professional judgement, or an unresolved service failure cannot progress safely.
- **Proof:** Pending police-report fixture allows controlled claim progress while retaining a later-action WorkItem and its source state.
- **Delivery level:** `Challenge/MVP target`.

### policy_or_history_lookup

- **FNOL problem:** Staff and claimants need evidence-grounded answers without treating generic document retrieval or a provider outage as a coverage decision.
- **Trigger / intent:** A bounded question about policy wording, policy facts, or relevant claim history.
- **Input context:** Claim scope, authorised purpose, policy/history reference, effective time, role, visibility, and retrieval capability.
- **Output:** Claimant receives only an approved safe explanation when permitted; staff receives facts, citations, uncertainty, and limitations; Runtime returns evidence status.
- **Target actions:** `conversation.explain`, `runtime.continue`, or `runtime.pause_for_review`.
- **Authority:** Purpose-limited access authorises retrieval only; deterministic rules or authorised staff retain authority over coverage, fraud, liability, and high-impact conclusions.
- **Tool allow-list:** `policy.lookup`, `claim_history.lookup`, and filtered `knowledge.search` only when explicitly permitted for the actor and purpose.
- **Permitted actions:** Query an authorised structured record or filtered knowledge source, preserve source/version/time, and create a professional-review WorkItem for ambiguity.
- **Prohibited actions:** Returning another customer's record, treating RAG text as authority, declaring fraud or coverage, or widening purpose through free text.
- **Claim State effect:** Persist retrieval evidence and limitations; do not directly mutate coverage, fraud, liability, or approval state.
- **Failure behaviour:** Unavailable or ambiguous retrieval returns an explicit limitation and preserves Claim State; it may route to professional review.
- **Visibility:** Claimant sees only permitted facts and citations; staff sees source-linked evidence and uncertainty; raw provider payloads remain restricted.
- **Claimant-visible response:** Present only permitted facts with citations and material limitations; never convert retrieved evidence into an insurer decision.
- **Handoff condition:** Required when ambiguity, conflict, or a high-impact interpretation needs professional judgement; provider unavailability alone reports a limitation unless policy requires review.
- **Proof:** Policy/history fixtures cover evidence found, no evidence, ambiguous, wrong-purpose, and unavailable results.
- **Delivery level:** `Challenge/MVP target`.

### evidence_assistance

- **FNOL problem:** Images or documents can reduce repetitive description work, but extracted facts must remain traceable and claimant-confirmed where material.
- **Trigger / intent:** Claimant or staff supplies an image/document or asks the Agent to explain an evidence requirement.
- **Input context:** Evidence metadata, protected object reference, processing state, current Claim form, field registry, source visibility, and extraction capability.
- **Output:** Claimant sees upload/processing status and a safe proposed fact for confirmation; staff sees source-linked extraction and conflicts; Runtime returns an evidence proposal or failure.
- **Target actions:** `claim.register_evidence`, `claim.propose_fact_patch`, `conversation.confirm_material`, `runtime.wait_for_external`, or `runtime.continue`.
- **Authority:** The evidence service may propose extracted facts; claimant confirmation, occupied-field protection, and deterministic validation authorise any Claim update.
- **Tool allow-list:** `evidence.register`, `evidence.extract`, `evidence.verify`, and declared upload tools scoped to the accepted evidence item.
- **Permitted actions:** Register accepted evidence, request typed extraction, create proposed fields with source references, and ask for confirmation.
- **Prohibited actions:** Treating extraction as confirmation, overwriting an occupied field, exposing protected object details, or inferring a coverage/fraud result from an image.
- **Claim State effect:** Evidence lifecycle and proposed facts update through the evidence boundary; claimant confirmation or staff authority creates the next revision.
- **Failure behaviour:** Upload, extraction, or storage failure leaves existing Claim State unchanged and preserves a retryable evidence status.
- **Visibility:** Claimant sees safe status and proposed fact; staff sees source/provenance and conflicts; object references and diagnostics remain restricted.
- **Claimant-visible response:** Explain processing status and clearly label extracted content as proposed until the claimant confirms or corrects it.
- **Handoff condition:** Required for unresolved material conflicts or professional interpretation; ordinary extraction and confirmation remain self-service.
- **Proof:** Image-assisted fixture proves proposed status, source reference, claimant confirmation/correction, and occupied-field protection.
- **Delivery level:** `Challenge/MVP target`.

### professional_review_handoff

- **FNOL problem:** Material ambiguity, conflicting evidence, or a high-impact interpretation must reach a claims professional with enough source context to decide without recollecting the claim.
- **Trigger / intent:** A validated rule identifies a coverage, liability, review-signal, evidence-conflict, or other approved judgement that exceeds automated authority.
- **Input context:** Current Claim revision, material facts and provenance, evidence and conflicts, relevant cited retrievals, prior communication, pending WorkItems, authority result, staff queue capability, and visibility rules.
- **Output:** Claimant receives an accurate explanation of the review and next responsibility; staff receives a structured source-preserving handoff packet and requested action; Runtime returns a paused-for-review result.
- **Target actions:** `human.request_professional_review`, `conversation.explain`, and `runtime.pause_for_review`.
- **Authority:** Deterministic review rules or authorised staff may require professional review; the model may identify candidate ambiguity but cannot create a high-impact conclusion.
- **Tool allow-list:** `handoff.create`, `handoff.status`, `claim.read`, and read-only source retrieval needed to assemble the authorised packet.
- **Permitted actions:** Record the review reason without alleging an outcome, assemble the standard handoff packet, assign responsibility through the configured queue, and preserve unrelated safe progress.
- **Prohibited actions:** Declaring coverage, fraud, liability, approval, or rejection; exposing internal signals to the claimant; omitting conflicting sources; or blocking unrelated work solely because review is pending.
- **Claim State effect:** Create a source-linked professional-review WorkItem and handoff status through one validated revision; no high-impact decision exists until authorised staff records it separately.
- **Failure behaviour:** Queue or retrieval failure preserves Claim State and the review requirement, records the unavailable dependency, and reports truthful pending responsibility without claiming dispatch.
- **Visibility:** Claimant sees the safe review status and next responsibility; staff sees the complete permitted packet, evidence, conflict, and reason; restricted signals and diagnostics remain internal.
- **Claimant-visible response:** Explain that professional review is needed, what can continue, who is responsible next, and only timing known from the authoritative state.
- **Handoff condition:** Required when a validated material ambiguity, conflict, review signal, or high-impact decision exceeds automated authority.
- **Proof:** Professional-review fixtures prove source-complete packet creation, no claimant allegation, independent safe progress, staff decision write-back, and dispatch-failure preservation.
- **Delivery level:** `Challenge/MVP target`.

### claim_creation

- **FNOL problem:** A claimant needs progress when the current safe action is ready, but claim creation is a high-impact external side effect that must not be triggered by persuasive model prose.
- **Trigger / intent:** A validated next-action request after required-now facts, confirmation, evidence rules, and authority checks pass.
- **Input context:** Current Claim revision, confirmed form, evidence refs, pending WorkItems, authorised decision, idempotency key, route, and claims-service capability.
- **Output:** Claimant receives created, pending, or failed status and next step; staff receives external result and limitations; Runtime returns a typed external outcome.
- **Target actions:** `claim.prepare_creation`, `claim.create`, `runtime.wait_for_external`, `runtime.continue`, or `runtime.fail_safe`.
- **Authority:** Deterministic prerequisites plus the documented claimant, rule, or staff authority must authorise creation before the external call.
- **Tool allow-list:** `claim.prepare_creation`, `claim.create`, and provider-neutral status or reconciliation tools using one idempotency reference.
- **Permitted actions:** Prepare and submit an idempotent provider-neutral creation request after deterministic or staff authority.
- **Prohibited actions:** Creating from an unconfirmed proposal, treating pending evidence as silently resolved, retrying an unknown outcome without reconciliation, or exposing provider payloads.
- **Claim State effect:** Record an authorised decision and external operation status; preserve the working Claim and revision regardless of provider result.
- **Failure behaviour:** Timeout becomes an unknown external outcome requiring status/reconciliation; explicit failure is retryable only when the contract permits it.
- **Visibility:** Claimant sees safe creation status and responsibility; staff sees decision, provider state, and reconciliation work; raw credentials and payloads remain restricted.
- **Claimant-visible response:** State created, pending, failed, or unknown status accurately and identify the next action and responsibility without inventing a claim number.
- **Handoff condition:** Required when authority or professional review remains outstanding, or when an unknown external outcome cannot be reconciled automatically.
- **Proof:** Controlled creation journey covers confirmed form, pending later evidence, idempotent replay, provider failure, and unknown outcome handling.
- **Delivery level:** `Challenge/MVP target`.

### staff_agent_assistance

- **FNOL problem:** Staff need source-linked summaries, comparison, and next-step help without rereading every message or delegating professional judgement to a chatbot.
- **Trigger / intent:** A staff member invokes `@Agent` in an authorised Claim scope using natural language.
- **Input context:** Staff identity, role, task, Claim State, evidence, WorkItems, handoff context, permitted retrieval/tool capabilities, and visibility rules.
- **Output:** Staff receives a source-linked answer, proposal, comparison, or draft; claimant receives nothing until staff explicitly sends an authorised update; Runtime returns advisory status.
- **Target actions:** `conversation.summarise`, `conversation.explain`, `human.request_approval`, `runtime.continue`, or `runtime.wait_for_user`.
- **Authority:** Staff role and task scope authorise reads; explicit staff approval separately authorises sends, mutations, disclosures, or high-impact actions.
- **Tool allow-list:** `claim.read`, `knowledge.search`, `policy.lookup`, `claim_history.lookup`, and `communication.draft` when declared for the staff role; no autonomous mutation or send tool.
- **Permitted actions:** Read authorised context, retrieve evidence, explain uncertainty, propose next steps, and draft communication.
- **Prohibited actions:** Autonomous Claim mutation, claimant send, disclosure, high-impact decision, unrestricted cross-claim search, or treating read permission as execution authority.
- **Claim State effect:** Advisory assistance is read-only; staff acceptance creates a separate authorised action and revision.
- **Failure behaviour:** Bounded unavailable or incomplete suggestions preserve the staff workflow and expose the limitation without inventing certainty.
- **Visibility:** Staff sees sources, limitations, and advisory label; claimant sees only an explicitly authorised staff update; internal diagnostics remain restricted.
- **Claimant-visible response:** None until staff explicitly authorises a bounded update; any sent text must match the persisted claimant-safe outcome.
- **Handoff condition:** No new handoff merely because staff invokes `@Agent`; retain the existing work item or create a specific handoff only through authorised staff workflow.
- **Proof:** Staff fixture proves source-linked suggestion, accept/ignore distinction, no automatic claimant message, and role-scope enforcement.
- **Delivery level:** `Challenge/MVP target`.

### unknown_or_unsafe_intent

- **FNOL problem:** Ambiguous, malicious, or unsupported input must not cause a hidden action, schema invention, or unsafe confidence.
- **Trigger / intent:** No declared route matches safely, the input attempts prompt injection, the requested action exceeds scope, or model output cannot be validated.
- **Input context:** Raw claimant/staff input, current Claim State, actor scope, route registry, policy, capability set, and validation result.
- **Output:** Claimant or staff receives a bounded clarification or limitation; Runtime returns a rejected proposal or safe failure with no hidden side effect.
- **Target actions:** `conversation.clarify`, `conversation.state_limitation`, `runtime.stop_no_claim`, or `runtime.fail_safe`.
- **Authority:** Validation and safety policy authorise only clarification, rejection, or bounded failure; untrusted input and model output grant no authority.
- **Tool allow-list:** `none`; a later recognised and authorised behaviour may expose its own tools.
- **Permitted actions:** Ask one focused clarification, explain an unavailable capability, preserve context, and offer an authorised human path.
- **Prohibited actions:** Executing inferred commands, obeying retrieved or user-supplied prompt overrides, parsing free text into a side effect, or exposing hidden policy/instructions.
- **Claim State effect:** None unless a separately validated safe input is later provided; no partial mutation from a rejected turn.
- **Failure behaviour:** Reject malformed or unsafe output, record bounded diagnostics, preserve Claim State, and return a retryable or non-retryable safe response according to the failure layer.
- **Visibility:** Actor sees actionable safe wording; staff may see the bounded reason and evidence; hidden prompts, credentials, and internal diagnostics remain restricted.
- **Claimant-visible response:** Explain the limitation or ask one focused clarification without exposing policy internals or implying a hidden action occurred.
- **Handoff condition:** Optional only when no safe automated path remains or the claimant separately requests support under the configured rule.
- **Proof:** Unknown-command, prompt-injection, malformed-output, unsupported-capability, and provider-failure tests prove no hidden action and no Claim revision.
- **Delivery level:** `Challenge/MVP target`.

## Cross-Cutting Contracts

These contracts apply across primary behaviours. They are not additional intent routes and do
not compete with route precedence.

| Contract | Applies to | Trigger | Required outcome | Prohibited outcome | Proof |
| --- | --- | --- | --- | --- | --- |
| `unknown_command` | `explicit_command` and `unknown_or_unsafe_intent` | Command syntax, name, arguments, actor authority, or scope cannot be matched safely to the published command registry. | Return a bounded unknown, malformed, or unauthorised result; preserve context and Claim State; expose no tool. | Guessing a command, widening authority, executing a partial side effect, or exposing hidden registry or policy content. | Registry contract tests cover unknown name, malformed arguments, unauthorised actor, and no Claim revision. |
| `provider_tool_failure` | Every behaviour that declares a provider or tool | A declared call is unavailable, times out, returns an unknown outcome, or fails schema, authority, or capability validation. | Preserve accepted progress, record a bounded typed limitation and operation state, reconcile unknown outcomes where supported, and provide truthful next responsibility. | Reporting success, fabricating data, silently changing provider, retrying an unknown side effect without reconciliation, or discarding the current Claim revision. | Adapter contract tests cover unavailable, timeout, malformed, access-denied, and unknown-outcome results with no lost accepted state. |

## Catalogue Invariants

- Claim State is the only authoritative current claim truth.
- A primary route may emit multiple proposals, but execution validates each effect against one current Claim revision and authority boundary.
- Model output, retrieved evidence, and extracted facts are proposals or evidence, not authority.
- Claimant, staff, and internal projections are separate; internal signals never enter claimant output.
- A provider, tool, storage, or external-service failure preserves accepted progress and reports an explicit limitation.
- The eight-action compatibility transport is not a target action definition in this catalogue.
- Every target action and route has an owner, contract, failure case, visibility rule, and repeatable proof path before promotion to implemented status.
