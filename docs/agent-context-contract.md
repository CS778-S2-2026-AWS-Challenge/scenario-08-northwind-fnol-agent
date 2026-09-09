# Agent Context Contract

This contract defines the bounded context supplied to claimant and Staff Agent turns. It
does not replace Claim State, the API schemas, or the persistence contract. It tells the
Runtime what to select from those authoritative sources for one purpose and one identity.

## Context envelope

Every turn is built from:

| Slice | Claimant Agent | Staff Agent |
| --- | --- | --- |
| Identity and scope | Authenticated customer or anonymous session; one Claim | Authenticated staff identity; zero to five explicitly selected Claims |
| State | Current Claim revision, workflow, next action, active branch and field selection | Same Claim projections plus responsibility, handoff, work, review and operational state |
| Work | Unresolved questions, pending evidence/work, prior commitments, current required-now fields | Open gaps, blockers, ownership, due work and requested staff action |
| Messages | Current message plus bounded recent messages from the Claim's sessions | Bounded recent Staff Agent messages plus selected Claim communication |
| Sources | Claimant-visible evidence and cited retrieval results | Staff-authorised evidence, retrievals, signals, handoffs, actions and external records |
| Limits | Model profile budget and claimant visibility | Model profile budget and staff purpose/privacy boundary |

The Runtime filters every slice by actor, Claim ownership/role, visibility, purpose, and
the current revision before serialization. A browser-provided customer ID, role, provider,
endpoint, or secret is never a context selector.

## Model-aware budget

The selected published Model Profile supplies:

- `context_window_tokens`: provider-declared total window, when known;
- `max_input_tokens` and `max_output_tokens`: request limits;
- reserved input for system instructions, tool results, and structured output; and
- capacity status: `verified`, `configured`, or `unknown`.

The context builder allocates the request in this order: system policy and schema, current
Claim State and required-now branch fields, unresolved work and pending items, the current
message, relevant recent history, then optional cited sources. It truncates optional history
before required state and records a limitation when a source cannot fit or is unavailable.
Profiles with unknown capacity use a conservative configured budget; configuration is not
provider-readiness evidence.

## History and provenance

Complete immutable `MessageRecord` values remain persisted and are not sent on every turn.
Routine context uses the current message, a bounded recent window, and the session summary.
The builder follows `source_refs` to load a full source message only for a correction,
material conflict, explanation, evidence check, or missing semantic detail. The returned
source includes the immutable `message_id` and original content; a summary or text span is
not a substitute for the source record.

On resume the Runtime reads the latest Claim State first. If `Session.context_revision` is
behind the Claim revision it recomputes active branches, unresolved questions, pending work,
and the next action before selecting history. Resuming a working Claim reuses it and does
not create a duplicate Claim.

## Source precedence and conflicts

The Runtime keeps one selected value in Claim State and retains source-linked assertions.
New statements are classified as equivalent, compatible refinement, explicit correction,
material conflict, different semantic field, or irrelevant. A correction supersedes the
selected assertion without deleting its history. A material conflict keeps both sources and
creates clarification or professional-review work; it never becomes a fraud conclusion.

## Visibility and unavailable sources

Claimant projections exclude internal signals, staff notes, hidden model reasoning, provider
metadata, and another customer's history. Staff projections may include source-linked
internal records allowed by role and Claim scope. Every missing, stale, inaccessible, or
failed source is represented as an explicit limitation with a recoverable next step; the
model must not infer success from absence.

## Acceptance evidence

Contract tests must demonstrate claimant isolation, staff multi-Claim scope, bounded history,
selective source recovery, stale-session re-plan, model-budget truncation, and explicit
unavailable-source handling. A green API response alone does not prove a complete user journey.
