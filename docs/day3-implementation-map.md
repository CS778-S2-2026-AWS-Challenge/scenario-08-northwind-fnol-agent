# Day 3 Implementation Map

## Purpose and Status

This map is the Day 2 planning contract for the Day 3 implementation work. It
connects claimant states, Agent actions, API contracts, fixtures, and
observable state without claiming that the frontend, Agent, or backend are
already integrated.

The normative inputs are `SPEC/`, `docs/api.md`, `docs/persistence-schema.md`,
and the Sprint 1 acceptance scenarios. The current customer page still uses
the temporary `/api/claims/message` connectivity route. Day 3 work must move to
the versioned routes and preserve the existing domain and persistence
boundaries.

## Baseline and Planned Ownership

| Surface | Current baseline after Day 2 | Day 3 consumer |
|---|---|---|
| Claimant UI | `customer/src/App.jsx` has a temporary text-entry shell and legacy route | Claimant journey components and state transitions |
| Versioned API | Claim/session/form routes are available; message/evidence routes are contract-defined but not implemented | Agent and claimant clients |
| Domain state | Claim state, form fields, sessions, messages, and evidence records are shared models | Agent updates and claimant projections |
| Persistence | `FixtureRepository` implements the replaceable repository boundary | Scenario fixtures and future adapters |
| Agent | No production or provider-specific Agent implementation is claimed | Controlled action selection and route guards |
| Workbench | Staff requirements remain dependent on D2-R05 and D2-I05 | Consume the same persisted state after its contract is accepted |

The map describes planned consumers. It does not authorize new AWS services,
production policy decisions, or a full frontend-backend integration in Day 2.

## Scenario Dependency Matrix

The fixture names below are stable planning identifiers. AT-01, AT-02, AT-04,
AT-05, AT-06, AT-08, and AT-12 now have validated synthetic JSON fixtures
under `tests/fixtures/scenarios/`; the remaining identifiers continue to
describe planned fixture work.

| Scenario | Claimant page and state | Agent action and guard | API contract dependency | Fixture dependency | Observable result |
|---|---|---|---|---|---|
| AT-01 Clear minor motor | New report, conversation, form confirmation, ready for next step | `ASK` -> `CONFIRM` -> `PROCEED`; do not create until required facts are confirmed | Create claim, session message, form patch/confirmation, internal claim creation | `fixture://scenarios/AT-01-clear-motor` | Confirmed incident fields, next step, mock claim identifier |
| AT-02 Ambiguous policy | Evidence/uncertainty panel and professional-review next step | `ASK` or `HANDOFF`; coverage ambiguity never becomes an approval decision | Claim/session, form, claimant-safe update, internal review handoff | `fixture://scenarios/AT-02-coverage-ambiguity` | Ambiguity and cited evidence remain visible to staff; claimant sees plain-language next step |
| AT-03 Complex/conflicting | Conflict state, correction path, professional-review status | `CLARIFY` then `HANDOFF`; no unsupported conclusion | Message, form correction, internal signal/handoff | `fixture://scenarios/AT-03-conflict` | Conflict is recorded with source references and no automatic high-impact decision |
| AT-04 Injury/danger | Urgent interruption and bounded safety guidance | `URGENT_HANDOFF` immediately when the safety trigger is explicit | Message, support request, handoff/update | `fixture://scenarios/AT-04-urgent` | Normal intake stops; urgent handoff and claimant-safe responsibility are recorded |
| AT-05 Human request | Human-support choice or immediate transfer state | Apply the controlled first-request rule; repeated, distress, urgent, or accessibility requests transfer | Support request, session resume package, claimant update | `fixture://scenarios/AT-05-human-request` | Handoff context includes confirmed facts, open questions, and next owner |
| AT-06 Pending police document | Evidence pending state while unrelated actions remain available | `ASK` for safe current work; do not block unrelated actions on later evidence | Evidence registration/list, form, session, claimant update | `fixture://scenarios/AT-06-pending-evidence` | Pending item and responsibility are visible; later submission remains resumable |
| AT-07 Image facts | Upload/processing/proposed-facts states with correction controls | Use evidence extraction as a proposal; `CONFIRM` or `CLARIFY` before form update | Evidence upload/complete, form proposal, message | `fixture://scenarios/AT-07-image-assist` | Extracted facts remain proposed until claimant confirmation |
| AT-08 Ten-day resume | Resume summary, unresolved work, prior commitments, current next step | `ASK` from bounded resume context; never replay the full transcript by default | Start/read session, message, claim projection | `fixture://scenarios/AT-08-resume` | Same working claim resumes without repeated intake or lost commitments |
| AT-09 History review signal | Claimant-safe review status; internal signal hidden | `HANDOFF` or `CLARIFY`; a signal is evidence for review, not a fraud conclusion | History adapter boundary, internal signal, staff handoff, claimant update | `fixture://scenarios/AT-09-history-signal` | Signal and source references reach staff; claimant response contains no internal signal |
| AT-10 Assessor route | Claim-created state with route, timing, and next step | `CREATE_CLAIM` only after validation; assessor action remains controlled | Internal claim creation, external claim projection, assessor boundary | `fixture://scenarios/AT-10-assessor` | Claim identifier, route, status, next step, and expected timing are visible |
| AT-11 Coexisting dimensions | Multiple state badges/next-step explanations without overwriting one another | Select the next safe action from all dimensions; pending evidence cannot erase clear coverage | Claim state, evidence, form, next-step projection | `fixture://scenarios/AT-11-multi-state` | Independent state dimensions remain intact and only the relevant action is blocked |
| AT-12 Staff signal write-back | Claimant update after staff action; internal details remain hidden | Staff action is outside claimant Agent authority; write-back must pass visibility rules | Workbench action/update contract, claim revision, claimant updates | `fixture://scenarios/AT-12-signal-writeback` | Staff decision changes shared state and produces the correct claimant-visible update |

## Shared API and State Contract

Day 3 implementation should use these existing contract names rather than
introducing private equivalents:

- Claim lifecycle: `POST /api/v1/claims`, `GET /api/v1/claims/{claim_id}`.
- Session lifecycle: `POST` and `GET`
  `/api/v1/claims/{claim_id}/sessions` and its session resource.
- Conversation: the documented session message routes; message visibility is
  filtered before claimant projection.
- Structured form: `PATCH /api/v1/claims/{claim_id}/form` and the documented
  confirmation route, with `If-Match` and the claim revision.
- Evidence: the documented evidence registration, upload, and completion
  routes; pending evidence is represented as outstanding work.
- Human support and progress: the support-request and claimant-update
  contracts, with handoff context preserved.
- Internal operations: claim creation, history, policy, assessor, signal, and
  workbench actions stay behind their documented internal boundaries.

Every mutation must preserve server-generated identifiers, claimant ownership,
idempotency where required, optimistic revision checks, and claimant/internal
visibility separation.

## Fixture and Test Plan

The Day 3 fixture entry point should expose a scenario by its stable identifier
and return synthetic inputs plus expected state transitions. Each scenario
fixture should contain:

1. starting claim/session state;
2. claimant message, form, evidence, or support input;
3. expected Agent action and guard outcome;
4. expected revision and persisted records;
5. claimant-visible output and internal-only assertions.

Tests should first exercise the service and repository boundary with the
fixture, then add API tests for request/response and error envelopes. A test
must prove that internal signals, staff notes, provider keys, and synthetic
adapter details do not appear in claimant responses.

## Unresolved Decisions

These decisions remain visible and must be resolved at the indicated consumer
boundary rather than silently guessed:

| Decision | Why it matters | Next owner or gate |
|---|---|---|
| First explicit human request: immediate transfer or one transparent choice | Changes AT-05 interaction and handoff timing | Product rule before D3-P04 |
| Required fields by claim type and route | Controls `CONFIRM`, `PROCEED`, and `CREATE_CLAIM` guards | Formal field/route rule before D3-P02 |
| Policy and history response shapes | Controls evidence-linked review and source references | Adapter contract before D3-P03/D3-P09 |
| Image/document extraction result and failure states | Controls proposed-field lifecycle and retry UI | Evidence boundary before D3-P05 |
| Claim creation and assessor response semantics | Controls external claim projection and expected timing | Provider inspection before D3-P09 |
| Staff queue fields and allowed write-back actions | Controls AT-09/AT-12 workbench behaviour | D2-I05 and D3-P07/P08 |
| Production authentication and customer identity mapping | Synthetic token is prototype-only | AWS/environment inspection before deployment |
| Metrics for token, retry, latency, and staff handling cost | Controls scenario evidence and comparison | Measurement design before D3-P10 |

Until these are decided, implementation must use explicit prototype fixtures,
bounded rules, and honest `next_step` text. It must not present a fixture,
placeholder route, or internal signal as a confirmed Northwind production fact.

## Day 3 Handoff Checklist

- Claimant work has a named page/state owner and consumes the shared API models.
- Agent work has an action, guard, required inputs, and visible state result for
  each path.
- Fixture work has one stable identifier per scenario and expected persisted
  state.
- API tests cover success, ownership, visibility, idempotency, and revision
  errors for each implemented route.
- Any unavailable adapter or unresolved business rule is recorded as a bounded
  pending state, not hidden behind a guessed implementation.
