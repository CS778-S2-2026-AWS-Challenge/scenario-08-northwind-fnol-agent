# Verified AWS deployment plan

This document fixes the AWS deployment path supported by the evidence collected
for account `022499038031` on `2026-09-28`. It is an implementation decision and
verification record for the Validation Prototype, not a claim that every AWS
provider profile is implemented. The plan uses synthetic data only and keeps
the existing provider-neutral application contracts unchanged.

## Decision

The project uses AWS for the public static entry point and the host environment,
while the current application data and object-store runtime remain on one EC2
host. The verified path is:

```text
Browser
  -> CloudFront Free plan
     -> private S3 bucket through Origin Access Control
        (static claimant, Workbench, and Admin assets when packaged)

Browser/API client
  -> EC2 public application endpoint
     -> Docker Compose
        -> Backend / FastAPI
        -> MongoDB replica set
        -> MinIO
        -> existing external model gateway
```

CloudFront and S3 are separate from the Backend API path. `/api/*`,
`/internal/*`, evidence upload, claim persistence, and RAG retrieval continue
to use the existing Backend and MinIO boundaries until a separate runtime
identity and provider migration have been verified.

The deployment uses Sydney, `ap-southeast-2`, because the course account
requires Sydney resources. CloudFront is global, but its origin is the Sydney
S3 bucket.

## Verified resource path

The following resources were created only for a synthetic connectivity check:

| Resource | Verified value | Evidence |
| --- | --- | --- |
| AWS account | `022499038031` | AWS console session used for the check. |
| Repository baseline | `origin/main` at `ec5bd07555ee38a60cdd76dfaa6c6eae32f65c70` | Current contracts used when this plan was fixed. |
| S3 bucket | `nw-fnol-static-check-022499038031-20260928` | Bucket creation and object upload succeeded in Sydney. |
| S3 object | `tmpnzgy2k.tmp` | A 52-byte synthetic object was uploaded and read by CloudFront. |
| CloudFront distribution | `EIEGNJOBUS39Y` | Distribution creation succeeded and status became enabled. |
| CloudFront domain | `d18u26m0cj618r.cloudfront.net` | HTTP request returned the test object. |
| CloudFront plan | Free | Console showed `$0/month` and `$0` estimated pro-rated charge at creation. |

The final HTTP check returned `200`, 52 bytes, the expected synthetic body,
`Via: CloudFront`, and `X-Cache: Hit from cloudfront`. The direct S3 object
URL returned `403`, so the bucket was not made public. CloudFront access was
granted through the distribution's private-origin configuration.

This evidence proves only private S3-to-CloudFront delivery. It does not prove
Backend runtime access to S3, an EC2 instance profile, an AWS database adapter,
or a complete application deployment.

## Service boundaries

The following table is the current service decision. Each status describes the
strongest evidence available, not an intended future state.

| Service or component | Decision | Boundary |
| --- | --- | --- |
| CloudFront | Use | Public static delivery through the verified Free plan distribution. |
| S3 | Use for static assets | Keep the bucket private and grant access through CloudFront. Do not connect the current Backend Evidence adapter until a runtime identity is verified. |
| EC2 | Use for the Validation Prototype host | Run the existing Docker Compose application and durable EBS-backed MongoDB/MinIO volumes. Instance size, network rules, and runtime identity require a separate bounded EC2 validation. |
| MongoDB | Keep for the application runtime | Preserve the current local MVP source model and provider-neutral repository contract. This is not MongoDB Atlas. |
| MinIO | Keep for Evidence and knowledge objects | Preserve the current S3-compatible object-store boundary for the running Backend until an AWS runtime object-store path is proven. |
| External model gateway | Keep | Continue using the existing provider-neutral Model Gateway and configured external GPT-4o gateway. AWS hosting does not imply Bedrock model inference. |
| DynamoDB | Do not enable yet | `#992` and `#1010` provide local migration rehearsal evidence only. No runtime adapter, table, IAM access, or AWS read/write evidence is claimed. |
| Bedrock and Knowledge Bases | Do not enable yet | The application can retain its provider-neutral RAG contract, but the current AWS plan does not depend on Bedrock. No Bedrock or Knowledge Bases evidence is claimed. |
| ECS/Fargate | Do not use for the first deployment | The current account evidence does not establish the required runtime role, networking, image-pull, secret, database, or persistent-volume path. EC2 gives the existing Compose topology a bounded host target. |
| Secrets Manager | Pending runtime validation | Use only after the selected EC2 runtime identity and secret-read path are verified. Never put credentials in the repository or an image. |
| CloudWatch | Use for host/application observability when available | Add logs and alarms after the EC2 deployment path is verified. CloudFront and S3 connectivity evidence is not CloudWatch deployment evidence. |
| IAM | Use the course-provided permission boundary | Do not create or assume additional roles. Record every required action that is denied and keep the application fail-closed. |
| Lambda/EventBridge | Exclude from the core path | Optional non-core automation only. They must not control Claim journey, persistence, Evidence, or RAG behaviour. |

## Deployment sequence

The deployment follows this order so each step has a bounded rollback point:

1. Verify the Sydney account permissions, EC2 launch capability, networking,
   storage, security-group rules, and the ability to run the selected host
   configuration. Do not record console access alone as runtime evidence.
2. Launch the smallest suitable EC2 instance and attach durable storage for
   MongoDB and MinIO. Do not use real customer data.
3. Install the existing container runtime and start the current Compose
   profile. Keep the Backend, MongoDB, MinIO, and model gateway configuration
   aligned with the repository's runtime deployment profiles.
4. Run health, restart, persistence, claimant, Workbench, Evidence, and RAG
   smoke checks. A fixture or local-only result remains labelled as such.
5. Publish the built static clients to the private S3 bucket and serve them
   through CloudFront. Configure API access separately; do not expose MongoDB,
   MinIO, or internal routes through the static distribution.
6. Add CloudWatch visibility and budget monitoring for the resources actually
   used. Stop non-essential resources outside demonstrations.
7. Record exact resource identifiers, configuration assumptions, test commands,
   and blocked capabilities in the AWS verification issue. Do not claim a
   complete AWS journey until the Backend and all required consumers have real
   evidence.

## Repository and migration boundary

The current repository already defines the provider-neutral API, persistence,
Evidence, RAG, runtime-profile, and fail-closed contracts. This deployment plan
does not add fields, lifecycle states, permissions, or a second persistence
model. The existing MongoDB-to-DynamoDB design remains the authoritative local
preparation for `#991` and `#992`; it is not activated by this plan.

Pull request `#1010` rehearsed a possible DynamoDB migration locally but did
not create DynamoDB resources, perform AWS writes, or provide an application
adapter. The selected EC2/MongoDB plan does not require that pull request, so
it is closed without merge. If DynamoDB is reconsidered later, the team must
open a new bounded task against the then-current persistence contract and
revalidate any reusable mapping rather than treating `#1010` as AWS evidence.

Evidence bytes and governed knowledge objects remain behind the existing MinIO
boundary for the first EC2 deployment. The S3 connectivity check used a
separate synthetic bucket and object; it must not be interpreted as permission
to change the current Evidence adapter or to copy policyholder data to S3.

## Verification levels and stop conditions

Use these evidence labels in deployment records:

| Label | Meaning |
| --- | --- |
| `validated` | A real bounded call or journey succeeded in the named AWS environment. |
| `permission_denied` | AWS returned an explicit authorization denial. |
| `unreachable` | The endpoint or network path could not be reached. |
| `unconfigured` | The required resource or runtime configuration does not exist. |
| `unavailable` | The service or capability cannot be used under the current account constraints. |
| `local_only` | The result came from the repository's local MongoDB, MinIO, fixture, or mock environment. |

Stop the migration rather than substituting fixtures when any required
capability is `permission_denied`, `unconfigured`, or `unavailable`. In
particular, do not report the following as complete AWS integration:

- browser login without a running application call;
- an S3 console upload without Backend runtime access;
- local MongoDB or MinIO data without an EC2 restart/readback check;
- a local RAG retrieval without a verified deployed retrieval provider;
- a CloudFront distribution that cannot read the private origin;
- an AWS resource created in a different region from Sydney;
- a fixture or external model response labelled as Bedrock output.

## Cost controls

The first deployment is demonstration-scale. Use the smallest suitable EC2
instance, one host, one private S3 origin, the CloudFront Free plan, synthetic
data, bounded logs, and stopped resources outside testing. Do not provision
DynamoDB, Bedrock Knowledge Bases, OpenSearch, ECS/Fargate, or always-on search
infrastructure unless a later verified capability and an explicit cost review
justify it. Review AWS Budgets and the account billing view before each longer
run.

## Current limitations

The following work remains separate and is not closed by this document:

- EC2 launch and inbound/outbound network verification;
- EC2 runtime identity and secret injection;
- container start and restart evidence on EC2;
- MongoDB and MinIO persistence after host/container replacement;
- complete claimant, Workbench, Evidence, and RAG journey evidence on EC2;
- AWS budget and CloudWatch configuration;
- any future DynamoDB adapter or Bedrock Knowledge Bases integration.

The first verified result is therefore a fixed deployment direction and a
working private S3-to-CloudFront path. It is not a claim that the full FNOL
journey is already deployed to AWS.
