# Week 4 compatibility and integration inputs

Issue: #150

Compiled from `main@98715b5ac85447748700d49d093e6ab626fe175c` after the canonical
path-evidence fix in #227.

## Status: Draft / NOT READY

This is a current integration compilation, not a declaration that Week 4 is
ready. Issue #150 depends on the other Day 5 validation cards. Incomplete PRs,
owner checks, provider confirmations, and production-provider gaps remain
visible below and must not be inferred as complete from a green fixture path.

The runtime and canonical fixture rows in this document are guarded by tests.
GitHub issue/PR workflow state is a dated process snapshot; the linked GitHub
items remain authoritative when that state changes.

## Runtime readiness snapshot

The table below mirrors `GET /health/ready` for the default fixture profile.
The test suite requires every runtime check and its current status to appear as
an exact row.

| Check | Current status |
| --- | --- |
| `persistence` | `using_fixture` |
| `evidence_storage` | `using_fixture` |
| `policy` | `using_fixture` |
| `claim_history` | `using_fixture` |
| `knowledge_documents` | `using_fixture` |
| `knowledge_retrieval` | `using_fixture` |
| `agent` | `not_configured` |
| `aws_policy_history` | `pending_confirmation` |
| `claims_service` | `using_fixture` |
| `aws_claims_service` | `pending_confirmation` |
| `handoff_dispatch` | `using_fixture` |
| `aws_evidence_storage` | `pending_confirmation` |

**No AWS capability is confirmed.** The three `aws_*` checks are deliberately
`pending_confirmation`. A fixture-backed implementation proves the repository
contract and degraded behaviour; it is not evidence of a live Northwind/AWS
provider.

`agent=not_configured` is a provider/model-readiness status, not a missing
software seam. `create_app()` injects `AgentTurnProvider` and currently defaults
to `ControlledAgent`.

## Integration points

Every current boundary names its port, current provider, consumer, runtime
status, and readiness key. Where two boundaries share one readiness key, that
limitation is stated rather than hidden.

| Integration point | Port / seam | Provider now | Consumer | Status | Readiness key |
| --- | --- | --- | --- | --- | --- |
| Working-claim persistence | `PersistenceRepository` | `FixtureRepository` through `DataRuntimeBundle` | claim, session, message, evidence, retrieval, review, handoff and staff workflows | `using_fixture` | `persistence` |
| Evidence object storage | `EvidenceStorage` | `MockEvidenceStorage` | upload target and upload-completion paths | `using_fixture` | `evidence_storage` |
| Policy retrieval | `PolicyHistoryAdapter` | `MockPolicyHistoryAdapter` | `POST /internal/v1/policy/search`, retrieval persistence and review signalling | `using_fixture` | `policy` |
| Claim-history retrieval | `PolicyHistoryAdapter` | `MockPolicyHistoryAdapter` | `POST /internal/v1/claim-history/search` | `using_fixture` | `claim_history` |
| Knowledge documents | `KnowledgeDocumentStore` | `FixtureKnowledgeDocumentStore` | governed knowledge runtime on `app.state` | `using_fixture` | `knowledge_documents` |
| Knowledge retrieval | `KnowledgeRetriever` | `FixtureKnowledgeRetriever` | governed knowledge runtime on `app.state`; no claim of a production ranking service | `using_fixture` | `knowledge_retrieval` |
| Agent turns | `AgentTurnProvider` | `ControlledAgent` | claimant conversation path | provider/model not configured | `agent` |
| External claim creation | `ClaimsServiceAdapter` | `MockClaimsServiceAdapter` | controlled claim-creation integration | `using_fixture` | `claims_service` |
| Assessor routing | `AssessorServiceAdapter` | `MockAssessorServiceAdapter` | assessor-routing integration | fixture-backed; shares claim-service readiness reporting | `claims_service` |
| Staff queue dispatch | `HandoffDispatchAdapter` | `MockHandoffDispatchAdapter` | claimant support request and durable handoff notification | `using_fixture` | `handoff_dispatch` |

The data runtime is exclusive: the complete fixture bundle is implemented;
selecting an unsupported non-fixture profile fails startup instead of silently
mixing fixture dependencies into a provider-labelled deployment.

## Fallback and failure behaviour

| Boundary | Failure behaviour | Claim / customer outcome | Current evidence |
| --- | --- | --- | --- |
| Policy / claim-history retrieval | returns `unavailable` with limitations only; no source and no facts are fabricated | claim remains available for safe review/fallback; no retrieval/review record is invented | merged retrieval tests; connected orchestration in #231 pending final local gate/merge |
| Evidence storage | returns retryable dependency failure before evidence persistence | Claim State and evidence collection remain unchanged; retry can use the same contract after recovery | merged storage-boundary regression |
| Handoff dispatch | persists handoff first, then degrades notification to `queued_locally` | staff context is not lost; same-key replay/recovery must not duplicate ownership or advance revision twice | #231 pending final local gate/merge |
| Claim creation | idempotency/revision boundaries reject duplicate or conflicting writes | no duplicate external claim; explicit source/route remain traceable on the fixture path | merged claim-creation journey and repository tests |
| Unsupported data runtime profile | startup raises `RuntimeProfileConfigurationError` | deployment fails closed; no fixture/provider hybrid is assembled | merged runtime-profile contract |

## Canonical five-path evidence compatibility

These rows are derived from `EvidenceFixtureService`, which now resolves the
canonical scenario records classified by `path-entry-visibility.json`. The old
parallel path-evidence catalogue has been removed by #227.

| Business path | Canonical scenario | Evidence state | Records | Claimant-visible | Received | Pending | Needs attention |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `fast` | `AT-01-clear-motor` | `received` | 1 | 1 | 1 | 0 | 0 |
| `professional_review` | `AT-02-coverage-ambiguity` | `inconsistent` | 3 | 3 | 2 | 0 | 1 |
| `urgent` | `AT-04-urgent` | `received` | 1 | 1 | 1 | 0 | 0 |
| `human_request` | `AT-05-human-request` | `received` | 1 | 1 | 1 | 0 | 0 |
| `pending_evidence` | `AT-06-pending-evidence` | `pending_generation` | 3 | 1 | 0 | 3 | 0 |

Independent verification for #227 recorded:

```text
Checked 5 business paths.
No evidence path defects found.
```

The pending-evidence row is intentionally asymmetric: the claimant-visible
police report is separate from an external-agency record and an internal staff
history record. Staff can retain all three while the claimant sees only the
record appropriate to the claimant projection.

## Evidence and fixture inputs

| Family | Source of truth | Verifier / consumer | Current status |
| --- | --- | --- | --- |
| Canonical scenarios | `backend/demo_data/scenarios/` | scenario loader and API/demo tests | canonical record owner |
| Evidence lifecycle | `backend/domain/evidence.py` + `tests/fixtures/evidence/evidence-lifecycle.json` | lifecycle fixture runner/tests | shared state rules |
| Five-path visibility | `tests/fixtures/evidence/path-entry-visibility.json` | `EvidenceFixtureService` + zero-defect path check | canonical-ID classification only |
| Professional review | canonical scenario/retrieval/review fixtures | retrieval, Workbench and presentation tests | sourced/role-safe review path |
| Claim/session/handoff persistence | repository protocols + provider contract tests | API/integration regressions | fixture runtime complete; non-fixture runtime not complete |
| Presentation journeys | `tests/fixtures/presentation/` and journey regressions | focused demonstration tests | evidence only; not a production-provider claim |

## Day 5 closure matrix

Snapshot after #227 merged on 22 August 2026. `Acceptance met` means the
behaviour has direct technical evidence; it does not override an outstanding
review, local-gate, owner-confirmation, or merge requirement.

| Card | Technical state | Remaining closure blocker | Owner / current action |
| --- | --- | --- | --- |
| #141 clear claim | Acceptance met; #223 merged; #200 independent provenance test approved on its prior base | #200 is now behind the post-#227 `main` and needs current-main replay/merge | `bdfa123` / refresh #200 against current main |
| #142 claim creation | Acceptance met on provider-neutral/fixture path | assigned API/routing/AWS current-main confirmation not yet recorded | `liyang6620` / owner check requested |
| #143 pending evidence | Acceptance met | assigned staff-visible pending-status check not yet recorded | `LLL263` / owner check requested |
| #144 session + evidence | **Closed / completed** | None | #227 merged; canonical evidence contract is on `main` |
| #145 staff handoff UX | Acceptance met | staff takeover and claimant-facing status owner confirmations not yet recorded | `LLL263`, `Ysoseri1224` / owner checks requested |
| #146 handoff API/fallback | Acceptance met; #227 merged | #231 is Draft under the new PR policy until exact local gate; API/adapter owner sign-off and merge remain | `liyang6620`; `jxu316-arch` local-gate evidence |
| #147 adapter/review records | Acceptance met for sourced provider-neutral contract | #231 local gate/sign-off/merge; API/AWS owner confirmation; stale Day-5 runbook refreshed in this branch | `liyang6620`, `jxu316-arch` |
| #148 authority/visibility | **Closed / completed** | None | completed before this compilation |
| #149 staff write-back | Acceptance met | #230 is Draft under the new PR policy until exact local gate; Staff Workbench owner review/merge remain | `LLL263`; `jxu316-arch` local-gate evidence |
| #150 integration inputs | **Draft / NOT READY** | other Day-5 closure rules, current-main final gate, API/AWS input confirmation | `bdfa123`, `liyang6620` plus current compiler |

## Provider and deployment blockers

| Blocker | Current truth | Owner / tracking | Why it is not Ready |
| --- | --- | --- | --- |
| AWS policy/history | `pending_confirmation` | `liyang6620` / #150 input confirmation | no verified live provider/configuration is represented by current runtime |
| AWS claims service | `pending_confirmation` | `liyang6620` / #150 input confirmation | fixture source is explicit; live provider is unverified |
| AWS evidence storage | `pending_confirmation` | `liyang6620` / #150 input confirmation | fixture storage contract is tested; live provider is unverified |
| MongoDB runtime | partial adapter foundation in PR #225; #224 remains open | `liyang6620` | real transaction rollback/concurrency, protected evidence bytes, Atlas topology/config and complete `DataRuntimeBundle` composition remain unverified; profile must stay disabled |
| Production Agent/model | `agent=not_configured` with `ControlledAgent` prototype seam | team / future provider decision | controlled behaviour proves authority/conversation contracts, not production-model quality or readiness |
| Northwind production data/services | not supplied/verified in repository | Northwind/AWS/team dependency | no production schema, credentials, service limits or provider ownership facts should be invented |

## What Week 4 can rely on now

- One provider-neutral application composition root and an exclusive fixture
  data runtime that fails closed for unsupported profiles.
- One canonical evidence set per business path, with zero known path anchoring
  defects and explicit claimant/internal visibility classification.
- Optimistic Claim revision and idempotency boundaries across creation,
  persistence, support requests, and staff write-back.
- Fail-closed policy/history retrieval: unavailable data cannot become an
  unsourced policy or fraud conclusion.
- Durable human handoff semantics and role-safe claimant/staff projections in
  the merged contracts; the connected outage regression is pending #231's new
  local-gate requirement before merge.
- Resume/pending-evidence behaviour that allows unrelated safe work to continue
  and does not re-ask confirmed facts.

## What Week 4 cannot claim yet

- A confirmed live AWS policy/history, claims-service, or evidence-storage
  integration.
- A complete MongoDB production runtime or verified Atlas transaction model.
- A production Agent/model provider.
- Closure of #141, #142, #143, #145, #146, #147, or #149 while their explicit
  closure rules above remain outstanding.
- Final #150 Ready status before the current-main full gate and assigned API/AWS
  confirmation are recorded.

## Final #150 Ready gate

Do not mark #150 Ready until all of the following are true:

1. The dependent Day-5 cards satisfy their recorded closure rules.
2. #200 is replayed/merged on the post-#227 main.
3. #230 and #231 record exact-head `./scripts/check.ps1` local PASS results,
   meet the current PR template, receive their assigned owner reviews, and merge.
4. `liyang6620` records the assigned API/AWS integration-input confirmation,
   leaving unavailable provider capabilities explicitly `pending_confirmation`.
5. This document still matches `/health/ready` and `EvidenceFixtureService`.
6. The final current-main branch passes the complete local repository gate,
   GitHub CI, and PR Policy.
