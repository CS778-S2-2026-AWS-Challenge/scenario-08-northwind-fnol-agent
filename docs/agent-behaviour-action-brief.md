# Agent Behaviour and Action Brief

This is the implementation brief for P6.2. It defines what the Agent may propose and what
the Runtime must validate. Prompts render this brief for a selected model; they do not grant
authority, mutate Claim State, or replace a registered action contract.

## Shared contract for every behaviour

Each behaviour records its trigger/intent, input context, output, target Runtime actions,
authority, tool allow-list, permitted and prohibited effects, Claim State effect, visibility,
failure/unavailable outcome, confirmation requirement, handoff condition, and repeatable proof.

The model may propose facts, questions, citations, drafts, and actions. Runtime code owns
schema validation, branch and Field Registry checks, permission, revision, idempotency,
source provenance, visibility, and execution. Unknown actions or provider failures fail
closed without partial Claim mutation.

## Six behaviour families

| Behaviour | Trigger and output | Runtime boundary | Proof focus |
| --- | --- | --- | --- |
| Field collection | Claimant describes a loss or supplies a missing field; return a focused next question or accepted candidate facts | `conversation.ask`, `claim.propose_field`, `claim.upsert_work_item`; registered branch and current-action fields only | One message can preserve multiple sourced facts and skip already confirmed fields |
| Natural-language correction | Claimant corrects or refines a prior statement; explain the change and request confirmation only when material | `claim.propose_field`, `conversation.clarify`, `claim.resolve_assertion`; no silent overwrite | Equivalent, refinement, correction and conflict retain source history |
| Progress explanation | Claimant or staff asks what is complete, pending or next | `conversation.answer`, read-only Claim/WorkItem/Evidence tools | Response matches current projection and labels pending/unavailable work |
| RAG/policy/history query | User asks why a step is needed or asks about policy/history | `claim.read`, `external.lookup_knowledge`; cited source required, no state mutation | Source, version, section, confidence and no-result limitation are visible to the permitted role |
| Third-party service suggestion | Context indicates an assessor, repairer or other approved service may help | `external.load_requirements`, `external.prepare_request`; consent and authority remain separate | Missing consent, unavailable provider, duplicate and unknown outcomes are recoverable |
| Professional handoff | Clear human request, unresolved material conflict, high-impact ambiguity or approved safety signal | `human.create_handoff`, `claim.upsert_work_item`; Runtime sets priority and packet | Handoff contains source-linked facts, gaps, responsibility and next step without repeating intake |

## Cross-cutting confirmation gate

Confirmation is required for a material interpretation, conflict resolution, claimant
declaration, customer-controlled choice, external disclosure, or another policy-marked
consequential action. It is not a seventh business route and must not be used to re-ask
already confirmed facts. A declined or expired confirmation leaves Claim State unchanged and
returns a clear next step.

## Human-support rule

The first clear, unambiguous natural-language request to speak with a person creates a
standard-priority handoff. Repeated requests, urgency, distress, and accessibility needs
transfer immediately and may raise priority. Claimant `@agent` is not a supported entry
point; Staff Agent assistance uses the dedicated Workbench session.

## Failure and visibility rules

- Unknown or malformed model output is rejected before messages, state, or idempotency are persisted.
- A tool or provider failure preserves accepted progress and records an explicit retryable or terminal limitation.
- A proposed action is never described as completed until the authoritative result exists.
- Claimant responses contain only claimant-safe projections; staff-only signals, notes, and provider metadata remain internal.
- Staff Agent drafts are suggestions. Sending, mutation, disclosure, external execution, and high-impact decisions require the registered business route and fresh authority.

## Proof matrix

The repeatable proof set includes: multi-intent intake with no repeated question; correction
and material-conflict resolution; progress with pending police evidence; cited no-result and
unavailable retrieval; consent-required third-party suggestion; first ordinary human request
and urgent handoff; malformed/unknown action rejection; and claimant/staff visibility checks.
