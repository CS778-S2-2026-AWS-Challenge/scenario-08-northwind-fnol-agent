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
- Source Markdown files: the team-controlled synthetic corpus whose bytes match the manifest

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
py -3.12 scripts/upload_knowledge_sources.py path/to/approved-policy-markdown
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

All cases must pass. The schedule-boundary cases intentionally retrieve relevant wording while
recording the structured fields required before an exact customer-specific answer is possible.

## Provider failure

Stop only the local MinIO service and issue an otherwise valid motor knowledge search. The
retrieval boundary must raise `KnowledgeRetrievalUnavailable` with the stable message
`The knowledge service is unavailable.` It must not return invented evidence or expose provider
exception details. Restart MinIO immediately after this check.

## Recorded result

Validated on 2026-08-27 against MinIO
`RELEASE.2025-07-23T15-54-02Z` and manifest version `1.0`:

- 3 governed sources uploaded with manifest-matching SHA-256 checksums;
- 50 chunks indexed (motor 17, home 16, contents 17);
- repeat ingestion returned `unchanged` for all sources;
- 12 MinIO objects remained traceable (3 raw, 9 derived);
- the repository six-case acceptance set passed, including citations and empty results;
- the extended twelve-case synthetic set also passed;
- a stopped MinIO provider produced the normalised unavailable error.

The remote PR quality result is recorded by CircleCI separately from this real-provider check.
