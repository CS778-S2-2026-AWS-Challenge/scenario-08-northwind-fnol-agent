# Issue #371: RAG and Structured-Query Acceptance Evidence

## Scope

This record verifies the minimum RAG and structured-query interfaces already present on the
current `main` baseline. It packages acceptance evidence for #371 without reimplementing the
query routes delivered by earlier work.

The verified interfaces are:

- `POST /internal/v1/knowledge/search` for governed knowledge retrieval;
- `POST /internal/v1/policy/search` for provider-neutral policy facts;
- `POST /internal/v1/claim-history/search` for purpose-limited claim history.

This record does not claim vector search, Atlas Search, a live Northwind provider, or automatic
Agent-to-RAG tool orchestration. Those remain separate integration work.

## Baseline and validation

- Baseline: `origin/main` at `a8eb3c661d03d3a2dfe2cf504cdbb55bd2ecbff2`.
- Focused contract validation:

  ```text
  py -3.12 -m pytest tests/test_knowledge_search_api.py tests/test_retrieval_api.py tests/test_knowledge_retrieval.py -q --basetemp=.pytest-371-cr
  32 passed in 1.84s
  ```

- Static validation:

  ```text
  py -3.12 -m ruff check <affected source and tests>
  All checks passed!
  py -3.12 -m ruff format --check <affected source and tests>
  7 files already formatted
  py -3.12 -m mypy <affected source files>
  Success: no issues found in 5 source files
  ```

## Acceptance mapping

### Named outcome is observable

The API tests observe successful evidence responses for all three interfaces, including exact
citations for RAG and source/provenance for policy and claim-history results. They also observe
empty and unavailable responses without fabricated facts or citations.

Evidence: `tests/test_knowledge_search_api.py` and `tests/test_retrieval_api.py`.

### Claim Context and visibility compatibility

The retrieval routes require the integration principal. Structured policy and claim-history
lookups require a known claim and persist only provider-neutral retrieval records. History access
is restricted to the `relevant_history_review` purpose. Provider-only conclusions, fraud labels,
internal notes, and other staff-only signals are not returned through the response contract.

Evidence: `tests/test_knowledge_search_api.py`, `tests/test_retrieval_api.py`, and the retrieval
models in `backend/domain/retrieval.py`.

### No unverified provider capability is represented as complete

Provider outages are returned as `unavailable`; missing records are returned as `no_evidence`;
ambiguous policy evidence remains an explicit review signal. The response never converts an
unavailable or absent provider result into facts or a coverage/fraud conclusion.

Evidence: `test_knowledge_search_reports_empty_and_unavailable_without_inventing_results`,
`test_unavailable_provider_reports_the_limitation_and_stores_nothing`,
`test_unknown_reference_is_no_evidence_rather_than_a_negative_finding`, and
`test_history_retrieval_reports_outage_and_missing_records_without_inventing_facts`.

## Handoff to follow-up work

This evidence enables the independent review in #373. It intentionally leaves Agent tool wiring,
provider switching, Control Plane configuration, and real external-provider verification to their
own issues and dependencies.
