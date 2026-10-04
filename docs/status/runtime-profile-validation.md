# Runtime Profile Validation Record

## Scope

This record verifies the provider-neutral runtime profiles required by issue #266. It records
actual connectivity and temporary-container results observed on 26-28 August 2026, plus commands
another contributor can repeat. It does not promote an incomplete profile or claim production
deployment, AWS access, Cloudflare access, or a complete MongoDB runtime.

## Current-main reconciliation

Reconciled on 2026-09-28 against
`main@fad552f83a6ebae409f2677bed80a8c9899d206c`. The dated classifications and commands below are
historical run evidence and were not rerun by this documentation change.

- The current supported development path composes `local_mvp` with `model_gateway`; PR #977 has
  merged the claimant Runtime v8 model-backed path. Statements below that a named historical run
  used the controlled Agent remain true only for that run.
- The profile selector added in PR #988 can request `model_gateway` without silently falling back,
  but issue #962 still lacks its first recorded model-backed 5/3/2 journey batch.
- Real AWS migration and integration are Sprint 5 work. The historical `aws: unavailable`
  classification remains evidence for the named earlier environment, not a permanent product
  decision.
- The latest successful EC2 application rehearsal is recorded below with its exact application
  commit and date. It supersedes the earlier application-startup failure only for that pinned
  rehearsal; it does not promote the repository `aws` runtime profile or prove the latest
  `origin/main` release.
- Third-party participant behavior is intentionally simulation-backed and is independent of the
  AWS data-profile migration.

The validation branch was synchronized with `main@4c90e2a` before the latest checks below. The temporary
containers use one image built from the final reviewed branch head; the pull-request evidence names
that exact head after the configured remote quality checks pass.

## Initial AWS framework capability validation (2026-10-01)

On 1 October 2026, the school-provided team account was checked through the
AWS console in the Sydney region (`ap-southeast-2`). This validation was
performed against the final framework recorded in
`docs/design/aws-verified-deployment-plan.md` and selected in #1080.

The console session used the school SSO permission set. No credentials,
account identifiers, policyholder data, or secret values were recorded here.
The results below are account-capability evidence only; they do not promote
the repository `aws` runtime profile or prove that the application is
deployed.

| Capability | Classification | Evidence observed | Boundary and next step |
| --- | --- | --- | --- |
| Sydney region and static delivery | `validated` | The bounded private S3-to-CloudFront static path succeeded in `ap-southeast-2`; direct S3 access was denied | CloudFront is static delivery only |
| S3 bucket creation | `validated` | An empty general-purpose bucket was created successfully in Sydney using the console. No objects were uploaded | The empty test bucket is temporary and must be removed after the user confirms cleanup; this proves S3 create permission, not Evidence or Knowledge Base integration |
| S3 existing state | `validated` | Two existing Sydney general-purpose buckets were visible, including the project static-check bucket | Ownership and intended use of existing buckets remain to be confirmed; do not reuse the accelerator access-log bucket for project data |
| EC2 launch surface | `validated` | Sydney had no instances, while the EC2 console exposed `Launch instances` | No instance was launched. A launch would create a persistent cost risk and requires an explicit smallest-size, stop/teardown plan |
| Docker Compose and EC2 application | `unreachable` | Docker and the Compose plugin installed, but the repository MinIO client image could not be pulled; the stack did not start | Backend, MongoDB, MinIO, and the external model gateway therefore remain unverified |
| HTTPS API, CORS, and application journey | `unconfigured` | No browser-safe API origin was configured; claimant, Workbench, and three FNOL paths were not run on EC2 | Requires a successful Compose startup first |
| CloudWatch and budget visibility | `partially validated` | Bounded synthetic monitoring and budget evidence exists | Coverage of a running application is still pending |
| AWS credits | `unavailable` | The Billing and Cost Management Credits page reported no active or remaining credits at the time of checking | The account must not be treated as having a guaranteed course credit. Budgets are alerts, not credit balances; confirm the teaching team's billing arrangement before persistent deployment |
| Repository AWS runtime | `local_only` | The current repository remains on the existing local MongoDB/MinIO and external model-gateway path | No AWS provider or application-data migration was enabled |

### Cost and cleanup boundary

No persistent EC2 application, ECS cluster, ECR repository, DynamoDB table,
CloudWatch application resource, secret, Knowledge Base, or application data
was created during this check. The bounded static delivery and monitoring
checks used synthetic data only. This record does not claim a persistent
application deployment or a data migration.

The only new persistent resource was the empty S3 permission-test bucket
named `nw-fnol-permission-check-20261001`; it contains zero objects. Its
deletion is a separate account mutation and should be performed after the
current user confirms that the evidence has been recorded.

The existing billing view showed an already-existing `$200` budget with usage
above that budget, while the Credits view showed no remaining credits. This
must be treated as a cost warning, not as proof that the team has `$200` of
available free usage.

### Latest successful EC2 application rehearsal (2026-10-02)

The later bounded rehearsal restored the approved test route and deployed the
exact application commit
`f1b897d76dbb3d5d854b6172c7cc49907e3f902a` on a Sydney `t3.small` without an
instance profile. It used synthetic data and the original approved MinIO image
archive. This is the latest successful application evidence; it is distinct
from the initial account-capability check above and was not performed against
the current unreconciled `origin/main` head.

| Capability | Classification | Evidence observed | Boundary |
| --- | --- | --- | --- |
| Compose initialization | `validated` for the pinned rehearsal | Backend, MongoDB, and MinIO became healthy; database, storage, and knowledge initialization completed | The CLI worker required a deployment-only healthcheck override; no worker health endpoint is claimed |
| Backend readiness | `validated` with `degraded` status | HTTP readiness returned 200; persistence and Evidence/knowledge services were available | Existing policy, claim-history, claims-service, and handoff-dispatch services remained fixture-backed |
| External model gateway | `validated` for structured text | A live call returned success with a request ID and used the configured external GPT-4o gateway | This does not prove every modality or a newer release configuration |
| CloudFront application routing | `validated` for the rehearsal | CloudFront served the private static frontend, rejected unauthenticated claims, and denied internal knowledge access | CloudFront to EC2 used the approved HTTP test origin |
| Motor, home, and contents HTTP journeys | `validated` for bounded journeys | Each completed account/session, model turn, signed Evidence upload/completion, support request, staff reply, and claimant readback | Not an external insurer submission or complete browser coverage |
| Claimant browser path | `validated` for bounded coverage | Registration, model reply, and synthetic JPEG upload reached `Ready` | Does not cover every browser route |
| Staff Workbench | `validated` for bounded coverage | Staff login and all three product conversations displayed claimant, model, and staff messages | External-claim submission was not exercised |
| Governed RAG | `validated` against MinIO | Each product returned three citations with document, chunk, version, checksum, and source metadata; missing evidence returned `no_evidence` | This is the MinIO knowledge boundary, not a different provider |
| Restart and recovery | `validated` for bounded recovery | Backend/MinIO restart, MongoDB restart, EC2 reboot, and named-volume restore preserved revision, messages, Evidence checksum, and claim-creation replay | Same-host recovery, not replacement-host disaster recovery |
| Cost guard | `configured` with readback | The validation cost guard and actual-cost thresholds were read back | Email delivery and automatic spending enforcement were not verified |
| Failure handling | `validated` for bounded faults | Deliberate model timeout returned retryable timeout; stopped MinIO returned `unavailable` with zero citations; fixture fallback was refused | The controlled RAG read timeout still collapses to `unavailable` |

This later record supersedes the initial `Docker Compose and EC2 application`
`unreachable` result only for the pinned rehearsal above. The earlier result
remains valid as historical evidence for the initial account check. No
application data migration occurred, and the repository `aws` runtime profile
remains unpromoted until the final frozen release is separately verified.

### Validation commands and evidence limits

The account checks above were performed through the authenticated AWS console,
not through the local CLI. The local environment still has no AWS CLI and no
committed AWS credentials. Therefore no CLI/API command can be reported as
successful for this account, and no browser observation is being presented as
proof of application connectivity.

The next checks for this framework are:

1. resolve the Compose MinIO client image dependency without changing the
   application contract or silently substituting an unreviewed image;
2. start the existing Compose topology and verify Backend health, MongoDB and
   MinIO restart/readback, the external model gateway, and synthetic
   Evidence/RAG paths;
3. configure and verify the HTTPS API origin, reverse proxy, and CORS;
4. run the three FNOL paths and Staff Workbench journey against EC2;
5. record CloudWatch, budget, stop, cleanup, and rollback evidence for the
   resources actually used.

Bedrock, Bedrock Knowledge Bases, DynamoDB, ECS/Fargate, an S3 Evidence
adapter, and MongoDB/MinIO-to-AWS migration are outside this validation.

These checks remain separate from the repository's local runtime-profile
validation and must be recorded with the same evidence classifications.

## Results

| Profile example | Classification | Actual result | Bounded limitation |
| --- | --- | --- | --- |
| `fixture` | `verified` | Preflight ready; temporary container became healthy as non-root user `northwind`; liveness and readiness returned HTTP 200 | Deterministic synthetic data only; readiness remains degraded while the Agent is not configured |
| `local-minio` | `verified` | Preflight ready against the packaged healthy MinIO service; temporary container became healthy; FastAPI upload, checksum verification, claimant-safe metadata read, readiness, and bounded object cleanup passed | Fixture data bundle with explicit S3-compatible evidence storage, not a complete independent data profile |
| `local_mvp` | `verified` | Local MongoDB 8.0 replica set became primary; runtime preflight was ready; developer-only synthetic identity authenticated claimant, staff, and integration requests; claimant and controlled-Agent messages, Claim revision, idempotency records, Evidence metadata, typed Policy/History retrievals, and one staff-only review signal survived application reconstruction; a conflicting retrieval bundle rolled back without a partial record; protected Evidence bytes and governed Motor citations were read from MinIO | Development-only composition; identity, policy, and history remain synthetic, and the Agent remains controlled |
| `mongodb` | `partial` | MongoDB connection primitives and bounded probe exist; the configured Atlas probe was unavailable during this run; container exited before serving because the complete bundle is unverified | Persistence alone cannot provide evidence, policy/history, or knowledge capabilities and is not selected at runtime |
| `cloudflare` | `unavailable` | Preflight refused and the temporary container exited before serving | Provider services, bindings, schema, and credentials are unconfirmed |
| `aws` | `unavailable` | Preflight refused and the temporary container exited before serving | Services, permissions, schema, region, credentials, and deployment target are unconfirmed |

The three incomplete candidate containers exited with code 1 while importing the application.
Their bounded errors named only missing or unverified capabilities. They did not listen on a port,
construct fixture persistence as fallback, or access an unselected provider.

## OpenRouter GPT-4o PDF transport validation

On 2026-09-30, the document transport was checked in an isolated worktree based on
`main@10cdc4f14ff29cc55e077a917f1d1e77a3539273`. The probe used the repository's synthetic contents
purchase receipt, the configured OpenRouter endpoint, and `openai/gpt-4o`. It sent a private Base64
PDF file block with a strict JSON Schema response request.
The provider returned HTTP 200, identified the document type, and confirmed the explicit
simulated-material marker. Usage was 169 input and 15 output tokens. The credential, PDF bytes,
extracted text, storage references, and complete response were not printed or recorded.

This is live provider transport and structured-output evidence for one synthetic PDF. It is not a
claimant journey, a latency distribution, production-data approval, automatic Evidence processing,
or proof of a fixed OpenRouter parser engine. The request omitted explicit parser configuration and
therefore used OpenRouter's documented default PDF-processing selection. Issue #1129 separately owns
automatic dispatch, durable processing state, idempotency, and recovery.

## Week 5 Day 4 cloud boundary revalidation

## Issue #1139 initial-framework validation (historical)

This section records the initial Sydney validation, before the later successful
application rehearsal above. It used the current framework and synthetic data
only. EC2 launch/system checks, Docker installation, Docker Compose
installation, bounded monitoring, and the private S3-to-CloudFront static path
were recorded as evidence.

The application Compose check did not reach Backend startup. The repository's
current `minio/mc` image reference could not be pulled in the checked EC2
environment; temporary image substitutions were attempted only in the EC2
copy and were not committed. Consequently, EC2 Backend liveness/readiness,
MongoDB/MinIO restart readback, external model gateway, RAG, API HTTPS/CORS,
and the full FNOL smoke remained unverified at that earlier checkpoint. These
were historical framework blockers, not local fixture successes. The later
successful pinned rehearsal is recorded above. No application data migration
was executed.

Issue #432 revalidated this boundary on 3 September 2026 against `main@8d4d4e5`. The local
environment exposed no AWS or Cloudflare credential variable names, and the AWS CLI was not
installed. No live cloud request was attempted: there was no approved service binding or local
identity with which to make one. AWS and Cloudflare therefore remain `unavailable`, not verified
or partially complete.

`py -3.12 scripts/validate_runtime_profiles.py` returned `isolation=verified_fail_closed`.
The fixture profile was ready; the incomplete MongoDB, Cloudflare, and AWS profiles all refused
startup with the complete missing-capability list. Local MinIO was unavailable during this run and
`local_mvp` was deliberately not checked, so the run does not supersede their separately recorded
provider-backed results above.

The focused regression also supplies valid Model Gateway settings and conflicting MongoDB,
object-storage, AWS SDK, and Cloudflare SDK settings while selecting `DATA_RUNTIME_PROFILE=aws`.
The process still refuses the AWS data profile before constructing any data adapter, does not
expose a provider endpoint or credential in its result, and restores the caller's environment.
A configured model endpoint is independent evidence and cannot promote an unverified data profile.
Because application construction stops at the data composition root, no repository, API route, or
Claim Context mutation is available before refusal; existing claimant and staff visibility
contracts are therefore unchanged.

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

## Local MVP Contract Check

Start or verify the transaction-capable local services, then run the real runtime smoke:

```powershell
docker compose up -d mongodb mongo-init minio minio-init
py -3.12 scripts/check_runtime_profile.py deploy/runtime/local-mvp.env.example --expect ready
py -3.12 scripts/run_local_mvp_smoke.py
```

The smoke constructs the application twice. The first instance creates a synthetic Claim, stores a
controlled message turn, uploads and verifies Evidence through MinIO, queries the governed Motor
corpus, and exercises typed Policy/History `evidence_found`, Policy `ambiguous`, Policy
`no_evidence`, and History `unavailable` results. It also proves provider-only scoring and notes do
not cross the mapper boundary. The second instance checks durable idempotent replay,
Claim/session/message/Evidence and retrieval/review-signal recovery, claimant/staff visibility,
protected byte download, stale-revision refusal, and transaction rollback when a retrieval bundle
conflicts with an existing review signal. It writes only a unique synthetic Claim, Evidence, and
retrieval prefix; it never clears a database, collection, bucket, or knowledge object.

The final #350 acceptance run executed the complete local MVP smoke twice consecutively against the
same MongoDB and MinIO services. Both runs passed with independent synthetic prefixes. The
provider-failure check then stopped and restarted the isolated MinIO service, returned the bounded
`The knowledge service is unavailable.` error without evidence, and the restored governed store
subsequently passed all six RAG evaluation cases again.

The model smoke selects `AGENT_RUNTIME_PROFILE=model_gateway` in process and exercises the real
OpenAI-compatible adapter, Gateway Agent, Runtime authority, Message service, and MongoDB
repository through a deterministic `MockTransport`. It proves one accepted turn persists model
provenance and recovers after application reconstruction; an identical idempotent replay does not
call the model again; stale revision is rejected before model execution; and timeout, malformed,
incomplete, and model-controlled fact metadata attempts leave no Claim revision, message, Agent
decision, or idempotency write. The transport is controlled provider-shape evidence and must not be
reported as a live endpoint result. Policy/history remain typed fixtures, and automatic model tool
orchestration remains outside this validation.

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
