# MinIO Object-Storage Boundary

## Purpose

This document records the verified local object-storage contract for Sprint 2. It
defines the S3-compatible settings and evidence-object behaviour used by
`MinioEvidenceStorage`. It does not enable the MongoDB runtime profile or claim
that AWS access is configured.

## Local service

Start the packaged MinIO server with Docker from the repository root:

```powershell
docker compose up -d minio
```

The local API is available at `http://localhost:9000` and the MinIO console at
`http://localhost:9001`. Create the `northwind-evidence` bucket in the console
before running an integration check. The default values in `.env.example` are
synthetic local credentials only.

## Environment contract

| Variable | Meaning | Example |
| --- | --- | --- |
| `NORTHWIND_OBJECT_STORAGE_ENDPOINT` | S3-compatible HTTP(S) endpoint | `http://localhost:9000` |
| `NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID` | Runtime access key | `minioadmin` |
| `NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY` | Runtime secret | `minioadmin` |
| `NORTHWIND_OBJECT_STORAGE_BUCKET` | Bucket for protected evidence bytes | `northwind-evidence` |
| `NORTHWIND_OBJECT_STORAGE_REGION` | Signing region | `us-east-1` |
| `NORTHWIND_OBJECT_STORAGE_PRESIGN_EXPIRY_SECONDS` | Signed PUT lifetime | `900` |

The adapter requires endpoint, access key, and secret at runtime. Credentials are
not stored in source control, API responses, logs, domain records, or configuration
representations. Endpoint URLs containing embedded user-info credentials are rejected;
credentials have one controlled environment source.

## Object contract

Evidence bytes are stored under the adapter-owned key:

```text
claims/{claim_id}/evidence/{evidence_id}
```

The signed PUT target requires the declared media type and carries metadata for
`claim-id`, `evidence-id`, `media-type`, and `expected-size`. Completion calls
`get_object`, computes SHA-256 over the stored bytes, and accepts the object only when
its checksum, content type, byte length, and claim/evidence metadata match the
provider-neutral request. The domain stores the returned protected reference, verified
checksum, and safe `s3_compatible_evidence_storage` transition source; it never exposes
the bucket, object key, or raw provider response to a claimant.

The adapter accepts `image/jpeg`, `image/png`, and `application/pdf`, with a
maximum declared size of 10 MiB. Missing objects, metadata mismatches, and size or
type mismatches are treated as upload failures. Network, credentials, and bucket
errors raise `EvidenceStorageUnavailable` so callers can return a retryable
dependency error without rejecting the claimant's file.

## Portability

The adapter uses `boto3`'s S3 API and accepts an arbitrary S3-compatible endpoint.
Moving from local MinIO to AWS S3 changes endpoint, credentials, bucket, and (if
needed) region configuration only. FastAPI routes and domain models do not import
`boto3` or inspect object-store keys. Runtime wiring and end-to-end FastAPI upload
checks are tracked separately by issue #245.

## Current limitation

This boundary is implemented and tested with a deterministic S3 client double. The
MongoDB `DataRuntimeBundle` remains intentionally unselected until its complete
transaction and evidence-storage acceptance criteria are met.
