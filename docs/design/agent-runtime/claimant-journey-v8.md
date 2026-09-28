# Claimant Journey v8

This document publishes the evidence, decisions and implementation contract for claimant v8,
including the approved v3.15 family and service-admission decisions. It is the shared repository reference for
the implementation in PR #977, which delivers issues #976 and #980 and the bounded recovery
slice of #779. Its contracts can be read without a maintainer's local workspace.

## Evidence behind the change

The original audit used PR #977 at `8a50cdee2b06c8d6cecaebcc28ad5eb1c420e537`.
These are historical defects that define the acceptance cases, not claims about the new release:

| Case | Observed defect | Required behavior |
| --- | --- | --- |
| CH-1 | External assistance produced a card but discarded same-message facts. | Save facts, offer consent and ask a useful question in one turn. |
| CH-2 | Injury handoff stopped subsequent facts and Agent replies. | Commit safety support and continue the conversation without duplicate handoffs. |
| CH-3/4 | Normalized values and natural-language enum values failed or lost source authority. | Preserve grounded claimant provenance and the actual normalization flag. |
| CH-5/6 | Deterministic family/consent paths lacked a trace; decline retained stale consent progress. | Keep the audit gate, emit valid traces and recompute progress. |
| CH-7 | Ordinary intake failed even when external-service turns worked. | Use a satisfiable complete provider schema and preserve input on failure. |
| CH-8 | Requirement and confirmation rules prevented a bounded Home journey. | Collect, display and confirm facts without per-field confirmation calls. |
| CH-9 | Global question deletion removed useful model questions. | Preserve valid questions and reject only the invalid proposal. |
| CH-10 | Editing a created Claim reset its workflow to an intake state. | Keep the terminal workflow and external creation result unchanged. |

Live implementation checks also exposed three contract gaps now addressed: safety persistence
must precede the provider call; an inferred family must permit collection before confirmation;
and free-text placeholders must not count as collected answers. A malformed question is an
optional suggestion failure, not a reason to discard otherwise valid facts.

## Turn contract

One claimant turn may contain facts, a family result, a grouped next question,
eligible service suggestions, a safety or handoff signal, and a truthful reply.
Runtime validates the proposal and reduces it with the current Claim revision.
Intake is always retained as an intent even when the message also asks for
external help. `TurnTask` is audit classification only.

The model never authorises coverage, liability, fraud, settlement, or an external
side effect. Runtime owns field status, permissions, consent, lifecycle status,
revisions, idempotency, terminal protection, and the audit trace.

## Progress and confirmation

Branch requirements are computed by one `_required_set` implementation and are
classified as confirmed, recorded pending confirmation, or missing. A claimant
grounded normalised value keeps claimant provenance. Inferred and disputed values,
and authority-sensitive values without claimant provenance, require confirmation; pending confirmation does not
prevent the next useful question but can prevent final creation.

A single inferred family activates collection of that family's requirements. It does not
confirm the family field: that value remains recorded until the displayed batch is confirmed.
Each requirement belongs to exactly one of satisfied, recorded, or missing. Fallback questions
consume the same missing set and cannot independently reclassify a recorded family as missing.

Conversational confirmation and `POST /claims/{id}/form/confirmations` share the
same confirmation validation and fact-confirmation logic. The conversational record stores the displayed field set and
value fingerprint. The turn reducer compares it with the revision before the
new claimant message was persisted, then uses the final CAS to protect against
concurrent changes.

## Safety and external services

Runtime-detected safety and explicit human-support requests commit through the shared
handoff writer before model invocation. A model timeout or malformed response cannot undo
this action. The reducer handles additional model-originated escalation and checks existing
handoffs without duplicating them. Failed safety persistence is a hard failure. A later
provider failure returns a deterministic safety/support notice marked as recovery, keeps
the original message retryable and applies no model facts. ControlledAgent remains a
deployment choice, never a replacement for one failed model turn.

An open handoff continues to accept claimant messages and returns an Agent
reply. It may record facts and ask a non-blocking question. It suppresses all
new third-party suggestions until the handoff is resolved. Declined or withdrawn
offers are suppressed for three claimant turns; an explicit renewed request can
create a new offer identity. Consent, withdrawal, dispatch, result and handoff
mutations recompute the claimant next step.

Unknown family limits the frontend catalogue to cross-family manual assistance.
The independent Northwind Staff Assistance entry remains available. Manual/link/phone
third-party entries such as Police 105 remain registered guidance; using them does not
create an ExternalTask or imply that an external organisation accepted work.
Presentation metadata is projected by the service registry from the current
access and operation state. A redesign of polymorphic frontend rendering is outside this change.

The model receives the existing small service toolbox (at most eight lifecycle projections),
independent of family, with open-handoff and existing-operation exclusions. This is read-only
context, not permission or a new candidate state. `validate_turn_proposal` validates facts first,
then resolves service eligibility from the same-turn accepted family through the existing
eligibility query. The shared assertion resolver prevents conflicting or unsupported family
proposals from unlocking another family's services. Registry, cooldown, renewed intent,
handoff, disclosure and consent rules are unchanged. Optional lifecycle-read failure omits
services and logs a bounded diagnostic while preserving chat.

## Recovery and terminal lifecycle

The claimant model-dependency failure rule is the first registered
`RecoveryPolicyRegistry` entry. The inbound message/checkpoint is preserved
before provider execution. The original idempotency key replays historical turn evidence;
only `current_claim` and `current_claim_revision` refresh from authoritative state.
Explicit retry goes through `submit_message` with a new attempt
identity linked to the accepted inbound message; no retry endpoint is added.

Created and other protected terminal Claims cannot regress to an in-progress
workflow state after a form correction. Existing external-task, WorkItem,
handoff, consent and audit records remain authoritative for their own data.

## Provider profiles

The claimant default is `openrouter-gpt4o-mini` (`openai/gpt-4o`). Gemini
remains available for comparison and applicable multimodal checks. Qwen is a
local optional profile and is excluded from live provider evidence when offline.
The default profile is non-reasoning and receives no reasoning parameter.

Text and lookup turns cap output at 4500 tokens; media turns at 5500. These are
operating caps, not a guarantee covering every schema-legal output. Provider truncation
is an incomplete response and enters the saved-message recovery path. Full-envelope
v8 profiles reject estimated input above 6000 tokens and log, without rejecting, above
the 3000-token soft threshold. The explicit v7 rollback uses 5500: measured maximum
3955 plus 15%, rounded up. Narrow Evidence-history and deep-review budgets are separate.
JSON estimates use unescaped UTF-8 text, not ASCII escape sequences for non-Latin text.
Provider failure telemetry records status and error type
without storing prompts, claimant text, credentials, or raw provider responses.

## Executable envelope and responsibility boundaries

The canonical types are in `backend/domain/agent_v8.py`. The text wire schema lives in
`backend/prompts/v8/schema/turn.json`; the planner binds permitted field variants to the current
registry and adds the authorized Evidence reference for media input.

| Proposal member | Constraint and owner |
| --- | --- |
| `reply` | Non-empty, at most 500 characters; Runtime removes unsupported execution claims. |
| `reason_codes` | 1–5 entries, at most 50 characters each; audit classification only. |
| `field_changes` | At most eight field-code/value/quotation/precision proposals. Runtime derives source, status and bookkeeping. |
| `contents_item_changes` | At most six independent Contents items; these are not scalar form fields. |
| `next_question` | Optional group of 1–3 registered missing fields; wording at most 250 characters. Invalid structure or membership discards the whole group. |
| `service_suggestions` | At most three registered eligible identities, each with a bounded rationale. They never grant consent or dispatch authority. |
| `state_proposals` | At most two whitelisted urgency/support proposals; no coverage, liability, fraud or settlement decisions. |
| `escalation` | Advisory urgent-safety, human, accessibility, distress or professional-review request; Runtime safety takes precedence. |
| `ready_to_create` | Advisory; Runtime requires the computed requirements to be ready. |
| `confirms_batch` | Model interpretation for wording only; it neither authorizes nor vetoes confirmation. |

`V8FieldChange` quotes supporting claimant words in `reported_text`. The normalized value need
not be a substring of that quote. The quote must belong to the current claimant message;
an unsupported interpretation remains inference/proposed. Boolean polarity checks remain in
force. Evidence-derived values require the authorized Evidence ID and remain proposals.
`normalised` describes whether the value was actually transformed: a verbatim relative date
is false; a normalized value that differs from its quotation is true.

Scalar strings are bounded to 300 characters; quotations to 200. Text lists contain at most
50 items of at most 100 characters. Contents quantity is at most 999. The output-only
`V8MoneyAmount` bounds amount to 10,000,000 and is immediately converted to the shared money
type; this does not change money contracts elsewhere in the application.

`validate_turn_proposal` owns proposal legality, not persistence. Invalid core fact structure
or an empty original reply rejects the turn outcome. Services, state suggestions, escalation,
readiness claims and questions are optional: reject the bad component with diagnostics and
continue with valid facts. Free-text placeholder proposals are separately rejected through
the existing `rejected_bounds` path for text/location/text-list values. Legal enum `unknown`,
boolean and temporal contracts remain unchanged. A rejected field keeps its previous value
and status; a previously missing field does not become recorded.

`ValidatedTurn` contains the cleaned reply, valid form/Contents changes, optional question,
eligible service identities, authorized state proposals, escalation, readiness/confirmation
flags and structured rejections. `reduce_turn` combines this with the authoritative Claim,
messages and confirmation checkpoint to construct `TurnOutcome`. The persistence service
commits the outcome; the existing dispatcher performs authorized effects. Model output cannot
bypass this sequence. `TurnTask` labels audit records while `TurnIntents` combines intake,
correction, confirmation, status, policy/history lookup, Evidence and external assistance.

## Collection and confirmation rules

Branches have four kinds: fact, workflow, record and projection. Only fact branches contribute
scalar collection requirements. Each policy declares required-now, before-creation,
later-action or staff-only collection. Injury has persons affected, reported severity and
medical-attention fields; the restricted theft/discovery fields are executable registry
entries. Consent, Evidence, other-driver records and external tasks keep their existing stores.

`_required_set` combines common, selected-family and active fact-branch requirements. It retains
`contents.items` outside the scalar field-code intersection. `_requirements` classifies each
required scalar as confirmed/satisfied, proposed/recorded, or missing/disputed. Independent
Contents records are inspected directly: confirmed items satisfy their requirement, proposed
items are recorded, and no qualifying item leaves it missing. Pending-later material stays
distinct. Required-before-creation fields join collection before final readiness.

A single authoritative or persisted proposed `TurnFamilyResolution.product_family` activates
collection. Keyword hints alone do not select a family or add family requirements in a v8 model
turn. A proposed family does not gain confirmation authority. Persisted authority
conflicts remain explicit unresolved context; mentioning a wall in an authoritative Motor
Claim does not switch it to Home. Conditional branches persist while their supporting facts
remain relevant and exit on a contrary correction. Disabled or observation-only registry rules
cannot retain active collection effects.

A weak signal may expose the registered fields of a candidate conditional fact branch to
the model as `CANDIDATE_NOW`, allowing same-turn facts to be recorded. Candidate status does
not make those fields required or confirm the triggering fact. This consumes the already
policy-filtered branch result; disabled and observation-only rules remain without field effects.

Before a family is authoritative, v8 exposes every registered top-level family field as a
candidate to the model, including when no keyword matches or several do. Candidate admission
alone does not add requirements or satisfy readiness. The model interprets the complete account
and proposes the family and its facts in one response. The existing quotation/source validator
remains unchanged: unsupported quotations produce inferred/proposed facts, never automatic
confirmation. A persisted proposed family still selects its collection requirements.
Lower conditional branches retain their existing fact-driven policies. ControlledAgent and v7
retain their established admission behavior; the v8 model planner and persistence validation
explicitly select the same v8 family policy. No per-turn model failure invokes ControlledAgent.

Question priority is injury details, newly activated fact branch, family-specific fields,
other fact branches, then common requirements. The model chooses up to three related fields
from the first non-empty group. Runtime fallback consumes that same missing set and asks one
registered question. It does not re-evaluate family or create a second missing-field list.
An imperative request such as “Tell me what happened” counts once even without a question mark.
During handoff it is optional and excluded from repeated-question penalties.

`ConfirmationRequestRecord` stores `confirmation_id`, `claim_id`, `claim_revision`, the actual
displayed `field_codes`, `shown_values_fingerprint` and `created_at`. Fingerprints bind displayed
values and assertion identities, including Contents items. A generic acknowledgement cannot
confirm undisplayed information. Compare the record revision with `revision_before_message`,
not the revision after saving the acknowledgement itself. The final CAS separately protects
against concurrent mutations. A correction changes the fingerprint and invalidates stale
confirmation. Recovery reloads the original checkpoint. The UI button and conversational
confirmation remain separate entrypoints sharing these checks and fact-confirmation functions.

Conversational execution additionally requires `is_explicit_batch_accept(message_text)`:
an unqualified acceptance such as “Yes”, “All correct”, or the supported short Chinese
acknowledgements. A field-specific answer such as “Yes we can still live here” may update
habitability but cannot confirm the other displayed fields. The model's boolean cannot
override this boundary in either direction. A button's explicit field selection remains
its own acceptance signal and still passes the same revision/value binding checks.

## Durable turn sequence and failure behavior

1. Authenticate, scope the Claim/Session, check the HTTP key and expected revision, then load
   the pre-message revision and any displayed confirmation checkpoint.
2. Persist the claimant message and its checkpoint before model processing. A retry with the
   original client message identity reuses this inbound rather than inserting another.
3. Detect deterministic safety/support. Commit creation or upgrade through the shared handoff
   writer before routing or invoking the model. Existing open support is reused and only
   upgraded, never downgraded. Failure to commit is a visible hard error.
4. Resolve family, branches, intents, eligible services and bounded context from the current
   post-safety Claim. Invoke the selected published model; no per-turn ControlledAgent fallback.
5. Validate the returned proposal. Reduce valid facts and confirmation against the current
   Claim, recompute branches and progress, prepare messages, trace, work items and offers,
   then atomically commit with a second revision check.
6. Perform authorized post-commit dispatch through the existing external lifecycle. Optional
   service failure cannot erase chat or be described as successful execution. Freeze the
   claimant-safe response on the existing idempotency record before returning it.

On a provider failure the accepted input survives. If safety was committed, a durable Agent
notice contains safety guidance and the truthful support confirmation. It carries recovery
metadata and does not hide Retry. A later successful non-recovery reply completes the response.
No failed model facts are applied. Same-key replay freezes historical `claim_revision`, messages,
decisions and recovery metadata. Only `current_claim` and `current_claim_revision` are read afresh
after later Claim changes. Replay never invokes the model, reducer or service dispatcher and
never writes an audit event. Explicit retry uses a new HTTP key with the original inbound identity,
content and checkpoint through `submit_message`; there is no new retry endpoint.

If a process stops after the Claim commit but before the first response is frozen, replay can
recover from the durable decision and freeze the first response. That response is a safe
post-dispatch observation and may include a concurrently completed mutation before freezing;
it is not represented as the original reducer snapshot. Once frozen, historical evidence remains
exact; only the two current-state fields refresh. The frontend installs `current_claim`, never
historical form or decision deltas. When revisions differ, it refreshes message actions through
the existing messages read endpoint instead of enabling historical consent controls. A failed
action refresh does not turn an already accepted message into a delivery failure.

## Progress writers and compatibility decisions

`recompute_progress` is the shared progress decision point. Created/terminal Claims do not
regress. Open support retains its owner and suppresses every third-party suggestion, including
renewed explicit requests. Professional-review transitions remain staff-owned. Only collecting
or ready-for-next states advance through ordinary intake and confirmation.

| Consumer | Required integration |
| --- | --- |
| `messages.py` | Orchestrates checkpoint, provider, reduction, persistence and dispatch; no competing next-step overwrite chain. |
| `claims.py` | Initialization is the declared exception; form PATCH and confirmations call shared progress inside their existing mutation boundary. |
| `external_service_offers.py` | Recompute after consent decisions instead of retaining the previous consent prompt. |
| `external_services.py` | Retain the assessor-specific read overlay; do not rewrite terminal Claim progress for external status. |
| `handoffs.py` | Shared writer for direct support, deterministic pre-provider support and reducer escalation; all share upgrade/idempotency rules and recompute progress. |
| `integrations.py` | Verified generic and assessor result writes invoke shared progress in their existing transaction. |
| `staff_actions.py` | Apply authorized staff responsibility first; recompute without replacing that decision. |
| `agent.py` / `model_agent.py` | Produce proposals, not independent persisted progress authority. |

| Decision | Retained and removed responsibilities |
| --- | --- |
| T1 | One context-aware family resolver. Keep the independent pure-text ControlledAgent helper and its callers unchanged. |
| T2 | Remove external-only task selection; retain intent contributions and bounded renewed-intent/no-model patterns. |
| T3 | Shared progress and registered fallback; retain the assessor read overlay. |
| T4 | One required set and mutually exclusive satisfied/recorded/missing classification. |
| T5 | Preserve ControlledAgent, `_guided_proposal` and PRES-02 behavior; v8-only prose and confirmation assembly do not leak into them. |
| T6 | Keep precise safety recognition separate from weak-signal branch activation while sharing vocabulary. |
| T7 | Publish v8; keep deprecated v7 rollback artifacts and leave deprecated v6 source inactive. |
| T8 | Keep generic and dedicated assessor lifecycles for this delivery; migration is issue #1005. |
| T9 | Preserve valid model questions, remove global question-sentence deletion, and use one reply composer. |
| T10 | Continue handoff conversation; no new external suggestions until support closes. |
| T11 | Preserve both confirmation entrypoints with shared validation. |
| T12 | Complete v8 turn envelope and media variant; retain bounded Evidence-history/summary contracts. |
| T13 | Intents select capabilities; task labels do not discard fact output. |
| T14 | Runtime derives pending Police material on the model path; controlled fixture behavior remains. |
| T15 | One truthful reply policy for denied services and unsupported execution claims. |

Unlisted duplicate responsibility must be recorded and resolved before changing it. Do not
silently keep two competing implementations or merge them without an explicit disposition.

## Release, migration and rollback

The published Release Set atomically selects the v8 instruction, schema, profiles and registry
versions. Existing records remain readable through additive fields/defaults; there is no bulk
rewrite of old decisions or Claim history. A schema/prompt file edit alone does not change an
already-published immutable release.

The deployment rollback procedure requires both selecting the complete previous v7 Release
Set and reverting/deploying the pre-v8 implementation change set. Merely selecting the v7
prompt is not the declared operational rollback, even though compatibility tests exercise
retained v7 parsing paths on the new code. Preserve the previous code and release coordinates
and perform rollback through the established operator-controlled workflow. v6 is not a fallback.

## Acceptance and delivery checkpoints

The twelve dependency steps are provider schema/budget; standalone progress/terminal guards;
shared traces; executable branches/requirements; multi-intent v8 profiles; validator; safety and
handoff; eligible offers and consent; provenance and confirmation; full reducer migration;
persist-first recovery/CAS; then frontend projection, documentation, release and acceptance.
They are internal checkpoints in one delivery, not separately published partial implementations.

The repeatable mocked-provider Motor/Home/Contents API journeys cover normal progression,
grouped confirmation without `/form/confirmations`, handoff continuity and creation. Static
single-writer checks, schema satisfiability, source/confirmation, eligibility, terminal, recovery,
placeholder and malformed-question tests cover the individual boundaries. Permission, claimant
visibility, concurrency, idempotency and audit tests remain mandatory.

Live GPT-compatible and Gemini checks must record published release/prompt, provider model,
actual usage and latency separately from heuristic budget estimates. Qwen is not called while
offline. CH-1 through CH-8 and CH-10 require visible browser observations; CH-9 uses controlled
known output. Keep failed attempts and blocked observations distinct from passes.

CH-8 ends in the browser at confirmed `ready_to_create`. Assert
`primary_action.action_code=claimant.create_claim` and `available=false`: #926/#928 still own the
independent final-submission gate. Creation and terminal corrections use real API calls and
must be labelled API acceptance, not browser end-to-end creation. A successful component test,
fixture replay, API call or schema probe cannot substitute for a different evidence level.
