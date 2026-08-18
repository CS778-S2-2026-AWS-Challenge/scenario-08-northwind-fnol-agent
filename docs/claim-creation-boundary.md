# Claim Creation and AWS Adapter Boundary

## Purpose

This record defines the Day 1 claim-creation boundary for Issue #102. It separates
verified fixture behaviour from a future configured claims service and records unknown
AWS behaviour without presenting it as fact.

## Current capability status

| Capability | Current status | Evidence and boundary |
|---|---|---|
| Provider-neutral create contract | available | `POST /internal/v1/claims/create` accepts only domain fields and rejects provider-specific infrastructure fields. |
| Controlled claimant creation path | available | `POST /api/v1/claims/{claim_id}/creation` derives its request from confirmed persisted state. |
| Fixture claim creation and routing | using fixture | The deterministic adapter returns status, route, next step and `source: fixture`. |
| Configured insurer claims service | unavailable | No insurer endpoint, credential or provider schema has been supplied. |
| AWS claims-service implementation | pending confirmation | Account, region, service choice, IAM policy, network path and physical schema have not been verified. |

`Unavailable` means a required provider input is absent now. `Pending confirmation`
means the implementation choice or AWS environment has not yet been inspected. Neither
state permits the system to fabricate a provider result.

## Stable create and route contract

The public creation operation has no provider payload. Lambda or another orchestration
layer must derive the provider-neutral command from the authorised `WorkingClaim` and
invoke a `ClaimsServiceAdapter` implementation.

Every successful or pending result contains:

- `creation_status`: `created`, `pending`, or `failed`;
- `route`: the configured processing route, not a coverage or liability decision;
- `next_step`: the claimant-visible action after the provider call;
- `source`: `fixture` or `configured_service`;
- provider references and expected timing when available.

The fixture result uses `source: fixture`. A future adapter may use
`source: configured_service` only after its endpoint, credentials, permissions and
response mapping have been verified.

## Authority and failure behaviour

- Claim creation requires confirmed required facts, the current revision and a
  deterministic `CREATE_CLAIM` authorisation.
- The working claim ID is the provider-neutral idempotency reference. A retry restores
  the same result; changed input under the same reference is rejected.
- Pending evidence remains outstanding work and is not silently discarded.
- A model proposal, severity value or claimant-supplied identifier cannot authorise
  creation or assessor routing.
- An unavailable configured service must return the documented dependency error and
  preserve the working claim. It must not be reported as a successful AWS call.

## Fixture fallback

The fixture adapter implements the same typed boundary as a future configured adapter.
It generates synthetic claim references, preserves route and next-step fields and marks
the response source explicitly. This keeps the demonstration repeatable without
claiming that Northwind or AWS production integration exists.

## Open AWS confirmations

The following remain outside the verified boundary until the provided environment is
inspected: AWS service selection, region, account and IAM permissions, DynamoDB table
layout, network connectivity, secrets handling, retry limits, provider timeout mapping,
operational ownership and production retention. These are recorded as
`pending_confirmation`, not inferred from the fixture implementation.
