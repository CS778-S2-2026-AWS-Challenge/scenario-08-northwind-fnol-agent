# Sprint 2 Week 4: Connected MVP and Verified Delivery

## Status

- **Period:** 24-28 August 2026
- **Capacity model:** five implementation stacks, normally two four-hour cards per owner per day, with reduced Day-5 stabilisation/documentation cards and a one-hour whole-team presentation gate
- **Committed issue set:** #233-#283
- **Document role:** time-bound Sprint 2 Week 4 commitment baseline
- **Product authority:** current `SPEC/` and current engineering contracts remain authoritative for long-lived product, API, safety, data, identity, and runtime behaviour

This document records committed scope and sequencing. It does not mark any issue complete, prove provider availability, or replace the acceptance criteria and current status on the linked GitHub issues and pull requests.

## Sprint Goal

Turn the existing adaptive FNOL prototype into a connected, reviewable MVP slice in which:

- claimant interaction can use bounded Agent behaviours, an explicit model gateway, and controlled motor/home/contents branching;
- knowledge retrieval, structured policy/history records, evidence, object storage, and runtime profiles remain provider-neutral and truthfully labelled;
- Claim State, sessions, handoffs, staff messaging, resume, revisions, and identity share explicit transactional and authorisation boundaries;
- the Staff Workbench can receive context, communicate with claimants, and use clearly advisory Agent assistance;
- a bounded Control Plane/Admin slice can demonstrate real versioned configuration behaviour without implying the full administration backlog is complete;
- canonical evidence and external-service scenarios remain traceable across claimant and staff views; and
- Day 4 validation drives Day 5 fixes, limitations, capability status, and a repeatable team presentation.

The quality bar is not feature count. A capability is useful only when its authority, ownership, visibility, failure behaviour, evidence, and limitations can be explained and repeated.

## Non-Goals and Truthful Boundaries

Sprint 2 Week 4 does **not** by itself commit to or prove:

- a production IdP, SSO, MFA, session-management, key-rotation, or compliance programme;
- production-ready AWS, Cloudflare, MongoDB, MinIO, or Northwind provider connectivity unless independently verified during the sprint;
- the full Control Plane/Admin backlog in #208-#215 or the full parent scope in #209;
- production-scale transactions, availability, disaster recovery, or data-retention operations for unverified provider profiles;
- autonomous coverage, liability, fraud, approval, rejection, medical, or other high-impact decisions;
- unrestricted staff access to every claim or unrestricted integration access to every internal operation;
- a remote Agent-service identity when the current Agent remains in-process; or
- complete post-FNOL claim handling.

A fixture, mock, compatibility layer, configured endpoint, or successful demonstration remains labelled as such.

## Committed Stacks and Ownership

| Stack | Primary owner | Day 1 | Day 2 | Day 3 | Day 4 | Day 5 |
| --- | --- | --- | --- | --- | --- | --- |
| Agent Runtime + Claimant Experience | `Ysoseri1224` | #233, #234 | #243, #244 | #253, #254 | #263, #264 | #273, #274 |
| Data Platform + Knowledge/RAG + Cloud Integration | `liyang6620` | #235, #236 | #245, #246 | #255, #256 | #265, #266 | #275, #276 |
| Backend Domain + Persistence + Identity | `jxu316-arch` | #237, #238 | #247, #248 | #257, #258 | #267, #268 | #277, #278 |
| Staff Operations + Control Plane Frontend | `LLL263` | #239, #240 | #249, #250 | #259, #260 | #269, #270 | #279, #280 |
| Evidence + External Service Integration | `bdfa123` | #241, #242 | #251, #252 | #261, #262 | #271, #272 | #281, #282 |
| Whole team | all five members | — | — | — | — | #283 |

The issue body owns the exact deliverable and acceptance criteria. This table is the commitment map, not a substitute for those contracts.

## Day-by-Day Delivery Intent

### Day 1 — contract and boundary day

Issues #233-#242 define or verify the boundaries required for safe parallel implementation:

- Agent behaviour and model-gateway delivery slice;
- runtime-profile and S3-compatible object-storage contracts;
- shared Claim State transaction and identity/developer-mode contracts;
- claimant-to-staff messaging journey and bounded Control Plane interface; and
- canonical scenario/evidence baselines plus the first RAG/external-service source inventory.

Day-1 work should reduce ambiguity. It must not prematurely claim that Day-2/Day-3 runtime behaviour is already implemented.

### Day 2 — first connected implementation slices

Issues #243-#252 implement one bounded capability per Day-1 contract:

- Agent intent routing and one live general-purpose model path;
- MinIO-through-boto3 and first RAG ingestion;
- explicit role authentication/developer mode and claimant-to-staff messaging APIs;
- staff conversation UI and Control Plane shell/access boundary; and
- realistic structured MVP data plus a bounded external-service adapter fixture.

### Day 3 — shared MVP connection

Issues #253-#262 connect the main product slices:

- controlled motor/home/contents branches and scoped Agent tools;
- filtered RAG plus provider-neutral runtime deployment profiles;
- one revisioned claim/session/handoff/message flow and the bounded versioned Admin API slice;
- staff messaging with advisory `@Agent` assistance plus one real Control Plane configuration flow; and
- canonical evidence/data loading plus one claimant-facing external-service experience.

### Day 4 — adversarial validation

Issues #263-#272 validate the connected system rather than adding unrelated breadth:

- natural intake, branch selection, commands, tool authority, prompt injection, model failure;
- object storage, RAG citations, runtime profiles, and temporary deployment status;
- claim/handoff/messaging/resume/revision conflicts plus role/developer-mode boundaries;
- staff takeover, advisory Agent collaboration, and Control Plane behaviour; and
- canonical scenarios, external-service failure, retry, consent, and cross-stack defects.

A Day-4 failure is useful evidence when it is reproducible, owned, and not hidden.

### Day 5 — fix, stabilise, document, present

Issues #273-#282 fix the highest-priority Day-4 defects, stabilise the demonstrable paths, and document verified capability and limitations. Issue #283 is the whole-team presentation/rehearsal gate.

Day 5 is not a new-feature day except where a narrowly scoped fix is required to satisfy an already committed acceptance criterion.

## Critical Dependency Gates

The following sequencing rules are part of the sprint commitment because violating them creates predictable rework or authority defects.

### Backend / identity / messaging

1. #237 defines the shared Claim State transaction boundary before #248 and #257 rely on multi-record mutation semantics.
2. #238 defines the identity/developer-mode boundary before #247 implements it.
3. #239 defines sender, audience, delivery, failure, retry, and Agent-suggestion semantics before #248 finalises messaging API behaviour.
4. #248 must provide a stable messaging contract before #249 builds the conversation UI and before #257 connects the shared state flow.
5. #247 and the Control Plane screen/access contract must exist before #258 exposes Admin endpoints.
6. #257 is the connected-state prerequisite for #267; #247 is the identity prerequisite for #268.

A blocked dependency must remain visible. A downstream card must not invent incompatible semantics merely to start on schedule.

### Agent / model / tools

1. #233 and #234 define the Day-1 behaviour/gateway boundaries before #243/#244 implementation.
2. #244 establishes the authorised live-model path before #254 treats model-backed tool orchestration as connected.
3. #254 consumes RAG, structured policy/history, and handoff contracts; knowledge RAG does not replace structured claim/policy/history or deterministic authority.
4. Day-4 #263/#264 validate both successful and adversarial behaviour before Day-5 #273/#274 stabilisation claims.

### Data / storage / RAG

1. #235/#236 define profile and S3-compatible boundaries before #245/#256 composition.
2. #242 provides the approved source inventory before #246 ingestion.
3. #246 precedes #255 filtered retrieval/citation behaviour.
4. Runtime profiles remain mutually exclusive and fail closed when required capabilities are missing; no unselected provider is a silent fallback.

### Workbench / Control Plane

1. #239 precedes #249; #240 plus the admin identity contract precede #250.
2. #249 precedes #259; #250 and #258 precede the real configuration workflow in #260.
3. `@Agent` output in #259 remains advisory until explicit staff action sends or applies it.
4. #270 must distinguish working configuration logic from unavailable or unfinished modules.

### Evidence / external service

1. #241 is the canonical scenario/evidence baseline for later structured data and cross-stack scenario work.
2. #242 precedes #252's external-service fixture and contributes source authority/version/scope to RAG work.
3. #251/#252 precede #261/#262 connected experiences.
4. Day-4 #271/#272 produce repeatable defects/results before #281/#282 stabilisation and capability reporting.

### Presentation gate

#283 depends on a demonstrable build and the verified capability/limitations register, especially #282. Presentation wording must follow verified status; the presentation cannot promote a fixture or partial capability to production readiness.

## Bounded Control Plane Commitment

The full parent Admin/Control Plane scope remains broader than this sprint. In particular:

- #209 remains an `extra` parent backlog item for the complete Admin API/versioned configuration foundation;
- #258 is the committed Day-3 bounded backend slice: configuration read, draft update, validation status, publication state, and audit metadata;
- #250/#260/#270/#279/#280 cover only the corresponding bounded frontend/workflow/validation/stabilisation slices; and
- unfinished Control Plane modules must expose their actual unavailable/partial state rather than fake success.

Completing #258 does not close the full #209 backlog automatically.

## Shared Safety and Authority Rules

Every stack preserves these cross-cutting rules:

- `WorkingClaim` is the authoritative current FNOL state and material shared writes use its revision boundary.
- AI/model output is advisory until deterministic authority permits the action; a model cannot grant itself identity, scope, schema, or high-impact authority.
- Authentication, coarse role/scope, resource authorisation, and domain-action authority are separate checks.
- Claimant identity is self-scoped; staff role does not automatically grant every claim; integration base scope does not automatically grant every internal operation.
- Original evidence, structured provider records, RAG citations, review signals, staff decisions, and claimant-visible updates remain distinct records/authority classes.
- Handoff preserves context and ownership; failure must not create partial ownership, duplicate messages, or contradictory Claim State.
- Secrets and provider credentials do not enter public API payloads, logs, fixtures, or versioned configuration values.

## Evidence and Verification Standard

Opening a PR is not completion evidence. For a committed card to be treated as complete, the issue/PR should record, as applicable:

- exact head/commit being verified;
- focused acceptance tests or repeatable scenario results;
- repository quality gates required by current governance;
- current provider/runtime status without unsupported readiness claims;
- contract/API/data/projection impact;
- known limitations and remaining dependencies; and
- independent review or a repeatable check by another team member where the issue requires it.

Historical Day-1-to-Day-5 evidence may support provenance but does not override current code or current contracts.

## Capability Status Vocabulary

Use conservative status language:

- **verified:** the named capability and environment were directly demonstrated and acceptance evidence is recorded;
- **partial:** a meaningful slice works, but one or more required capabilities/conditions are not verified;
- **unavailable:** the selected environment cannot currently provide the capability and fails explicitly;
- **fixture-dependent:** behaviour is repeatable against fixtures/mocks but is not evidence of a live provider.

Do not infer AWS, MongoDB, Cloudflare, model, Northwind, or production readiness from provider-neutral contracts or fixture success.

## Change Control

- `SPEC/` owns long-lived product requirements.
- Current `docs/` engineering contracts own their named technical boundaries.
- This file owns the time-bound Sprint 2 Week 4 commitment map.
- GitHub Issues own detailed deliverables, acceptance criteria, assignment, and execution state.
- The Project board may visualise status but must not silently redefine committed scope.

Issue status, implementation details, or estimates may evolve without rewriting this document when the committed outcome is unchanged. Adding/removing a committed card, materially expanding a deliverable, moving an `extra` parent into committed capacity, or changing a critical dependency must update this baseline in a reviewed change.

## Sprint Exit Standard

Week 4 exits successfully only when the team can distinguish, with evidence:

1. what is connected and repeatable;
2. what is fixture-dependent;
3. what is partial or unavailable;
4. which AI actions are advisory versus authorised;
5. how Claim State, identity, messaging, handoff, evidence, and configuration stay consistent under failure; and
6. what remains for later sprints without presenting it as already complete.

The final presentation should make those boundaries an advantage: the system demonstrates useful AI behaviour while preserving deterministic authority, traceable evidence, shared state, and honest operational limits.