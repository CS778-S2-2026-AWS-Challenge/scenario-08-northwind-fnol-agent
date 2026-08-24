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
- claimant-visible success and failure wording; and
- the exact Claim State fields that may change after success, with no failure mutation.

The current `RouteAssessorRequest` does not contain `claimant_consent_ref`. The scenario
marks that field as `gap_for_issue_252`; this issue does not change the API or simulate
consent that the runtime cannot yet prove. The exact external Challenge Key Feature 2
wording is also absent from the repository, so the scenario records that reference as
`unverified_external_brief` rather than claiming complete challenge-feature coverage.

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
