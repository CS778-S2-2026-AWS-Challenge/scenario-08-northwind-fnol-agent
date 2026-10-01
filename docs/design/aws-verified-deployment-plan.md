# AWS deployment framework and bounded evidence

This document records the AWS deployment framework validated against the
course-provided Sydney account on 2026-10-01. It records the infrastructure
path that was tested with synthetic content. It does not claim that the full
FNOL application, MongoDB persistence, MinIO persistence, or every AWS service
is deployed.

## Framework decision

The framework uses CloudFront as the browser entry point and one EC2 host for
the existing provider-neutral application topology:

```text
Browser
  -> CloudFront HTTPS
     -> /                 private Sydney S3 origin through OAC
        -> static claimant, Workbench, and Admin assets
     -> /api/*            EC2 custom origin over HTTP
        -> Docker Compose
           -> Backend / FastAPI
           -> MongoDB replica set
           -> MinIO
           -> existing external model gateway
```

The CloudFront distribution uses managed cache policies. The static S3
origin remains private. The `/api/*` behavior uses a disabled-cache policy
and forwards the request to the EC2 origin. The validated HTTP origin is a
bounded synthetic demonstration path; it is not a claim of end-to-end TLS
between CloudFront and EC2. A production deployment would require a trusted
certificate and DNS name for the EC2 API origin.

CloudFront does not expose `/internal/*`, MongoDB, MinIO, evidence objects, or
knowledge objects. The application keeps the provider-neutral model gateway;
AWS hosting does not imply Bedrock model inference. This framework does not
change Claim, Session, Message, Evidence, RAG, permission, revision, or
idempotency semantics.

## Account and permission boundary

Regional resources use Sydney (`ap-southeast-2`). CloudFront is global. The
current SSO identity can create and operate the tested resources, but it
cannot pass an EC2 IAM role:

- The pre-created `ec2-ssm-role` and
  `AWSAccelerator-SessionManagerEC2Role` exist.
- `iam:GetRole`, `iam:GetInstanceProfile`, and `iam:PassRole` are denied to
  the current SSO identity.
- The validated EC2 path therefore launches without an instance profile.
- EC2 Instance Connect supplies a short-lived SSH public key for bounded
  administration; SSM is not a deployment dependency.

No AWS-managed teaching resources, including AWSAccelerator, ControlTower, or
CloudHealth resources, are changed by this framework.

## Decision boundaries and evidence state

| Component | Framework role | Evidence state | Boundary or restriction |
| --- | --- | --- | --- |
| CloudFront | HTTPS browser entry point and S3/API routing | `validated` | A real distribution served both synthetic S3 content and a synthetic EC2 API response. |
| Private S3 | Static frontend origin | `validated` | OAC access succeeded; direct object access returned `403`. It is not the Evidence adapter. |
| EC2 | Host for the Compose topology | `validated` | No instance profile is attached. The tested host used a smallest bounded instance. |
| EBS root volume | EC2 boot storage | `provisioned_only` | The EC2 launch provisioned its root volume; application restart and data readback were not tested in this smoke run. |
| VPC, subnet, and security group | EC2 network boundary | `validated` | A temporary Sydney security group allowed only the bounded HTTP/SSH smoke path. |
| Elastic IP | Stable EC2 origin address | `validated` | Allocation and association to the test EC2 succeeded. |
| EC2 Instance Connect | Temporary host access | `validated` | `send-ssh-public-key` returned `Success: true`, followed by a successful SSH command. |
| CloudShell | AWS control-plane and deployment shell | `validated` | AWS CLI commands ran with the course SSO identity. |
| Docker Compose | Backend, MongoDB, MinIO, and model gateway runtime | `unconfigured` | The tested EC2 served a synthetic Nginx endpoint; the project Compose profile still requires a separate EC2 startup test. |
| Backend API | Application API | `unconfigured` | The CloudFront test used a synthetic `/api/health` endpoint, not the real Backend. |
| MongoDB | Application persistence | `local_only` | Current MongoDB contract remains in use; no AWS MongoDB or restart/readback claim is made. |
| MinIO | Evidence and knowledge object store | `local_only` | Keep the current S3-compatible boundary; no AWS object-store adapter is enabled. |
| External model gateway | Model inference | `unconfigured` | The existing external gateway remains the model boundary; no live model call was made on EC2. |
| IAM/SSO | AWS control-plane authorization | `validated` | Current SSO actions were verified; runtime EC2 role attachment is `permission_denied`. |
| Secrets Manager | Runtime secret injection | `unavailable` | No EC2 role can read it. Inject deployment secrets only through a bounded operator session. |
| SSM | Host administration | `unavailable` | No usable instance profile can be attached. |
| CloudWatch Agent | Automatic application logging | `unavailable` | No EC2 role-backed log shipping was verified. Use bounded host logs during the demonstration. |
| Budget | Cost control | `configured_only` | Account budget alerts exist, but this smoke run did not change or re-verify them. |
| DynamoDB | AWS persistence target | `not_enabled` | No table, adapter, read/write result, or migration claim is made. |
| Bedrock and Knowledge Bases | Model/RAG provider | `not_enabled` | The provider-neutral model gateway and current RAG boundary remain in use. |
| ECS/Fargate | Container orchestration | `not_enabled` | No task or execution role is available for a stable deployment. |
| ECR | Image registry | `not_enabled` | The validated smoke used a direct EC2 origin; private ECR runtime pull was not required. |
| Lambda/EventBridge | Non-core automation | `not_enabled` | They do not control the Claim journey. |

## Verified evidence

The following evidence came from the course account and synthetic content. The
exact account, object, and temporary resource identifiers remain in the
private operator record and are intentionally absent here.

| Check | Evidence state | Result |
| --- | --- | --- |
| EC2 launch without an IAM role | `validated` | Dry-run permission check succeeded, then a real `t3.micro` instance launched in Sydney without an instance profile. |
| EC2 HTTP origin | `validated` | The test host returned `HTTP/1.1 200 OK` for `/health`. |
| Elastic IP | `validated` | The address was allocated, associated with EC2, and used as the stable origin address. |
| Security group | `validated` | HTTP and temporary SSH rules were created for the bounded smoke test. |
| EC2 Instance Connect | `validated` | A generated synthetic Ed25519 public key was accepted and an SSH command completed successfully. |
| Private S3 upload | `validated` | A synthetic `index.html` was uploaded to a new private Sydney bucket. |
| Direct S3 read | `validated` | Direct object access remained denied. |
| CloudFront private S3 delivery | `validated` | CloudFront returned `HTTP/2 200`, the expected synthetic body, `via: CloudFront`, and Sydney POP evidence. |
| CloudFront `/api/*` custom origin | `validated` | `/api/health` returned `HTTP/2 200` from the EC2 Nginx origin with CloudFront `via` and POP headers. |
| Free pricing plan compatibility | `validated` | CloudFront rejected legacy cache settings; the distribution update succeeded after switching to managed cache and origin-request policies. |
| Real Backend Compose runtime | `unconfigured` | Not run in this bounded smoke test. |
| MongoDB/MinIO restart and readback | `unconfigured` | Not run in this bounded smoke test. |
| Full claimant, Workbench, Evidence, RAG, and model journey | `unconfigured` | Not run in this bounded smoke test. |

The CloudFront result proves the AWS routing chain, not the complete FNOL
application. Local MongoDB, MinIO, fixtures, mocks, and synthetic Nginx
responses do not upgrade the application rows above to `validated`.

## Activation sequence for the real application

1. Launch one smallest suitable EC2 instance without an IAM role and attach an
   Elastic IP.
2. Use EC2 Instance Connect for bounded setup; never commit or bake credentials
   into an image.
3. Attach durable EBS storage and run the existing `vp` Docker Compose profile.
4. Verify Backend health, MongoDB replica-set readiness, MinIO readiness,
   external model gateway readiness, restart recovery, and data readback.
5. Publish the built static clients to a private S3 bucket through CloudShell.
6. Configure CloudFront with the private S3 default behavior and the disabled
   cache `/api/*` EC2 behavior.
7. Verify Claimant, Workbench, Evidence, RAG, model-gateway, timeout, and
   unavailable paths through the CloudFront entry point.
8. Stop the EC2 host outside demonstrations and retain only the minimum
   required resources.

## Migration boundary

MongoDB and MinIO remain the application runtime for this framework. The
MongoDB-to-DynamoDB design and local rehearsal are preparation evidence only;
they do not enable DynamoDB and are not AWS read/write evidence. Evidence and
governed knowledge objects remain behind the current MinIO boundary. The S3
static-site smoke test must not be interpreted as permission to change the
Evidence adapter or copy policyholder data to S3.

## Cost and safety controls

Use one smallest suitable EC2 host, one private S3 origin, synthetic data, and
bounded CloudFront/API traffic. Stop the EC2 instance outside demonstrations.
Do not provision DynamoDB, Bedrock Knowledge Bases, OpenSearch, ECS/Fargate,
or always-on search infrastructure without a separate capability and cost
review. Never commit credentials, endpoints, account identifiers, policyholder
data, or raw credential-bearing errors.
