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

The ingestion record binds the document and version to both the source checksum and a deterministic
fingerprint of every governed source field. Repeating an import returns `unchanged` only when the
bytes, governed metadata, and code-controlled ingestion pipeline identity are identical, and writes
no duplicate objects. Different bytes or
changed provenance, applicability, effective dates, authority, or visibility cannot replace an
existing document version. A changed chunker/index pipeline also cannot silently reuse an older
derived artifact; controlled re-publication or rebuild is required.

## Run

The repository-controlled `config/knowledge-sources.json` manifest is the approval authority. Each
entry binds document ID and version to its source key, URI, scope metadata, publication status, and
required SHA-256 checksum. The manifest is also a validated trust boundary: the current slice
accepts only `.md` source keys below the `knowledge/` namespace (excluding generated
`knowledge/indexed/` objects), supported controlled source URIs, explicit jurisdiction, authority
and visibility, valid effective periods, and canonical SHA-256 integrity metadata. Synthetic
product-policy entries additionally require insurer and product applicability. Invalid entries
fail before any object-store read or indexed-object write. A request supplies only the controlled
identity:

```json
{"document_id": "nw-policy-motor-standard-mvp-2026-1", "version": "MVP-2026.1"}
```

The CLI resolves every authoritative field from the manifest. Extra caller-supplied metadata is
rejected, so a request cannot register, modify, or promote a source. Supply MinIO or S3-compatible
connection values through the existing protected
environment boundary, then run:

```powershell
py -3.12 scripts/ingest_knowledge_source.py path/to/ingestion-request.json
```

The knowledge bucket defaults to `northwind-knowledge` and may be overridden with
`NORTHWIND_KNOWLEDGE_BUCKET`. Draft or withdrawn sources, absent objects, checksum mismatches,
unknown document versions, request metadata that differs from the manifest, invalid UTF-8,
duplicate section identifiers, missing versions, and attempted mutation of an existing version
fail explicitly.

Source text is always untrusted document content. Instruction-looking passages are preserved for
traceability but are never interpreted by ingestion as Agent authority or executable tool requests.

## Current boundary

The generated keyword index is the deterministic MVP ingestion output. Filtered applicability,
ranking, citations, empty-result limitations, and retrieval-provider failure behaviour belong to
issue #255. End-to-end upload, ingestion, retrieval, and citation verification belongs to issue
#265.
