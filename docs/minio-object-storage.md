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
`http://localhost:9001`. The repeatable smoke command below creates the
`northwind-evidence` bucket when it is absent. The default values in `.env.example`
are synthetic local credentials only.

## Environment contract

| Variable | Meaning | Example |
| --- | --- | --- |
| `NORTHWIND_OBJECT_STORAGE_ADAPTER` | Explicit object-store adapter selection | `s3_compatible` |
| `NORTHWIND_OBJECT_STORAGE_ENDPOINT` | S3-compatible HTTP(S) endpoint | `http://localhost:9000` |
| `NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID` | Runtime access key | `minioadmin` |
| `NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY` | Runtime secret | `minioadmin` |
| `NORTHWIND_OBJECT_STORAGE_BUCKET` | Bucket for protected evidence bytes | `northwind-evidence` |
| `NORTHWIND_OBJECT_STORAGE_REGION` | Signing region | `us-east-1` |
| `NORTHWIND_OBJECT_STORAGE_PRESIGN_EXPIRY_SECONDS` | Signed PUT lifetime | `900` |

The adapter requires endpoint, access key, and secret at runtime. Real credential values
are not stored in source control, logs, domain records, or configuration representations.
The secret access key is never returned by the API; the access-key identity can appear
only inside the short-lived SigV4 capability described below. Endpoint URLs containing
embedded user-info credentials are rejected; credentials have one controlled environment
source.

The default adapter is `fixture`. Endpoint or credential variables alone do not switch
the running application. Selecting `s3_compatible` is explicit and fails startup when
the required connection values are incomplete; it never falls back to fixture storage.
This object-store selection does not enable the MongoDB, Cloudflare, or AWS data profile.

For a local PowerShell process:

```powershell
$env:DATA_RUNTIME_PROFILE = 'fixture'
$env:NORTHWIND_OBJECT_STORAGE_ADAPTER = 's3_compatible'
$env:NORTHWIND_OBJECT_STORAGE_ENDPOINT = 'http://localhost:9000'
$env:NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID = 'minioadmin'
$env:NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY = 'minioadmin'
$env:NORTHWIND_OBJECT_STORAGE_BUCKET = 'northwind-evidence'
```

## Object contract

New uploads use an adapter-owned staging key:

```text
claims/{claim_id}/evidence/{evidence_id}/staging
```

The signed PUT target requires the declared media type and carries metadata for
`claim-id`, `evidence-id`, `media-type`, and `expected-size`. Completion calls
`get_object`, computes SHA-256 over the staged bytes, and accepts the object only when
its checksum, content type, byte length, and claim/evidence metadata match the
provider-neutral request. It then copies and re-verifies those bytes under a checksum-bound
`finalised` key and deletes staging. Reusing the original PUT can only recreate staging;
it cannot replace the object referenced by an accepted Evidence record. The domain stores
the returned protected reference, verified
checksum, and safe `s3_compatible_evidence_storage` transition source; it never exposes
the bucket, object key, or raw provider response to a claimant.

The short-lived upload capability is the deliberate exception to storage-detail hiding:
an S3 SigV4 URL necessarily contains bucket/addressing information, the staging path, and
the access-key identity. It never contains the secret access key. Staging and final keys
are not returned by persistent Claim or Evidence projections. An idempotent retry after
capability expiry receives a newly signed target for the same Evidence and Claim revision.

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

## FastAPI verification

With MinIO running and the environment above set, execute:

```powershell
py -3.12 scripts/run_minio_fastapi_smoke.py
```

The check creates the local bucket when necessary, creates one synthetic Claim through
FastAPI, requests a signed upload target, uploads the object, completes checksum and
metadata verification through the FastAPI evidence route, reads the claimant-safe
evidence record, and checks readiness. It exits non-zero on configuration, upload,
stored-object, persistence, or health failure and prints no credentials or object keys.
The script removes both staging and final objects for its own synthetic Evidence in a
`finally` block, including after a failed check.

## Current limitation

The fixture profile may use configured MinIO while retaining fixture transactional,
policy, and knowledge adapters. The explicit `local_mvp` profile instead requires
verified MongoDB persistence and configured MinIO evidence bytes while retaining
clearly labelled fixture policy/history and knowledge capabilities. This development
composition does not enable or make production claims for the complete MongoDB profile.

The demo reset endpoint intentionally returns `DEMO_RESET_UNAVAILABLE` while MinIO is
selected. It does not clear a whole shared bucket. The smoke command provides bounded
cleanup for its own generated object prefix.

This smoke uses Python HTTP clients. It verifies FastAPI-to-MinIO composition and the
signed PUT contract, but it is not a claimant-browser or CORS end-to-end test.
