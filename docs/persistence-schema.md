# Persistence Schema Draft

## Status and Boundary

This is a Sprint 1 design draft for the persistence boundary. It is a logical
model, not confirmation of an AWS table, index, region, identity, or service
configuration. Those facts remain open until the provided environment is
inspected.

The public API exposes domain identifiers and typed records only. It never
exposes partition keys, sort keys, index names, table names, object keys, or
provider payloads. Route handlers depend on `PersistenceRepository` rather
than a DynamoDB SDK.

## Logical Item Layout

The draft uses one logical record collection. A future adapter may use one or
more physical stores if it preserves these access patterns and repository
methods.

| Record | Logical partition | Logical sort | Required parent |
|---|---|---|---|
| Working claim | `CLAIM#<claim_id>` | `CLAIM` | customer ownership in the item |
| Session | `CLAIM#<claim_id>` | `SESSION#<session_id>` | claim and customer |
| Message | `CLAIM#<claim_id>` | `MESSAGE#<created_at>#<message_id>` | claim and session |
| Evidence | `CLAIM#<claim_id>` | `EVIDENCE#<evidence_id>` | claim |

Customer claim listing needs a logical customer lookup:
`CUSTOMER#<customer_id>` with `CLAIM#<created_at>#<claim_id>` ordering. Whether
this is implemented as a DynamoDB secondary index or another query mechanism
is intentionally undecided.

The key templates are implemented in
`backend/repositories/key_layout.py`. They are adapter internals and are not
part of HTTP request or response models.

## Required Access Patterns

1. Read one claim after verifying the authenticated customer owns it.
2. List a customer's working claims ordered by creation time.
3. Read one session under its claim and retain its resume revision.
4. Append and page messages for one claim/session, filtering visibility before
   claimant projection.
5. Read or list evidence under a claim without returning another customer's
   records.
6. Save a material claim revision only when the expected revision still
   matches; otherwise return a repository revision conflict.
7. Record idempotency results using actor, route, and client key.

## Record Rules

- All identifiers are server-generated except a claimant's retry key.
- Every child record carries its `claim_id`; messages also carry
  `session_id`.
- `MessageVisibility.INTERNAL_ONLY` is never returned by claimant APIs.
- Evidence stores metadata, provenance, processing state, and a secure object
  reference owned by the adapter. File bytes and signed upload URLs are not
  stored in the domain record.
- Claim and child writes must preserve ownership and optimistic-concurrency
  checks at the repository boundary.
- Complete messages remain durable; session summaries are bounded resume
  context, not a replacement for message history.

## Unknowns and Next Decision Points

- AWS identity provider, table/index availability, region, throughput model,
  retention, encryption, and object storage are unconfirmed.
- The physical mapping, serialization format, pagination token, retry policy,
  and transaction support must be selected after AWS access is inspected.
- A future DynamoDB adapter must implement `PersistenceRepository` and its
  contract tests without changing route handlers or claimant projections.
