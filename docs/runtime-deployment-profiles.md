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
| `deploy/runtime/local-mvp.env.example` | Ready when local MongoDB, MinIO, and the governed indexes are healthy | MongoDB persistence, MinIO evidence/knowledge, and explicitly synthetic policy/history |
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
docker compose up -d mongodb mongo-init minio minio-init
py -3.12 scripts/check_runtime_profile.py deploy/runtime/local-mvp.env.example --expect ready
py -3.12 scripts/check_runtime_profile.py deploy/runtime/mongodb.env.example --expect refused
py -3.12 scripts/check_runtime_profile.py deploy/runtime/cloudflare.env.example --expect refused
py -3.12 scripts/check_runtime_profile.py deploy/runtime/aws.env.example --expect refused
```

The local MVP command initialises a transaction-capable single-node MongoDB replica set and creates
the two MinIO buckets without clearing either volume. The governed source and index objects must
already exist in `northwind-knowledge`; missing or invalid ingestion state refuses startup. Run
`py -3.12 scripts/run_local_mvp_smoke.py` to verify API writes, revision conflicts, protected
evidence bytes, staff projection, knowledge retrieval, and recovery through a newly constructed
application instance.

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

The `local_mvp` profile is a bounded development composition, not promotion of the provider-specific
`mongodb` profile. Policy and claim-history lookups remain labelled `using_fixture`, and the Agent
remains controlled until its separately owned model proposal contract is delivered. AWS,
Cloudflare, and the complete MongoDB provider profile remain unavailable rather than speculative.
