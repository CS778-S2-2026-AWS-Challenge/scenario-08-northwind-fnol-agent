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
| EC2 | Host for the existing Compose topology | `unconfigured` | Launch, security-group, storage, restart, and outbound-network evidence is still required. |
| Backend API origin | Separate HTTPS entry point | `unconfigured` | No API certificate, DNS, reverse proxy, or browser CORS result is claimed. |
| Docker Compose | Run Backend, MongoDB, MinIO, and the configured model gateway together | `unconfigured` | Container startup, health, restart, and persistence must be verified on EC2. |
| MongoDB | First application persistence runtime | `local_only` | The current provider-neutral MongoDB contract remains in use; local evidence is not AWS evidence and this is not Atlas. |
| MinIO | First Evidence and knowledge object-store runtime | `local_only` | Keep the current S3-compatible boundary until an AWS runtime object-store path is separately verified. |
| External model gateway | Model inference | `unconfigured` | The existing external gateway remains the model boundary; no Bedrock result is claimed. |
| IAM runtime identity | Permission boundary for the host and services | `unconfigured` | Use only the course-provided boundary; do not create or assume an unverified role. |
| Secrets Manager | Candidate runtime secret injection | `unconfigured` | No secret, credential, or secret-read path is committed or claimed. |
| CloudWatch and budget monitoring | Deployment visibility and cost control | `unconfigured` | Configure and verify only for resources that are actually deployed. |
| DynamoDB | Not enabled by this framework | `unconfigured` | Local migration rehearsals remain `local_only`; no AWS table, adapter, or read/write result is claimed. |
| Bedrock and Knowledge Bases | Not enabled by this framework | `unconfigured` | The provider-neutral RAG contract remains; no Bedrock retrieval or citation result is claimed. |
| ECS/Fargate | Not used for the first framework | `unconfigured` | No image-pull, task-role, networking, secret, or persistent-volume evidence is claimed. |
| Lambda and EventBridge | Excluded from the core Claim journey | `unconfigured` | Optional non-core automation must not control persistence, Evidence, RAG, or Claim state. |

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
| EC2 launch and application runtime | `unconfigured` | No EC2 host, Compose startup, or application-call evidence is included in this record. |
| HTTPS API origin, certificate, DNS, reverse proxy, and CORS | `unconfigured` | No browser-safe API path has been configured or verified. |
| Runtime identity and secret injection | `unconfigured` | No host-to-service identity or secret-read call has been verified. |
| AWS persistence, Evidence, RAG, and full FNOL journey | `unconfigured` | No AWS application integration is claimed. |

The static result proves only private S3-to-CloudFront delivery. A console
login, local MongoDB or MinIO result, fixture, mock, or external model response
does not upgrade any other row to `validated`.

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
