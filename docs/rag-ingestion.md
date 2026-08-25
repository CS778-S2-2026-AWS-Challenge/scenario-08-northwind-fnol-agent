# RAG Knowledge Ingestion

## Scope

The first ingestion pipeline imports approved UTF-8 policy or guidance documents from an
S3-compatible knowledge bucket. It validates source identity and version, performs section-aware
Markdown chunking, preserves the metadata required by `KnowledgeChunk`, creates a deterministic
keyword index, and records immutable ingestion state.

This pipeline does not ingest customer policy schedules, Claim State, messages, evidence, or staff
decisions. It does not connect retrieved content to the Agent and does not authorise coverage,
liability, fraud, approval, rejection, or payment decisions.

## Object layout

Raw approved sources remain under their governed source keys. Generated objects use:

```text
knowledge/indexed/{document_id}/{version}/chunks.jsonl
knowledge/indexed/{document_id}/{version}/keyword-index.json
knowledge/indexed/{document_id}/{version}/ingestion.json
```

The ingestion record binds the document and version to the source checksum. Repeating an import of
identical bytes returns `unchanged` and writes no duplicate objects. Different bytes cannot replace
an existing document version.

## Run

Create a non-secret request JSON containing the `KnowledgeSource` fields, including an exact
`source_key`, non-empty `version`, `publication_status: "approved"`, and optionally the expected
SHA-256 checksum. Supply MinIO or S3-compatible connection values through the existing protected
environment boundary, then run:

```powershell
py -3.12 scripts/ingest_knowledge_source.py path/to/ingestion-request.json
```

The knowledge bucket defaults to `northwind-knowledge` and may be overridden with
`NORTHWIND_KNOWLEDGE_BUCKET`. Draft or withdrawn sources, absent objects, checksum mismatches,
invalid UTF-8, duplicate section identifiers, missing versions, and attempted mutation of an
existing version fail explicitly.

## Current boundary

The generated keyword index is the deterministic MVP ingestion output. Filtered applicability,
ranking, citations, empty-result limitations, and retrieval-provider failure behaviour belong to
issue #255. End-to-end upload, ingestion, retrieval, and citation verification belongs to issue
#265.
