# First AWS deployment framework and evidence

This document records the first AWS deployment framework for the Validation
Prototype under Issue #1085. It separates the architecture decision from the
bounded evidence recorded under Issue #786. It does not claim that the full
FNOL application is deployed or that every AWS capability is available.

## Framework decision

The first framework uses AWS for static delivery and the host environment while
the existing application data and object-store runtime remain on one EC2 host.
The framework is:

```text
Browser
  -> CloudFront
     -> private Sydney S3 origin through Origin Access Control
        -> static claimant, Workbench, and Admin assets

Browser or API client
  -> HTTPS API origin at the EC2 host (required, not yet configured)
     -> Docker Compose
        -> Backend / FastAPI
        -> MongoDB replica set
        -> MinIO
        -> existing external model gateway
```

CloudFront serves static assets only. It does not expose `/api/*`,
`/internal/*`, MongoDB, MinIO, evidence objects, or knowledge objects. The API
origin requires a separately verified HTTPS, certificate or DNS, reverse-proxy,
and CORS boundary before a browser client can use it. The application retains
the provider-neutral model gateway; AWS hosting does not imply Bedrock model
inference.

This framework is a durable architecture record. It does not change Claim,
Session, Message, Evidence, RAG, permission, revision, or idempotency
semantics.

## Decision boundaries

The framework has the following boundaries and evidence states.

| Component | Framework role | Evidence state | Boundary or restriction |
| --- | --- | --- | --- |
| CloudFront and private S3 | Static asset delivery | `validated` | The bounded synthetic check succeeded in Sydney; the origin remains private. |
| EC2 | Host for the existing Compose topology | `validated` | A smallest bounded Sydney host launched and passed both system checks. The temporary diagnostic access was restricted to CloudShell's current address. The host must be stopped or removed after validation. |
| Backend API origin | Separate HTTPS entry point | `unconfigured` | No API certificate, DNS, reverse proxy, or browser CORS result is claimed. |
| Docker Compose | Run Backend, MongoDB, MinIO, and the configured model gateway together | `unreachable` | Docker and the Compose plugin started on EC2, but the current Compose dependency `minio/mc:RELEASE.2025-07-21T05-28-08Z` could not be pulled. A temporary `latest` and ECR Public substitution was also rejected by the checked environment. The repository Compose file was not changed. |
| MongoDB | First application persistence runtime | `local_only` | The current provider-neutral MongoDB contract remains in use; local evidence is not AWS evidence and this is not Atlas. |
| MinIO | First Evidence and knowledge object-store runtime | `local_only` | Keep the current S3-compatible boundary until an AWS runtime object-store path is separately verified. |
| External model gateway | Model inference | `unconfigured` | The existing external gateway remains the model boundary; the EC2 application did not reach a model call because the Compose stack was blocked before backend startup. No Bedrock result is claimed. |
| IAM runtime identity | Permission boundary for the host and services | `permission_denied` | Instance-profile listing was denied and no passable runtime instance profile was discoverable. Do not create or assume an unverified role. |
| Secrets Manager | Candidate runtime secret injection | `validated` | A synthetic secret was created and read back through the AWS API. Runtime injection into the application was not claimed because the Compose stack did not become reachable. |
| CloudWatch and budget monitoring | Deployment visibility and cost control | `validated` | A synthetic log group/stream, log event, metric submission, and cost budgets were exercised. Metric listing was not treated as immediate proof because of propagation delay. |
| DynamoDB | Not enabled by this framework | `validated` (capability only) | A bounded synthetic on-demand table put, consistent read, and repeat-write check succeeded. Local migration rehearsals remain `local_only`; no application adapter or migration is enabled by this framework. |
| Bedrock and Knowledge Bases | Not enabled by this framework | `permission_denied` / `unavailable` | Runtime model invocation returned an AWS authorization denial. No Knowledge Base existed and no retrieval or citation result is claimed. |
| ECS/Fargate | Not used for the first framework | `validated` (capability only) | A minimal public-image Fargate task registered, ran, and stopped successfully. This does not prove the application image, task role, private networking, secrets, or persistence path. |
| Lambda and EventBridge | Excluded from the core Claim journey | `validated` (EventBridge only) / `unavailable` (Lambda runtime) | A disabled synthetic EventBridge rule accepted a test event. Lambda execution was not enabled because no authorized execution role was available. Optional automation must not control persistence, Evidence, RAG, or Claim state. |

The framework uses Sydney (`ap-southeast-2`) for regional resources. CloudFront
is global, but its origin is the Sydney S3 bucket.

## Verified evidence

The following is the bounded evidence recorded for the course-provided AWS
sandbox. Exact account, bucket, object, distribution, and domain identifiers
remain in the private operator record and are intentionally absent here.

| Check | Evidence state | Result |
| --- | --- | --- |
| Synthetic object upload to a private Sydney S3 origin | `validated` | Upload succeeded; the object was not public. |
| CloudFront read through the private origin | `validated` | The request returned HTTP `200`, the expected synthetic 52-byte body, `Via: CloudFront`, and `X-Cache: Hit from cloudfront`. |
| Direct S3 object request | `validated` | The request returned HTTP `403`, confirming that the bucket was not made public. |
| EC2 launch and application runtime | `unreachable` | EC2 launch, system checks, Docker installation, and Compose installation succeeded. The application stack did not become reachable because its MinIO client image could not be pulled. |
| HTTPS API origin, certificate, DNS, reverse proxy, and CORS | `unconfigured` | No browser-safe API path was configured. The API origin cannot be validated until the backend stack is reachable. |
| Runtime identity and secret injection | `permission_denied` / `validated` | Instance-profile discovery was denied; an isolated synthetic Secrets Manager read succeeded. No application secret injection is claimed. |
| AWS persistence, Evidence, RAG, and full FNOL journey | `unconfigured` | AWS service probes exist for selected capabilities, but no full application integration or FNOL journey is claimed. |

The static result proves only private S3-to-CloudFront delivery. A console
login, local MongoDB or MinIO result, fixture, mock, or external model response
does not upgrade any other row to `validated`.

This evidence is supplied to #786 for prerequisite verification. It is not
deployment-readiness evidence for the EC2 application stack or its API origin.

## Issue #1139 validation update

The validation pass used `origin/main@c9fd8f6be570ba3f68216217b294d9d7000effbc`
in Sydney (`ap-southeast-2`) and synthetic data only. It created bounded
temporary resources and did not execute MongoDB/MinIO-to-AWS migration.

Validated capability evidence includes EC2 launch and system checks, Docker
installation, Docker Compose installation, DynamoDB on-demand put/consistent
read and repeat-write behaviour, synthetic Secrets Manager readback,
CloudWatch log and metric submission, EventBridge rule/event submission, ECR
push, and a minimal Fargate task run. The private S3-to-CloudFront static path
remained validated with direct S3 access denied.

The application-level EC2 check stopped at the container image stage. The
current repository Compose reference for `minio/mc` was not pullable in the
checked environment, so Backend liveness/readiness, MongoDB/MinIO restart
readback, RAG, external model gateway, API HTTPS/CORS, and the full FNOL smoke
remain unverified. A temporary image-name substitution was used only to test
whether the dependency could be recovered; it was not committed and did not
produce a successful stack startup.

Bedrock runtime invocation was explicitly denied for the checked CLI identity;
Knowledge Bases had no configured instance. IAM instance-profile discovery was
also denied. These results are capability constraints, not application-code
changes. The cost guard was configured against the observed account baseline
plus an additional USD 200 in USD 20 actual-cost increments; the email
subscription remains pending recipient verification.

## Verification labels and stop conditions

Use these labels in the AWS verification record.

| Label | Meaning |
| --- | --- |
| `validated` | A real bounded call or journey succeeded in the named AWS environment. |
| `permission_denied` | AWS returned an explicit authorization denial. |
| `unreachable` | The endpoint or network path could not be reached. |
| `unconfigured` | The required resource or runtime configuration does not exist in the checked environment. |
| `unavailable` | The service or capability cannot be used under the checked account constraints. |
| `local_only` | The result came from local MongoDB, MinIO, a fixture, or a mock environment. |

Do not substitute local results for a required AWS capability. Stop the
deployment record when a required capability is `permission_denied`,
`unreachable`, `unconfigured`, or `unavailable`. In particular, do not
report the following as complete AWS integration:

- Browser login without a running application call.
- An S3 console upload without Backend runtime access.
- Local MongoDB or MinIO data without EC2 restart and readback evidence.
- Local RAG retrieval without a verified deployed retrieval provider.
- A fixture or external model response labelled as Bedrock output.
- A static CloudFront page calling an unspecified plain-HTTP API endpoint.

## Activation sequence

When the account and permissions are available, validate the framework in this
order. Each step must retain its actual evidence label.

1. Verify Sydney-region EC2 launch, networking, storage, and the permitted
   runtime identity using synthetic data and bounded resource sizes.
2. Start the existing Compose topology and verify health, restart, persistence,
   claimant, Workbench, Evidence, RAG, and model-gateway smoke paths.
3. Configure an HTTPS API origin and its CORS policy separately from the
   static CloudFront distribution, then verify browser-to-API calls.
4. Publish static clients to the private S3 origin and verify CloudFront
   delivery without exposing internal services.
5. Add CloudWatch and budget visibility for the resources actually used, and
   stop non-essential resources outside demonstrations.
6. Record exact identifiers only in the approved private AWS verification
   record. Keep repository and GitHub evidence anonymized.

This sequence does not activate DynamoDB, Bedrock, Knowledge Bases,
ECS/Fargate, or an S3 Evidence adapter. Each future activation requires a
separate bounded task against the then-current contracts and permissions.

## Migration boundary

The repository's MongoDB-to-DynamoDB design and local rehearsal remain
preparation evidence only. They do not enable DynamoDB and are not evidence of
AWS reads or writes. This document does not close, supersede, or otherwise
dispose of PR #1010; that PR's treatment is outside this architecture record.

Evidence bytes and governed knowledge objects remain behind the current MinIO
boundary for the first EC2 framework. The synthetic S3 check must not be
interpreted as permission to change the Evidence adapter or to copy
policyholder data to S3.

## Cost and safety controls

Use one smallest suitable EC2 host, one private S3 origin, synthetic data,
bounded logs, and stopped resources outside demonstrations. Do not provision
DynamoDB, Bedrock Knowledge Bases, OpenSearch, ECS/Fargate, or always-on search
infrastructure without a separate capability and cost review. Never commit
credentials, endpoints, account identifiers, policyholder data, or raw
credential-bearing errors.
