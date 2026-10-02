# AWS Deployment Plan

This document records the current AWS deployment plan for the Northwind FNOL
Agent. It describes a bounded demonstration deployment using synthetic data.
It is not a production rollout and it does not perform application-data
migration.

## Current Deployment Framework

The application is hosted on one Sydney EC2 instance. CloudFront is the public
HTTPS entry point. Static frontend assets are served from a private S3 bucket;
the application runtime remains the existing Docker Compose topology.

```text
Browser
  -> CloudFront HTTPS
     -> /                         private S3 origin through OAC
        -> claimant and Staff Workbench static assets
     -> /api/*                    EC2 custom origin over HTTP
        -> Nginx
           -> Backend / FastAPI
              -> MongoDB replica set
              -> MinIO
              -> existing external model gateway
     -> /northwind-evidence/*     EC2 -> signed MinIO object path
```

The deployment uses Sydney (`ap-southeast-2`) for regional resources.
CloudFront is global. CloudFront serves the static frontend from the private
S3 origin and routes API and signed Evidence requests to the EC2 origin.
MongoDB and MinIO administration ports remain bound to the EC2 host. The
`/internal/*` surface is not exposed through CloudFront.

The current application semantics remain unchanged. This deployment does not
change Claim, Session, Message, Evidence, RAG, permission, revision,
idempotency, or audit contracts.

## AWS Resources In Scope

| Resource | Purpose | Current use |
| --- | --- | --- |
| CloudFront | Public HTTPS entry point and path routing | Static frontend, API, and signed Evidence paths |
| Private S3 bucket | Static frontend origin | Built claimant and Staff Workbench assets; direct public access denied |
| EC2 | Host for the application stack | Backend, MongoDB, MinIO, Nginx, and deployment files |
| EBS | EC2 boot and application data volumes | MongoDB, MinIO, SQLite control-plane data, and recovery artifacts |
| VPC, subnet, and security group | Network boundary | Restrict EC2 access to required demonstration paths |
| Elastic IP | Stable EC2 origin address | Stable origin address while the test host is active |
| EC2 Instance Connect | Temporary host administration | Short-lived SSH access for bounded deployment operations |
| CloudShell | AWS control-plane and deployment shell | AWS CLI and bounded operator commands |
| Docker Compose | Runtime composition | Backend, MongoDB, MinIO, initialization, and recovery services |
| External model gateway | Agent model inference | Existing provider-neutral gateway; the actual configured model is external GPT-4o |
| AWS Budgets | Cost visibility | Existing team budget plus the separate validation cost guard |

The application uses its existing MongoDB, MinIO, and external model-gateway
boundaries.

## Permission Boundary

The course SSO identity is:

- Role: `ICTGSStudentPermissionSet`
- Regional resources: `ap-southeast-2`

The account identity is retained only in the private operator evidence and is
not committed here.

The current identity can operate the bounded CloudFront, S3, EC2, networking,
CloudShell, and budget resources used by this plan. It cannot pass an EC2 IAM
role for the application host. Pre-created roles exist in the account, but the
current deployment does not depend on attaching one. EC2 Instance Connect is
used for short-lived host access.

No teaching resources related to AWSAccelerator, ControlTower, or CloudHealth
are modified. No credentials, access keys, private keys, `.env` files, or
runtime secret values are committed to the repository.

## Runtime Configuration

The EC2 host runs the existing provider-neutral Compose deployment:

- Backend / FastAPI serves the application API.
- MongoDB replica set stores Claim, Session, Message, workflow, revision,
  idempotency, and application audit state according to the current local MVP
  contract.
- MinIO stores Evidence bytes and governed policy-knowledge objects.
- SQLite volumes retain the existing identity and control-plane state.
- The existing external model gateway provides model inference.
- Nginx supplies the EC2 HTTP origin and the signed Evidence routing boundary.

Secrets are supplied only through a protected operator-side deployment
mechanism during a test run. They are not stored in GitHub, S3 static assets,
CloudFront configuration, or frontend code.

## Historical Application Rehearsal Evidence (2026-10-02)

This is the latest successful application rehearsal recorded for this plan. It
used synthetic data and pinned application commit
`f1b897d76dbb3d5d854b6172c7cc49907e3f902a` on a Sydney `t3.small`. It is
historical evidence for that exact release, not evidence that the current
`origin/main` or a future frozen release has already been deployed.

| Check | Result | Boundary |
| --- | --- | --- |
| Private S3 to CloudFront | Passed | Static synthetic content was served through CloudFront; direct S3 access was denied |
| CloudFront API routing | Passed | `/api/health` reached the EC2 origin through CloudFront |
| EC2 host | Passed | Small test instance started and returned healthy system and instance status |
| EC2 administration | Passed | EC2 Instance Connect accepted a short-lived public key and an SSH command completed |
| Compose initialization | Passed | Backend, MongoDB, and MinIO became healthy; initialization completed |
| Backend readiness | Passed with degraded status | Persistence and object services were available; existing fixture-backed services remain explicit |
| External model gateway | Passed | Live structured request used the configured external GPT-4o gateway |
| Motor, home, and contents workflows | Passed for bounded HTTP journeys | Account/session, model turn, Evidence upload/completion, support request, staff reply, and claimant readback completed |
| Claimant browser path | Passed for bounded coverage | Registration, model reply, and synthetic JPEG upload reached `Ready` |
| Staff Workbench | Passed for bounded coverage | Staff login and all three product conversations were visible after recovery |
| Governed RAG | Passed against MinIO | Citations contained document, chunk, version, checksum, and source metadata; missing evidence returned `no_evidence` |
| Container and host restart | Passed | Revision, messages, Evidence checksum, and claim-creation replay survived restart and EC2 reboot |
| Backup and restore rehearsal | Passed | MongoDB, MinIO, and SQLite data restored to separate named volumes and read back |
| Cost guard | Configured and read back | Validation budget covers the existing baseline plus an additional USD 200; actual-cost thresholds are configured |
| Failure handling | Passed for bounded checks | Model timeout returned a retryable timeout; unavailable MinIO returned `unavailable` with zero citations; fixture fallback was refused |

These results demonstrate the bounded test deployment. They are not a claim
that the service is a production-ready, always-on system.

## Evidence and RAG Boundary

Evidence is uploaded through the signed application path and stored in MinIO.
The application records the claim/evidence association, checksum, and object
metadata in its existing persistence contract. Unsigned object access is
denied.

Governed policy knowledge is initialized into MinIO using the current local
knowledge contract. Retrieval returns citations with document, chunk, version,
checksum, and source metadata. A missing applicable document returns
`no_evidence`; an unavailable knowledge service returns `unavailable` without
fabricating citations.

The external model gateway remains the model boundary. AWS hosting does not
change the selected inference provider.

## Operational Boundaries

The deployment is intended for a bounded synthetic-data demonstration. Before
each demonstration, the operator must verify the current application release,
the model-gateway configuration, the EC2 host state, the Compose health state,
the CloudFront distribution state, and the active cost guard.

The API origin currently uses HTTP between CloudFront and EC2 for the bounded
test path. A production deployment would require a trusted certificate and a
DNS name for the EC2 origin. This plan does not claim end-to-end TLS from
CloudFront to EC2.

The deployment must not expose MongoDB, MinIO administration, SQLite files,
runtime secrets, or internal application endpoints to the public Internet.
Evidence remains accessible only through the application-authorized signed
path.

## Known Limits

- The rehearsal was performed against the pinned release stated above. It is
  not evidence for a newer unreconciled `origin/main` release.
- The external model timeout is bounded at the application gateway. A long
  request still needs a separate end-to-end acceptance decision if the final
  demonstration requires requests longer than the CloudFront origin budget.
- The current object-store adapter records a controlled RAG read timeout as
  `unavailable`; a separate timeout classification is not claimed.
- Browser evidence covers the bounded claimant and Workbench paths, not every
  browser route or an external insurer submission.
- Audit preservation after restart and restore requires a separate field-level
  acceptance check before production use.
- Retained EBS volumes, private S3 artifacts, and other retained test objects
  can continue to incur storage charges after the active compute resources are
  stopped.

## Cleanup and Cost Control

The active test environment must be stopped when it is not being demonstrated.
Temporary SSH ingress, public addresses, and CloudFront test exposure must be
removed after a bounded run. Retained data volumes and private artifacts must
be reviewed separately because stopping EC2 does not stop their storage cost.

The pre-existing team budget named `Budget` is a school-managed annual cost
budget and is already above its nominal USD 200 amount. It is retained as
account-level cost information and is not treated as evidence that this
validation deployment created the historical spend. The separate Northwind
validation cost guard is the relevant monitor for this work.

## Future Demonstration Acceptance Checklist

This remains a future acceptance checklist. It is not a claim that every item
is currently satisfied for the next frozen release:

1. CloudFront serves the private S3 frontend and routes the required API and
   signed Evidence paths.
2. EC2 starts the existing Compose topology with healthy Backend, MongoDB, and
   MinIO services.
3. Motor, home, and contents workflows complete with synthetic data.
4. Evidence checksums, governed RAG citations, revision, idempotency, and
   restart readback remain consistent with the existing application contract.
5. The external model gateway is available and its configured release is
   recorded.
6. Cost monitoring is visible and the environment is stopped after the test.

No data migration, new AWS persistence adapter, new model provider, or change
to the existing business lifecycle is required by this deployment plan.
