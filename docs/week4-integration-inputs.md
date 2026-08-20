# Week 4 compatibility and integration inputs

Issue: #150

This is the `bdfa123` half: the evidence, fixture, and path-compatibility
inputs. `liyang6620` confirms the API and AWS integration inputs.

Compiled at the end of Sprint 2 Day 4 against `main`. Every status below is
what the repository actually reports, not what a card claims.

## Read this first

Issue #150 depends on the other nine Day 5 validation cards completing. **They
have not.** All nine are still open. This document is therefore a compilation of
the current state, not a Ready declaration, and the incomplete rows are marked
so they cannot be mistaken for finished work.

## Integration points

Every replaceable boundary, its provider, its consumers, and what
`GET /health/ready` reports today. The `Check` column is the key `GET /health/ready` reports, so this table and
the runtime can be compared directly.

| Integration point | Check | Port | Provider now | Consumers | Status |
| --- | --- | --- | --- | --- | --- |
| Policy retrieval | `policy` | `PolicyHistoryAdapter` | `MockPolicyHistoryAdapter` | `POST /internal/v1/policy/search`, retrieval persistence, review signals | `using_fixture` |
| Claim history retrieval | `claim_history` | `PolicyHistoryAdapter` | `MockPolicyHistoryAdapter` | `POST /internal/v1/claim-history/search` | `using_fixture` |
| External claim creation | `claims_service` | `ClaimsServiceAdapter` | `MockClaimsServiceAdapter` | `POST /internal/v1/claims/create` | `using_fixture` |
| Assessor routing | `claims_service` | `AssessorServiceAdapter` | `MockAssessorServiceAdapter` | `POST /internal/v1/assessors/route` | `using_fixture` |
| Evidence object storage | `evidence_storage` | `EvidenceStorage` | `MockEvidenceStorage` | upload target, upload completion | `using_fixture` |
| Staff queue notification | `handoff_dispatch` | `HandoffDispatchAdapter` | `MockHandoffDispatchAdapter` | claimant support request | `using_fixture` |
| Persistence | `persistence` | `PersistenceRepository` | `FixtureRepository` | everything | `not_configured` |
| Agent turns | `agent` | `AgentTurnProvider` | `ControlledAgent` | claimant conversation | `not_configured` |

Assessor routing has no readiness check of its own; it currently shares the
`claims_service` row. Worth splitting when a real provider appears, because the
two can fail independently.

**No AWS capability is confirmed.** `aws_policy_history`,
`aws_claims_service`, and `aws_evidence_storage` all report
`pending_confirmation`. Every path above runs on a fixture under the production
contract, and says so at runtime rather than implying otherwise.

`persistence` and `agent` report `not_configured`, but that is a **reporting
gap, not a missing seam**. `create_app()` already injects `PersistenceRepository`
and `AgentTurnProvider` and defaults them to `FixtureRepository` and
`ControlledAgent`, exactly like the other six. What they lack is a
`connection_status()` on the port, so readiness has nothing to ask and returns a
hardcoded string. Correcting that is small and worth doing before Week 4, so the
readiness endpoint describes all eight boundaries the same way.

## Fallback behaviour

Each fallback is demonstrable, not asserted. Every mock carries a settable
outage so the degraded path is a business path rather than a flaky test.

| Boundary | On failure | Claim outcome |
| --- | --- | --- |
| Policy / history retrieval | `unavailable` with limitations only — no source, no facts, nothing persisted | unchanged; an absent answer never becomes a finding |
| Evidence storage | `503 DEPENDENCY_UNAVAILABLE`, `retryable: true` | unchanged; never reported as a rejected file |
| Staff queue notification | `delivery.state: queued_locally` with a claimant-safe limitation | handoff persisted, revision advances once, still in the staff queue |
| Claim creation / assessor routing | adapter idempotency conflict surfaces as `409` | no duplicate external claim |

Registering evidence the claimant does not yet hold never touches the object
store, so that path keeps working during a storage outage.

## Evidence and fixture inputs

| Family | Location | Verifier | Status |
| --- | --- | --- | --- |
| Lifecycle catalogue | `tests/fixtures/evidence/evidence-lifecycle.json` | `scripts/run_evidence_fixtures.py` | five entry stages, complete |
| Path entry visibility | `tests/fixtures/evidence/path-entry-visibility.json` | `scripts/run_evidence_visibility_fixtures.py` | five paths, **see Defect 1** |
| Shared path service | `backend/services/evidence_fixtures.py` | `scripts/run_evidence_paths.py` | five paths resolve through one rule |
| Canonical scenarios | `backend/demo_data/scenarios/` | `scripts/run_scenarios.py` | nine scenarios |
| Professional review | `tests/fixtures/professional_review/` | `test_professional_review_scenarios.py` | four review conditions |
| Presentation | `tests/fixtures/presentation/` | pytest | per-card demonstrations |

Evidence state and source rules have one definition, in
`backend/domain/evidence.py`. The five entry stages are separate from the
conflict state, which is registered but is not an entry. No path carries a
private evidence model; a repository-wide sweep enforces it.

## Path compatibility

Two columns, deliberately. **Defect 1 is open**, so the path-entry fixtures are
not anchored to the scenarios they name, and presenting only the fixture values
would describe evidence the runtime does not hold.

| Path | Scenario | Canonical scenario holds | Path entry declares |
| --- | --- | --- | --- |
| fast | AT-01-clear-motor | 0 records, `not_started` | 1 record, `received` |
| professional_review | AT-02-coverage-ambiguity | 0 records, `not_started` | 2 records, `unofficial` |
| urgent | AT-04-urgent | 0 records, `not_started` | 1 record, `received` |
| human_request | AT-05-human-request | 0 records, `not_started` | 1 record, `received` |
| pending_evidence | AT-06-pending-evidence | 3 records, `pending_generation` | 1 record, `pending_generation` |

**A Week 4 consumer should read the left pair, not the right.** The scenario
column is what a seeded claim actually contains; the entry column is what the
visibility fixture asserts about a set that is not in the runtime.

The two agree on nothing except the pending-evidence state, and even there the
record counts differ. That is Defect 1, stated as a table rather than as prose.

All five entries resolve through the one service and the one domain rule, so the
fixtures are internally consistent — they are just not anchored to the
scenarios.

## Open blockers, with owners

Nothing below is fixed by this document. Each is reproducible.

| Blocker | Owner | Where | Impact on Week 4 |
| --- | --- | --- | --- |
| **Defect 1** — path entries declare evidence that exists in no scenario; four of five scenarios hold no evidence at all | `bdfa123` | `docs/day4-evidence-visibility-defects.md` | path visibility fixtures do not describe the runtime; a Week 4 consumer reading them would build against invented data |
| **Defect 2** — claimant evidence list returns records the claimant never supplied | `liyang6620`, `bdfa123` | same | a claimant-facing visibility gap. `default_handoff_visibility()` already implements the rule; the claimant endpoint does not apply it |
| Agent behaviour layer not started | `Ysoseri1224` | issues #101, #105, #111, #116, #121, #122, #131, #132 | conversation, intent, and authority have no implementation; the Agent integration point cannot be specified for Week 4 |
| API and AWS integration inputs | `liyang6620` | Issue #150, the other half | this document's AWS rows are runtime-reported status only, not a confirmed capability list |
| `persistence` and `agent` report `not_configured` although both are injectable | unassigned | `/health/ready` | a readiness reporting gap, not a missing seam: neither port exposes `connection_status()`, so the endpoint describes six of eight boundaries honestly and hardcodes the other two |

## Day 5 validation status

All nine other Day 5 cards are open. Where a card is split, the half that is
done is named so the remainder is visible rather than implied.

**None of the `bdfa123` halves below has merged.** Every one is an open pull
request under review, so "done" here means written and passing its gate, not
accepted. Review state changes faster than this document, so treat the PR
itself as authoritative and this table as a map of who owes what.

| Card | Done | Outstanding |
| --- | --- | --- |
| #141 clear-claim path | fact source and confirmation state (`bdfa123`, PR #200 — **in review**) | claimant and Agent path, next step (`Ysoseri1224`) |
| #142 claim-creation APIs | repository and revision check (`jxu316-arch`, merged) | API, routing, AWS adapter (`liyang6620`) |
| #143 pending-evidence path | — | both halves (`LLL263`, `Ysoseri1224`) |
| #144 session and evidence | both halves (`jxu316-arch` merged; `bdfa123` PR #197) | closes when PR #197 merges |
| #145 staff handoff experience | — | both halves (`LLL263`, `Ysoseri1224`) |
| #146 handoff APIs and fallback | evidence handoff packet (`bdfa123`, PR #198) | API, priority, retry demonstration (`liyang6620`) |
| #147 adapters and review records | mappings and review records (`jxu316-arch`, merged) | API and AWS adapter boundary (`liyang6620`) |
| #148 authority and visibility | ambiguity, conflict, visibility fixtures (`bdfa123`, PR #199) | Agent authority (`Ysoseri1224`), staff review actions (`LLL263`) |
| #149 staff actions and revisions | revision and persistence (`jxu316-arch`, merged) | staff assignment, review, resolution (`LLL263`) |
| #150 this card | evidence, fixture, path inputs (`bdfa123`, this document) | API and AWS inputs (`liyang6620`) |

## What Week 4 can rely on

- Every external boundary is behind a replaceable port with a documented
  fallback, and reports its real status at runtime.
- Evidence state and source rules have one definition, enforced repository-wide.
- Persistence uses one optimistic-concurrency token, `WorkingClaim.revision`.
- Retrieval never fabricates a finding; an unavailable provider carries
  limitations only.
- Claimant-visible and internal data are separated at field level throughout.

## What Week 4 cannot rely on

- Any AWS capability. All three remain `pending_confirmation`.
- Record-level evidence visibility to the claimant. Defect 2 is open.
- The path-entry visibility fixtures as a description of runtime evidence.
  Defect 1 is open.
- The Agent behaviour layer. It does not exist yet.
- Nine of ten Day 5 validation cards.
