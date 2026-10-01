# First AWS deployment framework and validation

This document is the current validation record for the first AWS deployment
framework selected in #1080. It is the source of truth for the scope of #1139.
It does not claim that the complete FNOL application is deployed until the
EC2 application path and the required browser journey have real evidence.

## Final framework

The first deployment uses AWS for static delivery, the host environment, and
deployment visibility while the existing application runtime remains intact:

```text
Browser
  -> CloudFront
     -> private Sydney S3 origin through Origin Access Control
        -> static claimant, Workbench, and Admin assets

Browser or API client
  -> HTTPS API origin at the EC2 host
     -> Docker Compose
        -> Backend / FastAPI
        -> MongoDB replica set
        -> MinIO
        -> existing external model gateway
```

CloudFront serves static assets only. It does not expose `/api/*`,
`/internal/*`, MongoDB, MinIO, Evidence objects, or knowledge objects. The API
origin needs its own HTTPS, certificate or DNS, reverse-proxy, and CORS
verification. The application keeps the existing provider-neutral model
gateway; this framework does not use Bedrock for model inference or retrieval.

The framework does not change Claim, Session, Message, Evidence, RAG,
permission, revision, or idempotency semantics. It also does not perform a
MongoDB/MinIO-to-AWS data migration.

## In-scope acceptance

| Area | Required evidence | Current state |
| --- | --- | --- |
| Sydney target | Resources and tests use `ap-southeast-2`; CloudFront remains global with a Sydney origin | `validated` for the bounded static check |
| Private static delivery | Synthetic asset uploads to private S3, CloudFront returns it, direct S3 access is denied | `validated` |
| EC2 host | Smallest suitable host launches and passes system checks with a bounded stop/cleanup plan | `validated` |
| Docker Compose | Existing repository Compose topology starts without an unreviewed contract change | `unreachable`; the MinIO client image could not be pulled |
| Backend | FastAPI liveness/readiness and configured runtime health are reachable on EC2 | `unconfigured`; Compose did not start |
| MongoDB | Existing replica set starts on EC2, survives restart, and reads back synthetic application state | `unverified`; backend stack did not start |
| MinIO | Existing Evidence and knowledge object paths work on EC2, survive restart, and read back synthetic objects | `unverified`; backend stack did not start |
| External model gateway | Existing configured gateway is reachable from the EC2 application and preserves current model boundary | `unverified`; backend stack did not start |
| HTTPS API and CORS | Browser-safe API origin, certificate/DNS or approved endpoint, reverse proxy, and CORS behavior are verified | `unconfigured` |
| Application journey | Claimant, Staff Workbench, and motor/home/contents paths complete against the EC2 runtime | `unverified` |
| Visibility and cost | CloudWatch visibility and budget alerts cover the resources actually used; non-essential resources can be stopped | `partially validated`; bounded synthetic monitoring evidence exists |

The framework is not complete until the rows marked `unreachable`,
`unverified`, or `unconfigured` have either real evidence or a concrete,
accepted external blocker. Local MongoDB, local MinIO, fixtures, mocks, and
console access cannot upgrade an AWS row.

## Current validation evidence

The validation used synthetic data and the exact current `origin/main` head
recorded in PR #1141. It confirmed:

- private S3-to-CloudFront delivery in Sydney;
- direct S3 access denial;
- EC2 launch and system checks;
- Docker and the Compose plugin installation on EC2;
- bounded CloudWatch and budget monitoring behavior.

The EC2 application check stopped before application startup. The repository
Compose dependency `minio/mc:RELEASE.2025-07-21T05-28-08Z` could not be pulled in
the checked environment. Temporary image-name substitutions were tried only
on the diagnostic copy and did not produce a successful application stack;
the repository Compose file was not changed. Consequently no claim is made
for Backend health, MongoDB/MinIO restart readback, the external model gateway,
HTTPS/CORS, or the full FNOL journey.

## Validation labels

| Label | Meaning |
| --- | --- |
| `validated` | A real bounded call or journey succeeded in the named AWS environment. |
| `permission_denied` | AWS returned an explicit authorization denial. |
| `unreachable` | The required endpoint or deployment path could not be reached. |
| `unconfigured` | A required resource or configuration does not yet exist. |
| `unverified` | The prerequisite path was blocked before this behavior could be tested. |
| `local_only` | Evidence came from local MongoDB, MinIO, a fixture, or a mock. |

## Out-of-scope capability probes

The following are deliberately not acceptance criteria for this framework:

- Bedrock model inference;
- Bedrock Knowledge Bases or any AWS retrieval provider;
- DynamoDB or a MongoDB-to-DynamoDB migration;
- ECS/Fargate;
- an S3 Evidence adapter;
- Lambda/EventBridge in the core Claim journey;
- AWS provider enablement or application/API/schema changes.

Earlier console or synthetic probes for these services may remain in private
operator notes as historical capability observations. They must not be called
deployment evidence, migration prerequisites, or blockers for #1139.

## Activation sequence

1. Resolve the EC2 Compose image dependency without changing application
   contracts or silently substituting an unreviewed image.
2. Start the existing Compose topology and verify Backend health, MongoDB and
   MinIO persistence after restart, the external model gateway, and the
   synthetic Evidence/RAG paths.
3. Configure and verify the HTTPS API origin, reverse proxy, and CORS policy.
4. Publish static clients to the private S3 origin and verify browser calls to
   the separately protected API origin.
5. Run the three FNOL paths and Staff Workbench journey against the EC2 host.
6. Record CloudWatch, budget, stop, cleanup, and rollback evidence for the
   resources actually used.

## Safety and migration boundary

Use one smallest suitable EC2 host, synthetic data, bounded logs, and stopped
resources outside demonstrations. Keep credentials, endpoints, account
identifiers, and policyholder data out of repository and GitHub evidence.
Evidence bytes and governed knowledge objects remain behind the existing MinIO
boundary for this first framework. No application data migration is part of
this validation.
