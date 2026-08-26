# Filtered RAG Retrieval

## Scope

The MVP retriever reads immutable indexed chunks from the S3-compatible knowledge bucket. It
requires exact jurisdiction, visibility, authority, version, insurer, product, and effective-time
scope before ranking. It returns citable source chunks, not a coverage decision or a
customer-specific policy fact.

The document catalogue is derived from the same repository-controlled publication manifest used
by ingestion. Retrieval filters that catalogue before any indexed object is read, supports more
than one approved document in the same product/version scope, and rejects indexed chunks whose
identity, governed metadata, or checksum no longer matches the approved source record.

The deterministic keyword ranker is an MVP retrieval implementation. It does not claim vector or
semantic-search capability. Customer policy schedules remain structured records and must be
queried through the authorised policy boundary.

## Internal API

`POST /internal/v1/knowledge/search` requires the integration-service credential. A successful
result retains the exact document ID, chunk ID, section path, source URI, version, checksum, and
source text. Empty, expired, mismatched, and unavailable searches return no invented evidence and
include a limitation.

## Repeatable local verification

After the issue #246 ingestion output exists in MinIO, provide the protected S3-compatible settings
through the process environment and run the evaluator against an anonymous synthetic evaluation
file:

```powershell
py -3.12 scripts/verify_local_rag.py path/to/rag-evaluation-cases.json
```

Run the focused contract tests with:

```powershell
py -3.12 -m pytest tests/test_knowledge_ingestion.py `
  tests/test_knowledge_retrieval.py tests/test_knowledge_search_api.py -q
```

The evaluator checks expected citation IDs for applicable examples and expects no result for
wrong-product, wrong-insurer, expired, missing-version, and prompt-injection cases. Provider and
malformed-index failures are normalised at the retrieval boundary rather than exposed to clients.
The focused automated tests are repository-contained and provide the repeatable #255 acceptance
check; the real MinIO upload-to-citation run is recorded separately under #265.

## Runtime boundary

The retriever remains behind the provider-neutral `KnowledgeRetriever` port. Runtime-profile
composition is delivered and validated separately; this retrieval slice does not promote MongoDB,
MinIO, or another complete deployment profile by itself. Structured customer policy and
claim-history lookups remain separate authorised capabilities.
