# AWS deployment framework and bounded evidence

This document records the AWS deployment framework validated against the
course-provided Sydney account on 2026-10-01 and the bounded application
rehearsal on 2026-10-02. Actual application, persistence, model, and browser
checks are distinguished below from infrastructure probes and unresolved
acceptance gates. This is not a production rollout or data migration.

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
     -> /northwind-evidence/*  EC2 HTTP -> loopback MinIO signed objects
```

The CloudFront distribution uses managed cache policies. The static S3
origin remains private. The `/api/*` behavior uses a disabled-cache policy
and forwards the request to the EC2 origin. The validated HTTP origin is a
bounded synthetic demonstration path; it is not a claim of end-to-end TLS
between CloudFront and EC2. A production deployment would require a trusted
certificate and DNS name for the EC2 API origin.

CloudFront denies `/internal/*`. MongoDB and MinIO management ports bind only
to EC2 loopback. Evidence uses the explicitly approved signed-object path;
an unsigned object request returned `403`. Knowledge objects are not routed
publicly. The application keeps the provider-neutral model gateway;
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
| EBS root volume | EC2 boot and named application volumes | `validated` for bounded recovery | Three application records and Evidence hashes survived container and host restart. Offline backup/restore to separate volumes passed application readback. |
| VPC, subnet, and security group | EC2 network boundary | `validated` | A temporary Sydney security group allowed only the bounded HTTP/SSH smoke path. |
| Elastic IP | Stable EC2 origin address | `validated` | Allocation and association to the test EC2 succeeded. |
| EC2 Instance Connect | Temporary host access | `validated` | `send-ssh-public-key` returned `Success: true`, followed by a successful SSH command. |
| CloudShell | AWS control-plane and deployment shell | `validated` | AWS CLI commands ran with the course SSO identity. |
| Docker Compose | Backend, MongoDB, MinIO, and model gateway runtime | `validated` with deployment overrides | The pinned application ran on t3.small; original MinIO images were imported. The CLI worker needs its inherited HTTP healthcheck disabled and separate cycle-log monitoring. |
| Backend API | Application API | `validated` for bounded workflows | Real CloudFront HTTP workflows passed. Readiness remains explicitly degraded because some upstream business services use existing fixtures. |
| MongoDB | Application persistence | `validated` on EC2 | Revision, messages, creation replay, and authentication survived restart and restored-volume readback; no DynamoDB claim. |
| MinIO | Evidence and knowledge object store | `validated` on EC2 | Signed browser upload, staff download checksum, governed RAG metadata, restart, and restored-volume readback passed. |
| External model gateway | Model inference | `validated` for structured text | Actual GPT-4o inference and controlled request timeout were exercised. This is not Bedrock or proof of every modality. |
| IAM/SSO | AWS control-plane authorization | `validated` | Current SSO actions were verified; runtime EC2 role attachment is `permission_denied`. |
| Secrets Manager | Runtime secret injection | `unavailable` | No EC2 role can read it. Inject deployment secrets only through a bounded operator session. |
| SSM | Host administration | `unavailable` | No usable instance profile can be attached. |
| CloudWatch Agent | Automatic application logging | `unavailable` | No EC2 role-backed log shipping was verified. Use bounded host logs during the demonstration. |
| Budget | Cost notification | `configured_only` with verified readback | Baseline plus USD 200 and ten USD 20 thresholds were read back. Annual tracking avoids monthly reset during the course; email receipt and automatic shutdown are not verified. |
| DynamoDB | AWS persistence target | `not_enabled` | No table, adapter, read/write result, or migration claim is made. |
| Bedrock and Knowledge Bases | Model/RAG provider | `not_enabled` | The provider-neutral model gateway and current RAG boundary remain in use. |
| ECS/Fargate | Container orchestration | `not_enabled` | No task or execution role is available for a stable deployment. |
| ECR | Image registry | `not_enabled` | The validated smoke used a direct EC2 origin; private ECR runtime pull was not required. |
| Lambda/EventBridge | Non-core automation | `not_enabled` | They do not control the Claim journey. |

## Verified evidence

### Application rehearsal on 2026-10-02

The subsequent #1163 rehearsal restored the bounded test route and deployed
application commit `f1b897d76dbb3d5d854b6172c7cc49907e3f902a` on a Sydney
`t3.small` without an instance profile. The source archive checksum matched
on EC2. Docker Compose v2.39.4 was installed after checking its official
published checksum. The built Backend image ID is
`sha256:aeb61588f2fd6358c0510e2f00b73b59dcc27560c1705f0ab48711f17749108d`.
These later observations supersede the initial re-entry blockers below;
neither the historical probes nor this bounded rehearsal establishes a
long-lived production deployment.

| Check | Actual result | Evidence boundary |
| --- | --- | --- |
| Compose initialization | Backend, MongoDB, and MinIO became healthy; database, storage, and knowledge initializers exited 0. | The CLI worker inherited an unsuitable HTTP healthcheck. A deployment-only override disabled it; two successful cycle-log records were then observed. No dedicated worker health endpoint is claimed. |
| Backend readiness | HTTP 200, status `degraded`; persistence verified and Evidence/knowledge configured as services. | Existing policy, claim-history, claims-service, and handoff-dispatch fixtures remain explicit. No all-live provider claim. |
| External model | `python -m scripts.verify_model_gateway_live` returned `live_call_succeeded`, request ID present, 139 total tokens. | Actual provider model was `openai/gpt-4o`; the profile's legacy mini name is not its selected model. |
| Public routing | CloudFront root returned 200; unauthenticated claims returned 401; internal knowledge path returned 403. | Private S3 serves the built clients; the EC2 origin still uses approved HTTP for synthetic testing. |
| Three product HTTP journeys | Motor, home, and contents each completed account/session creation, a model turn, signed Evidence upload/completion, support request, staff acceptance/reply, and claimant message readback. | These are real deployed HTTP workflows, not completed external insurer submissions or three complete browser journeys. |
| Browser claimant | Registration, model reply, and synthetic JPEG upload displayed successfully; the attachment reached `Ready`. | The rendered date inferred from “yesterday” was in 2023. This application behavior is recorded, not repaired by deployment work. |
| Governed RAG | Each product returned three citations with document, chunk, version, checksum, and source metadata; a missing document returned `no_evidence`. | The diagnostic called the actual configured service inside Backend. It does not prove a browser citation flow or public internal-API access. |
| Container restart/readback | After Backend/MinIO restart and a separate MongoDB restart, all three records retained revision 8, three messages, matching Evidence bytes, and the same claim on creation replay. | SQLite-backed claimant/staff login also worked. Audit preservation and backup/restore require separate evidence. |
| EC2 reboot/readback | Host uptime reset; Backend, MongoDB, and MinIO restarted automatically. All three readback checks passed again. | This proves retained-volume recovery, not replacement of a lost EBS volume. |
| Cost guard correction | Two existing budgets now cover annual cumulative cost through the end of 2026, baseline USD 275.53 and limit USD 475.53. Ten actual-cost thresholds run from USD 295.53 to USD 475.53 in USD 20 increments. | Subscriber addresses were read back and matched the authorized email. Configuration is verified; email delivery and real-time spending enforcement are not claimed. |
| Backup/restore | Offline MongoDB data, MinIO data, and SQLite state archives were restored to separate named volumes. Archive comparisons and all three application readback checks passed. | The first temporary probe selected MongoDB's auxiliary volume and failed claim readback. The corrected rehearsal explicitly selected the original data volume; original volumes were preserved. This is a same-host rehearsal, not disaster recovery to another host. |
| Browser Workbench | Staff login and all three assigned product conversations displayed claimant, model, and staff messages after restoration. | The browser claimant report resumed with its attachment marked Ready. External-claim submission was not exercised. |
| Model timeout | A separate process with `MODEL_TIMEOUT_SECONDS=0.001` returned `live_call_failed code=timeout retryable=true`. | Deliberate fault injection into the real gateway, not spontaneous provider outage. Normal runtime timeout remained unchanged. |
| Storage unavailable | Stopped MinIO caused a running diagnostic's actual RAG service to return unavailable with zero citations. A new application refused startup without a fixture fallback. | MinIO was restarted after the test; the diagnostic did not expose an internal API. |
| RAG timeout classification | A controlled delayed HTTP object-store response produced unavailable in 0.054 seconds, with zero citations. | **Unresolved:** the real object-store adapter collapses read timeout into unavailable. This does not satisfy separate RAG timeout evidence. No application code was changed. |
| Original-image retention | A separate private, versioned, AES256 S3 artifact bucket accepted the 238092288-byte archive. Streamed readback matched its recorded SHA-256 and metadata. | This bucket is not the CloudFront origin and has no public access or OAC grant. Retention incurs storage cost. |

Release set observed during this rehearsal was `rel_223b008852f5c2546d94`.
The active agent instruction was `northwind-fnol-claimant-v8`, configuration
revision 3. Tool policy, agent rule, feature, and referenced model configuration
records also reported revision 3. The selected legacy-named profile was
`openrouter-gpt4o-mini`; the actual live-call result identified GPT-4o.
The runtime timeout was 180 seconds. Merely referencing the other seeded
model profiles is not proof that those providers are enabled or callable.
This rehearsal does not establish deployment of a newer team release.
Runtime secrets were supplied only to the authorized test EC2 through a
private deployment file. The Compose containers were removed without deleting
named data volumes; the old isolated MinIO probe was stopped. The EC2 `.env`
and private runtime archive, CloudShell runtime archive, and local temporary
runtime archive were removed. CloudFront was set disabled, EC2 stop requested,
the test Elastic IP released, and temporary SSH ingress removed. Final
control-plane readback showed EC2 `stopped`, no public IP, no SSH ingress,
and CloudFront `Enabled=false`, `Status=Deployed`: disable propagation completed.
Retained EBS data/backup volumes,
private static assets, and the private image artifact still incur storage
costs. These are recoverable retained artifacts, not an active deployment.
No application
data was migrated. The issue and PR must remain open/Draft while required
gates remain unresolved. A later fetch resolved `origin/main` to
`954c7374b3c1defee1499bf01cc14d12a379d728`; it changes Workbench/claim-acceptance
contracts and was not substituted into this pinned rehearsal. Reconcile that
delta and the intended release before freezing rather than relabeling these
results as tests of the newer head.

### Initial re-entry observations on 2026-10-02

The historical routing results below are not an inventory of resources that
remain active. Real account checks for #1163 found that the listed CloudFront
distribution is disabled, contains only an S3 origin, and has no API cache
behavior. Its domain failed DNS resolution from CloudShell. `head-bucket`
returned `404` for that origin bucket; the bucket inventory contained only
the protected teaching access-log bucket. `describe-addresses` returned an
empty list. A complete routing rehearsal therefore requires restoring test
resources before testing the application; the historical `200` and `403`
results must not be presented as current endpoint availability.

The application input for this attempt is `origin/main` commit
`f1b897d76dbb3d5d854b6172c7cc49907e3f902a`. Its `git archive` ZIP has SHA-256
`b6cd8ca4b21e253fcbe649c811f39ffc6090b3fd052aea0dcf14a33d183130f7`;
the uploaded CloudShell copy returned the same hash. Local `npm ci` and
`npm run build` completed with exit 0 for `customer`, `workbench`, and `admin`.
These are artifact/build checks, not AWS application or browser-journey results.

The retained EC2 was initially stopped. It was resized to `t3.small`, started,
and reported both system and instance status `ok`. No complete Compose stack
was started. The security group has no SSH ingress and the CloudShell source
address changed, so host access awaits confirmation of the bounded temporary
SSH rule. EC2 was confirmed stopped with no public address while waiting;
no SSH ingress was added. Retained EBS storage continues to incur charges.
The original image archive remains in CloudShell.

The cost-guard budgets still use the previous month's baseline: the lower
guard reports a monthly limit of USD 475.23 and actual spend of USD 32.788,
with actual-cost alert thresholds of USD 295.23 through USD 375.23 in USD 20
steps. These thresholds do not provide alerts for each additional USD 20
from the new month's spend. Cross-month cost tracking must be reconciled;
budget existence alone is not successful verification of that requirement.

The application rehearsal above records the subsequent restored route,
model/RAG checks, and recovery results. These initial observations explain
the starting state and are not the final resource inventory.

### Historical bounded checks

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
| Original MinIO image artifact on EC2 | `validated` | Operator uploaded the original archive, verified its SHA-256 on EC2, loaded both images, and confirmed the original image IDs. |
| Isolated EC2 MinIO container restart | `validated` | A synthetic object read before and after container restart returned the same SHA-256. No application data was migrated. |
| Isolated EC2 MinIO host reboot | `validated` | Docker and MinIO restarted automatically after EC2 reboot; the same object SHA-256 was read back. |
| MongoDB/MinIO restart and readback | `unconfigured` | Not run in this bounded smoke test. |
| Full claimant, Workbench, Evidence, RAG, and model journey | `unconfigured` | Not run in this bounded smoke test. |

These historical CloudFront results prove the infrastructure routing chain.
Only the separately identified application rehearsal supplies application
evidence; fixtures and synthetic Nginx responses do not upgrade that evidence.

## Activation sequence for the real application

Direct registry bootstrap is blocked in the school CloudShell environment.
The image-manifest preflight on 2026-10-01 used the image references from
`origin/main` commit `234c76470a8f254f162cc27449fcee11b9714dcb`:

| Command | Actual result |
| --- | --- |
| `docker manifest inspect minio/minio:RELEASE.2025-07-23T15-54-02Z` | Exit 1; registry denied access and required authentication. |
| `docker manifest inspect minio/mc:RELEASE.2025-07-21T05-28-08Z` | Exit 1; registry denied access and required authentication. |
| `docker manifest inspect mongo:8.0.12` | Exit 0; manifest accessible. |

These are real registry checks from AWS CloudShell, not EC2 container startup
evidence. They do not establish whether the MinIO tags are removed or require
additional registry credentials. No image was substituted. The deployment
owner must establish a retrievable, approved image source before a clean-host
Compose rehearsal can complete. A locally cached image does not prove that a
new AWS host can pull it.

### Original-image artifact delivery

The selected workaround preserves the original MinIO and client versions.
It transfers an exported Docker image archive through the operator's SSO
session and then over SSH to an x86 EC2 host. The host does not need an AWS
instance profile or Docker Hub credentials for `docker load`. This does not
change the Evidence adapter or migrate application data.

The archive contains only the two original images, not running-container
filesystems, Docker volumes, application secrets, or policyholder records.
Its size is 238092288 bytes. Its SHA-256 is
`1bfcf36dd0ad57648fba6466c4f6375bff9bf718b95d86db132c6c551f5476c7`.

| Image | Architecture | Image ID |
| --- | --- | --- |
| `minio/minio:RELEASE.2025-07-23T15-54-02Z` | `linux/amd64` | `sha256:a98a9d647e700e45c1d3d2e44709f23952a39c199731d84e623eb558fd5501f4` |
| `minio/mc:RELEASE.2025-07-21T05-28-08Z` | `linux/amd64` | `sha256:e1497f813d2de5084b2bd38df37f8e68a999be6af10b4c495ae7c3eaf081a9ce` |

The artifact-delivery checks on 2026-10-01 have distinct evidence levels:

| Check | Environment | Result |
| --- | --- | --- |
| Original image versions and synthetic write/restart/readback | Local Docker Desktop | Passed in an isolated temporary container; not AWS persistence evidence. |
| Archive export and manifest inspection | Local Docker Desktop | Passed; both original tags and image IDs are present. |
| Archive upload and SHA-256 comparison | School Sydney CloudShell | Passed; uploaded bytes match the local archive. |
| `docker load` and both version commands with `--pull=never` | School Sydney CloudShell | Passed; no replacement images or registry pulls were used. |
| Isolated MinIO server readiness after import | School Sydney CloudShell | Passed; no host port was published. |
| Archive transfer, checksum, import, and image IDs | Sydney EC2 without an instance profile | Passed; both image IDs and the archive hash match local evidence. |
| Synthetic write and container-restart readback | Sydney EC2 | Passed; object hash before and after restart is `a0775692a807c8c7e2c6ece136fee2c19c25d91726a13bb96b48d959fc5c484b`. |
| EC2 reboot and MinIO automatic recovery | Sydney EC2 | Passed; host uptime reset, MinIO was running, and object readback returned the same hash. |

The image references were rechecked against fetched `origin/main` commit
`eb51fc0285ab3e8051c3d0dba2413a0634e421ee`; both remain unchanged. This is
not an assertion that this application commit was deployed. The probe uses
Amazon Linux 2023, Docker, a `t3.micro`, a named Docker volume on the root EBS
disk, and an isolated network namespace. Neither MinIO port is published.
Instance Connect supplies the temporary SSH key; the security group admits
SSH only from the authorized CloudShell source address for this run.
The synthetic probe's development credentials are confined to that isolated
network namespace; they must not be reused for an exposed application.
The small probe instance does not establish capacity for the full Compose stack.
After the probe, EC2 state was confirmed `stopped`, its public address was
absent, and the security group had no remaining SSH rule. The CloudShell
probe container was stopped. The stopped EC2 instance and its root EBS volume
are retained for follow-up verification; storage charges continue. No claim
of full resource deletion or zero ongoing cost is made.

The reproducible image operations use these exact references:

```sh
docker save -o northwind-minio-original-images.tar \
  minio/minio:RELEASE.2025-07-23T15-54-02Z \
  minio/mc:RELEASE.2025-07-21T05-28-08Z
# Compare the transferred archive with its recorded release SHA-256.
sha256sum northwind-minio-original-images.tar
docker load -i northwind-minio-original-images.tar
docker run --rm --pull=never --network none \
  minio/minio:RELEASE.2025-07-23T15-54-02Z --version
docker run --rm --pull=never --network none \
  minio/mc:RELEASE.2025-07-21T05-28-08Z --version
```

Re-exporting can change archive serialization; record the checksum of the
actual frozen artifact rather than assuming every export has the hash above.
Use image IDs to check the loaded images independently of archive packaging.

The release procedure must verify the archive checksum before loading it,
verify both image IDs after loading, and prevent Compose from pulling these
two images again. The subsequent private S3 artifact copy was verified
separately from the frontend origin and does not make images public.
Keep an enduring operator-controlled copy of the archive before freezing a
release; a temporary local path or a CloudShell home directory is not a
durable release store. Retain the upstream license and source provenance.

### Remaining activation gates

This plan is not ready for deployment freeze. The rehearsal establishes
bounded startup, model calls, signed Evidence transport, RAG positive and
no-result behavior, three HTTP claimant-to-staff workflows, browser resumption,
container/host restart, and restored-volume readback on one pinned commit.
The remaining gates are distinct RAG timeout handling, confirmation of the
intended frozen release/configuration, full browser acceptance beyond the
tested conversation slice, and complete audit-envelope preservation checks.
CloudFront's 60-second origin-response budget also needs a long-model-request
test against the configured 180-second model budget. Successful short turns
do not establish that boundary. Do not treat these gaps as completed migration.
No data migration or application-code change was performed during this
preflight. Issue #1139 is closed for the accepted bounded infrastructure
validation. Issue #1163 owns the remaining full application activation gates
below; unresolved gates block deployment freeze. The numbered sequence is
the deployment order, not a claim that every step remains untested.

1. Launch one smallest suitable EC2 instance without an IAM role and attach an
   Elastic IP.
2. Use EC2 Instance Connect for bounded setup; never commit or bake credentials
   into an image.
3. Transfer and verify the original-image archive, load it on EC2, attach
   durable EBS storage, and run the existing `vp` Docker Compose profile with
   the imported MinIO images. Keep registry pulls for these images disabled.
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
