# RAG Source Inventory and External-Service Scenario

## Purpose

This Day 1 contract provides the bounded inputs requested by issue #242. It does not
perform document ingestion, chunking, indexing, or a configured external-service call.
Those implementation responsibilities remain with #246 and #252.

## Candidate RAG Source Inventory

The machine-readable inventory is
[`backend/demo_data/knowledge/source-inventory.json`](../backend/demo_data/knowledge/source-inventory.json).
It records three candidate New Zealand sources:

| Source | Authority | Controlled version | Scope boundary |
| --- | --- | --- | --- |
| [Privacy Act 2020](https://www.legislation.govt.nz/act/public/2020/31/en/latest/) | New Zealand legislation | Latest version as at 1 May 2026 | Privacy obligations; not insurance policy or claim authority |
| [Fair Insurance Code 2020](https://www.icnz.org.nz/wp-content/uploads/2023/01/Fair_Insurance_Code_2020.pdf) | ICNZ industry code | 2020; effective 1 April 2020 | ICNZ member conduct; Northwind membership is unverified |
| [Consumer Protection — Insurance](https://www.consumerprotection.govt.nz/help-product-service/managing-money/insurance) | New Zealand government guidance | Controlled retrieval dated 24 August 2026 | General guidance; not customer policy wording or a coverage decision |

All three records deliberately use `insurer: null`,
`northwind_applicability: unverified`, and `candidate_not_published`. Public or
industry guidance must not be relabelled as Northwind policy. The ingestion owner must
recheck the source version, capture the approved content, calculate its checksum, apply
governed insurer/product applicability, and publish it through the Control Plane before
the runtime retriever can use it.

Section locators distinguish one-based printed document pages from zero-based PDF file
indices. For the Fair Insurance Code, clauses 1-14 span printed pages 3-4 (PDF indices
4-5) and clauses 16-20 are on printed page 10 (PDF index 11). Web or legislation
sections without a stable page locator keep both locator fields empty rather than using
an ambiguous `page` value.

## Claimant-Authorised External-Service Scenario

The machine-readable scenario is
[`tests/fixtures/journeys/AT-10-claimant-authorised-assessor.json`](../tests/fixtures/journeys/AT-10-claimant-authorised-assessor.json).
It extends the existing provider-neutral AT-10 assessor boundary with a contract-only
claimant consent step and records:

- an approved vehicle damage assessor role with no assumed provider;
- the purpose and minimum task-specific input;
- provider-neutral output and lifecycle statuses;
- timeout, unavailable, access-denied, and malformed outcomes;
- idempotent retry expectations and unapproved automatic retry limits;
- a nonterminal `retryable_failure` state for timeout/unavailable and a separate
  `terminal_failure` state for access-denied/malformed outcomes;
- claimant-visible success and failure wording; and
- the exact Claim State fields that may change after success, with no failure mutation.

Consent withdrawal before provider acceptance prevents submission. After acceptance,
the scenario records the withdrawal but does not promise cancellation or recall; that
requires a separately approved provider capability and Northwind policy.

The #252 adapter fixture adds `claimant_consent_ref` to `RouteAssessorRequest` and checks
it against consent held in the shared Working Claim before calling the adapter. The
current fixture accepts consent only from that claim's claimant; authorised-representative
authority is not yet modelled. A retryable provider failure may be invoked again only
while its recorded authority still matches the current Claim revision. If a material
Claim update advances the revision, the stale retry is rejected before another provider
call and a fresh current-revision authority must prepare a new operation. An already
accepted provider result remains recoverable without a second provider call.

The #262 claimant flow records that bounded consent, derives the authorised request from
shared state, and shows provider, shared-data, progress, success, and failure states
without exposing internal references. The exact external Challenge Key Feature 2 wording
is absent from the repository, so the
scenario records that reference as `unverified_external_brief` rather than claiming
complete challenge-feature coverage.

## Repeatable Check

From the repository root, run:

```powershell
python -m pytest tests/test_reference_contracts.py
```

The checks validate strict parsing, unique source identities, authority and Northwind
boundaries, complete source metadata, consent coverage, all four required failure
outcomes, the lifecycle, idempotency expectations, and allowed Claim State changes.

Owner verification on 24 August 2026 recorded `4 passed` for the focused contract
tests. The repository gate also recorded `374 passed`, `91.41%` backend coverage,
`14 passed` repository-policy checks, `24 passed` claimant tests, and successful format,
lint, type, and claimant build checks.

## Claimant Experience Repeatable Check

The #262 claimant flow can be repeated from the repository root with:

```powershell
python -m pytest tests/test_claimant_external_service.py tests/test_integrations.py
npm test --prefix customer -- src/App.test.jsx
```

The backend checks prove that the action is absent before the controlled created-motor state,
consent is bounded and idempotent, claimant projections exclude raw consent references, current
Northwind authority is created, provider failure preserves the consented revision, and an
unchanged retry succeeds once without rewriting its authority record. Failure injection also
checks that consent cannot survive without its idempotency result and that a durable provider
success is restored when the public response write fails. A separate provider-acceptance/Claim-
CAS race check proves that the identical claimant request can reconcile the already accepted
operation without a second provider task, while an unrelated stale request remains rejected.
The claimant tests exercise the
consent-required, permission and submission progress, assigned success, retryable failure,
explicit retry, authoritative-result recovery, and claim-scoped interaction states.

For a visible check, start the backend and claimant client, complete a synthetic motor report
with a confirmed incident location, and create the claim. Verify that the assessor card appears
only then, names the controlled fixture provider, lists the four shared-data groups, and keeps
the request button disabled until permission is checked. Submit the request and verify the
assigned or queued result, next step, timing when known, and fixture limitation. Repeat at
1440 x 900 and 390 x 844; the 24 August 2026 owner run completed the assigned fixture path at
both sizes with no horizontal overflow or browser-console error.

The complete #262 branch gate on 24 August 2026 recorded `389 passed`, `90.77%`
backend coverage, `14 passed` repository-policy checks, `26 passed` claimant tests,
and successful format, lint, type, and claimant production-build checks.
