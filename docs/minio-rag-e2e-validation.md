# MinIO and RAG End-to-End Validation

## Purpose

This check proves the synthetic MVP path from governed policy source upload through ingestion,
retrieval and citation. It also proves empty-result and provider-failure behaviour. It does not
turn policy wording into a customer-specific policy record or claim decision.

Exact excesses, limits, endorsements and insured-item details still come from the authorised
structured Policy Schedule. Claim history and staff decisions still come from their authorised
structured stores. RAG supplies citable wording only.

## Inputs

- Policy source identities, paths and SHA-256 checksums: `config/knowledge-sources.json`
- Minimal ingestion requests: `config/knowledge-ingestion-requests/`
- Anonymous synthetic evaluation: `config/rag-evaluation-cases.json`
- Source Markdown files: `config/knowledge-source-corpus/`

Never commit MinIO credentials or customer records. Before upload, compare every source file hash
with the corresponding manifest checksum.

## Start MinIO and upload sources

Start the repository MinIO service and provide the protected settings in the current shell:

```powershell
docker compose up -d minio
$env:NORTHWIND_OBJECT_STORAGE_ENDPOINT = 'http://localhost:9000'
$env:NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID = '<local access key>'
$env:NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY = '<local secret key>'
$env:NORTHWIND_OBJECT_STORAGE_REGION = 'us-east-1'
$env:NORTHWIND_KNOWLEDGE_BUCKET = 'northwind-knowledge'
```

Upload the source directory. The CLI verifies every checksum before creating the bucket or writing
anything, and resolves all object keys from the manifest:

```powershell
py -3.12 scripts/upload_knowledge_sources.py config/knowledge-source-corpus
```

The source paths are controlled and may not be replaced by caller-provided metadata.

## Ingest and verify

Run all three requests:

```powershell
py -3.12 scripts/ingest_knowledge_source.py config/knowledge-ingestion-requests/motor.json
py -3.12 scripts/ingest_knowledge_source.py config/knowledge-ingestion-requests/home.json
py -3.12 scripts/ingest_knowledge_source.py config/knowledge-ingestion-requests/contents.json
```

The first run reports `indexed`. Run the same commands again; every result must report `unchanged`.
Each document must retain four traceable objects: its raw source plus `chunks.jsonl`,
`keyword-index.json`, and `ingestion.json`. The ingestion record must bind the document ID, version,
source key, source checksum, chunk checksum, governed metadata fingerprint and pipeline identity.

Run citation and empty-result checks:

```powershell
py -3.12 scripts/verify_local_rag.py config/rag-evaluation-cases.json
```

All cases must pass. Each case declares a `retrieval_limit`; every `expected_citations` entry must
appear and every additional top-N result must be explicitly listed in `allowed_citations`. The
verifier rejects undeclared extras, duplicate required/allowed entries, and malformed lists, while
refusal cases require the declared top five to remain empty. The schedule-boundary cases
intentionally retrieve relevant wording while
validating and reporting the structured fields required before an exact customer-specific answer
is possible. This proves that the evaluation metadata records the RAG/Policy Schedule boundary; it
does not perform a Policy Schedule lookup. The untrusted-query case proves that an instruction-like
query does not retrieve evidence; it does not claim to test instructions embedded in retrieved
document content.

## Provider failure

Run the bounded failure verifier after the successful ingestion and citation checks:

```powershell
py -3.12 scripts/verify_minio_rag_provider_failure.py
```

The verifier refuses non-local or non-default endpoints, runs `docker compose stop minio`, issues
a fixed valid motor search directly through `S3CompatibleKnowledgeRetriever`, and asserts that it
returns no evidence and raises `KnowledgeRetrievalUnavailable` with the stable message
`The knowledge service is unavailable.` A `finally` block runs
`docker compose up -d --wait minio`, including when the assertion fails. The process exits zero
only when the safe failure is observed and MinIO restarts successfully.

## Recorded result

Validated on 2026-08-27 against MinIO
`RELEASE.2025-07-23T15-54-02Z`, manifest version `1.0`, and corpus checksums
`a7e4d478...`, `12406124...`, and `041fd8fb...`:

- 3 governed sources uploaded with manifest-matching SHA-256 checksums;
- 50 chunks indexed (motor 17, home 16, contents 17);
- repeat ingestion returned `unchanged` for all sources;
- 12 MinIO objects remained traceable (3 raw, 9 derived);
- the repository six-case acceptance set passed, including citations and empty results;
- the extended twelve-case synthetic set also passed;
- a stopped MinIO provider produced the normalised unavailable error.

The remote PR quality result is recorded by CircleCI separately from this real-provider check.
