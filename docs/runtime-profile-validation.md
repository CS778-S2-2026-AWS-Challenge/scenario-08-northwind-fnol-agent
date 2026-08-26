# Runtime Profile Validation Record

## Scope

This record verifies the provider-neutral runtime profiles required by issue #266. It records
actual connectivity and temporary-container results observed on 26 August 2026, plus commands
another contributor can repeat. It does not promote an incomplete profile or claim production
deployment, AWS access, Cloudflare access, or a complete MongoDB runtime.

The validation branch was synchronized with `main@17f059d8` before the checks below. The temporary
containers use one image built from the final reviewed branch head; the pull-request evidence names
that exact head after the repository quality gate passes.

## Results

| Profile example | Classification | Actual result | Bounded limitation |
| --- | --- | --- | --- |
| `fixture` | `verified` | Preflight ready; temporary container became healthy as non-root user `northwind`; liveness and readiness returned HTTP 200 | Deterministic synthetic data only; readiness remains degraded while the Agent is not configured |
| `local-minio` | `verified` | Preflight ready against the packaged healthy MinIO service; temporary container became healthy; FastAPI upload, checksum verification, claimant-safe metadata read, readiness, and bounded object cleanup passed | Fixture data bundle with explicit S3-compatible evidence storage, not a complete independent data profile |
| `mongodb` | `partial` | MongoDB connection primitives and bounded probe exist; the configured Atlas probe was unavailable during this run; container exited before serving because the complete bundle is unverified | Persistence alone cannot provide evidence, policy/history, or knowledge capabilities and is not selected at runtime |
| `cloudflare` | `unavailable` | Preflight refused and the temporary container exited before serving | Provider services, bindings, schema, and credentials are unconfirmed |
| `aws` | `unavailable` | Preflight refused and the temporary container exited before serving | Services, permissions, schema, region, credentials, and deployment target are unconfirmed |

The three incomplete candidate containers exited with code 1 while importing the application.
Their bounded errors named only missing or unverified capabilities. They did not listen on a port,
construct fixture persistence as fallback, or access an unselected provider.

## Repeatable Classification

With the repository Python environment active, run:

```powershell
py -3.12 scripts/validate_runtime_profiles.py
```

This verifies fixture startup and fail-closed refusal for MongoDB, Cloudflare, and AWS. It does not
claim local service connectivity. To require a healthy local MinIO service and optionally record a
bounded MongoDB connectivity result, use:

```powershell
docker compose up -d minio
py -3.12 scripts/validate_runtime_profiles.py `
  --minio-endpoint http://localhost:9000 `
  --probe-mongodb
```

`--probe-mongodb` reads `NORTHWIND_MONGODB_*` only from process configuration and performs only an
administrative `ping`. It does not construct `MongoDBRepository`, create indexes, or write provider
state. The command prints `verified`, `unavailable`, or `not_checked`; it never prints the URI,
credentials, database name, collection name, or provider exception. A successful connectivity
probe still leaves the MongoDB profile `partial` until every required runtime capability passes the
shared contracts.

## Local MinIO Contract Check

After MinIO is healthy, use process-local development settings from
`docs/minio-object-storage.md` and run:

```powershell
py -3.12 scripts/run_minio_fastapi_smoke.py
```

The smoke creates only a synthetic claim and evidence object. It removes the staging and final
objects under its generated claim/evidence prefix in a `finally` block. It never clears the shared
bucket or prints credentials and object keys.

## Temporary Container Check

Build the one provider-neutral image and start the verified fixture profile:

```powershell
docker build -t northwind-fnol-backend:runtime-validation .
docker run -d --name northwind-runtime-validation-fixture `
  --env-file deploy/runtime/fixture.env.example `
  -p 127.0.0.1:18002:8000 `
  northwind-fnol-backend:runtime-validation
Invoke-RestMethod http://127.0.0.1:18002/health/live
Invoke-RestMethod http://127.0.0.1:18002/health/ready
docker inspect northwind-runtime-validation-fixture `
  --format "user={{.Config.User}} health={{.State.Health.Status}}"
docker rm -f northwind-runtime-validation-fixture
```

For local MinIO in Docker, attach the backend to the compose network so the example endpoint
`http://minio:9000` is process-accessible. Use a unique container name and host port. Candidate
MongoDB, Cloudflare, and AWS examples are expected to exit non-zero before serving; that refusal is
the verified behaviour until their complete bundles exist.

## Validation Cleanup

All five temporary backend containers created for this record were removed. The failed duplicate
MinIO compose attempt created in the isolated validation worktree was also removed with its empty
network and empty volume. The pre-existing healthy project MinIO service and its data were left
untouched. The local validation image remains available for follow-up issue #265.
