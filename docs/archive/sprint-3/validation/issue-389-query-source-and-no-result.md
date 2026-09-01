# Issue #389 query source and no-result validation

This validation record closes the Sprint 3 Week 5 Day 2 query-source outcome on the current
repository baseline. It verifies the existing RAG, structured policy, and claim-history interfaces
without duplicating their implementation or claiming a provider capability that is not verified.

## Scope

The validation covers three separate query boundaries:

- RAG returns citable document and chunk provenance after applicability filtering.
- Policy and claim-history queries return mapped facts with provider-neutral source metadata.
- Empty, unavailable, timeout, malformed, expired, or inapplicable results remain explicit
  limitations and never become invented evidence or conclusions.

RAG wording remains separate from structured customer policy and claim-history records. A fixture
result remains labelled as fixture evidence; this record does not promote MongoDB, MinIO, AWS, or
another provider profile.

## Acceptance mapping

| Issue #389 outcome | Evidence | Result |
| --- | --- | --- |
| Query results project their source | `tests/test_knowledge_search_api.py` preserves document ID, chunk ID, section path, source URI, version, checksum, and text; `tests/test_retrieval_api.py` checks structured source system, reference, and retrieval time. | Pass |
| No-result responses are explicit | Knowledge search returns `no_evidence` with empty results and a limitation; unknown policy/history references return `no_evidence` with `facts: null` and no persisted retrieval record. | Pass |
| Provider failures are explicit and safe | RAG, policy, and history unavailable/timeout paths return `unavailable` with a limitation, no invented facts, and no retrieval record. | Pass |
| Visibility and authority boundaries remain intact | Integration-service authentication is required; RAG filters jurisdiction, visibility, authority, insurer, product, version, and effective time before ranking; structured adapters discard provider-only conclusions. | Pass |
| Results are repeatable on the current baseline | The focused command below passes against `origin/main` commit `58d96446d4f36ef49ad9afbffe2ff746fa55b81b`. | Pass |

## Reproduction

Run the focused query-source and failure-path suite from the repository root:

```powershell
py -3.12 -m pytest tests/test_knowledge_ingestion.py `
  tests/test_knowledge_retrieval.py tests/test_knowledge_search_api.py `
  tests/test_retrieval_api.py -q --basetemp .pytest-tmp-389
```

The suite verifies citation projection, metadata filtering, no-evidence handling, unavailable
provider handling, timeout limitations, malformed-index handling, structured policy/history source
mapping, integration authorization, and the rule that failed lookups do not persist invented
retrieval evidence.

## Limitations

The implementation uses the repository's provider-neutral ports and controlled fixture adapters for
repeatable tests. This evidence does not claim live Northwind policy/history access, vector search,
MongoDB persistence, MinIO availability, AWS access, or production data residency.
