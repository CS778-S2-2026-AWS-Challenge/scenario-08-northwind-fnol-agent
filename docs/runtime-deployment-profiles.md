# Runtime Deployment Profiles

## Purpose

The backend uses one container image and selects runtime behaviour only through process
environment. `DATA_RUNTIME_PROFILE` selects exactly one complete data bundle. The separate
`NORTHWIND_OBJECT_STORAGE_ADAPTER` setting may select the already verified S3-compatible evidence
adapter only where the data profile contract permits it; endpoint values alone never activate an
adapter.

## Environment examples

| Example | Current startup result | Meaning |
| --- | --- | --- |
| `deploy/runtime/fixture.env.example` | Ready | Complete deterministic fixture bundle |
| `deploy/runtime/local-minio.env.example` | Ready when packaged MinIO is healthy | Fixture data with the explicit verified MinIO evidence adapter |
| `deploy/runtime/mongodb.env.example` | Refused | Connection primitives exist, but the complete MongoDB bundle is not verified |
| `deploy/runtime/cloudflare.env.example` | Refused | Provider services and bindings remain unconfirmed |
| `deploy/runtime/aws.env.example` | Refused | AWS services, permissions, and credentials remain unconfirmed |

The local credentials in the MinIO examples are published development defaults, not deployment
secrets. Atlas, cloud, and production credentials must be supplied through protected process
configuration and must never be committed in an environment file.

## Startup preflight

Inspect one example before serving requests:

```powershell
py -3.12 scripts/check_runtime_profile.py deploy/runtime/fixture.env.example --expect ready
py -3.12 scripts/check_runtime_profile.py deploy/runtime/mongodb.env.example --expect refused
py -3.12 scripts/check_runtime_profile.py deploy/runtime/cloudflare.env.example --expect refused
py -3.12 scripts/check_runtime_profile.py deploy/runtime/aws.env.example --expect refused
```

For local MinIO, start `docker compose up -d minio`, use a process-accessible endpoint when the
backend runs outside Docker, and run the preflight without `--expect` to require a real successful
connection. A refused result exits non-zero and names only the bounded missing capability or
configuration condition.

## Container image

Build the same backend image for every profile:

```powershell
docker build -t northwind-fnol-backend:local .
docker run --rm --env-file deploy/runtime/fixture.env.example -p 8000:8000 `
  northwind-fnol-backend:local
```

There are no provider-specific build arguments or images. Selecting an incomplete MongoDB,
Cloudflare, or AWS profile fails while importing the application, before Uvicorn serves a request.
No candidate profile falls through to fixture services.

## Verification boundary

This issue supplies repeatable examples and startup checks. Actual connectivity and temporary
deployment evidence belongs to #266. MongoDB/MinIO composition is not promoted until the complete
bundle passes the shared persistence, visibility, idempotency, evidence, policy/history, and RAG
contracts. AWS and Cloudflare remain unavailable rather than speculative.
