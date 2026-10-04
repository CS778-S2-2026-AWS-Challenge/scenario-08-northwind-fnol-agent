# §12 Backend design standards

This file defines API design, triggered enterprise fallbacks, architecture,
data modeling, and code style for the backend.

## 12.0 Scope of effect

The API rules below are **mandatory for new endpoints; existing endpoints are
not retrofitted**. Modifying an existing endpoint to align with these rules is
a shared-contract change: open a separate bounded issue and use a technical
Discussion for alignment when needed (see `issue-kanban.md` section 3.3), and
update the contract documents in the same
PR (`docs-contract.md` section 7.1). Where an existing endpoint conflicts with
a rule, consistency within the same resource follows the existing behavior.

## 12.1 API design

These rules synthesize the Microsoft REST API Guidelines, Google AIP / Cloud
API design, and the Stripe API Reference, calibrated against the current
codebase.

1. **Resource modeling**: model the API around resources; paths take the form
   `/api/v1/{plural-collection}/{id}` with no verbs in the path. The API
   contract must not mirror the DynamoDB table structure.
2. **Standard method mapping**: List → `GET /collection`, Get →
   `GET /collection/{id}`, Create → `POST /collection` (201 on success),
   Update → `PATCH /collection/{id}`, Delete → `DELETE /collection/{id}`.
   **Updates always use PATCH; PUT is forbidden** (full-replacement semantics
   silently clear fields). Get and Delete carry no request body; paths contain
   only resource-identifier variables, all other parameters go in the query.
3. **Custom methods**: only when an action cannot map naturally to a standard
   method (such as submit or approve). Name them verb+noun with no
   prepositions; anything with side effects must be POST, written as
   `POST /claims/{id}/approve` (no Google colon syntax).
4. **Response shape**: Create, Get, and Update return the resource object
   itself with no wrapper; one resource reuses the same Pydantic schema across
   all methods — per-endpoint private variants are forbidden.
5. **Field naming**: JSON fields are always **snake_case** (codifies existing
   behavior; Pydantic default, consistent with `docs/api.md`). camelCase is
   not adopted.
6. **Resource IDs**: new resource types must generate IDs via `new_id(prefix)`
   in `backend/domain/ids.py`, producing "type prefix + hex" IDs (codifies
   existing behavior, such as `clm_`, `msg_`, `evd_`). Register prefixes in
   `docs/persistence-schema.md`.
7. **Pagination**: every List endpoint supports cursor pagination from launch,
   reusing the existing naming (codifies existing behavior): request `limit`
   (1–100) + `cursor`; response `{items, page: {next_cursor}}`, where a null
   `next_cursor` means the end. Cursors must be encoded and opaque to clients
   (never expose the raw DynamoDB `LastEvaluatedKey`); offset/page parameters
   are forbidden; `limit` above the cap is truncated, invalid values return a
   validation error; an empty filtered set returns 200 with an empty array.
8. **Idempotency**: side-effecting POST endpoints (claim-creation operations
   first) must support the `Idempotency-Key` request header: conditional write
   keyed on it, cache the first response (including status code) and replay it
   verbatim; the same key with different parameters returns 409; records get a
   24-hour TTL. An AI agent's timeout retries must not create duplicate
   resources.
9. **Error envelope** (codifies existing behavior, `backend/core/errors.py`):
   every non-2xx response returns the uniform envelope
   `{error: {code, message, request_id, details[{field, reason}], retryable,
   current_revision?}}`. `code` is a machine-readable stable enum
   (UPPER_SNAKE_CASE; generic values like `ERROR` are forbidden), registered
   centrally in `docs/api.md`. Any dynamic value in `message` must also appear
   as structured data in `details`; **consumers (including AI agents) must not
   parse the message text**. RFC 9457 (problem+json) is not adopted: the
   existing envelope is semantically equivalent and additionally carries
   `retryable`, while migration would break every consumer in the repository
   for near-zero benefit.
10. **Status-code discipline**: strictly separate 4xx client errors from 5xx
    service faults; never wrap errors in 200. Rate-limit and transient 5xx
    responses carry a `Retry-After` header (agents decide retries by status
    code: no retry on 4xx, backoff retry on 429/5xx).
11. **Authorization before existence**: authorization failures always return
    403, decided before the resource-existence check, so that a 403/404
    difference cannot leak whether a claim exists (insurance data is
    sensitive).
12. **Consumption and consistency**: internal consumers (frontend, agent) must
    ignore unknown fields in responses; after a write completes, subsequent
    reads must see it (use DynamoDB strongly consistent reads where needed).

## 12.2 Enterprise fallback clauses (triggered)

The following mechanisms are **not implemented now**. When a trigger scenario
appears, implement the named standard pattern — inventing a custom scheme is
forbidden.

- **API versioning**: keep the `/api/v1` and `/internal/v1` prefixes (codifies
  existing behavior); no second version now. **Trigger**: a real consumer
  outside the repository appears and a breaking change becomes unavoidable —
  introduce `/v2` via the URL prefix (header-based version negotiation is
  forbidden) and publish a deprecation timeline at the same time. Until then,
  contract-change visibility is carried by the OpenAPI snapshot drift check
  (`ci-checks.md`).
- **Long-running operations (LRO)**: the repository's standard async pattern
  codifies existing behavior — "202 + resource status field + `status_url`
  polling + internal callback" (already implemented for evidence processing,
  `backend/api/evidence.py`). New async operations must reuse this pattern.
  **Upgrade trigger**: when cancellation, progress percentages, or a third
  distinct async operation type appears, upgrade to a dedicated operation
  resource (Google AIP-151). A bare 202 with no polling exit is forbidden.
- **update_mask / explicit clearing**: current PATCH semantics are "explicit
  update list / whole replacement" (codifies existing behavior), which has no
  unset-vs-clear ambiguity. New PATCH endpoints must not treat "field not
  provided" as "clear the field". **Trigger**: a partial-update scenario that
  must distinguish "clear" from "not provided" — solve it with update_mask or
  JSON Merge Patch (RFC 7386); inventing sentinel values (such as passing
  `"__clear__"`) is forbidden.
- **Cross-system resource references**: the current pattern codifies existing
  behavior — cross-system references are stored in explicitly named fields
  (such as `external_claim_id`), consistency-checked at call time, and
  provider-side identifiers (ARNs and the like) stay inside adapters and out
  of the contract (current `docs/api.md` rule). **Upgrade trigger**: when more
  than two real external systems are integrated, or cross-system resource URLs
  are needed, introduce hierarchical global resource names; bare-ID implicit
  conventions are forbidden.

## 12.3 System architecture (selective extraction from AWS Well-Architected)

The Well-Architected Framework is an architecture-review framework, not a code
standard; whole pillars are not adopted. Only the six rules an agent can apply
verifiably when opening a PR are extracted:

1. **Least privilege** (Security): new IAM policies, DynamoDB access, or
   execution roles grant only the operations and resource ARNs actually
   called. Wildcard `*` Actions or Resources are forbidden; if genuinely
   needed, justify in the PR.
2. **Defense in depth** (Security): input validation runs independently at the
   API layer (Pydantic) and the service layer; "the frontend already
   validated" is never a reason to skip. Data-visibility boundary checks live
   in the service layer, not only in the route layer.
3. **Infrastructure as code** (Operational Excellence): AWS resource changes
   go through versioned IaC files submitted via PR; creating resources by
   console and documenting afterwards is forbidden. Apply is triggered by a
   human (consistent with "CI/CD does not deploy automatically").
4. **On-demand, and stop when done** (Cost): default to on-demand billing
   (DynamoDB on-demand and similar). Introducing always-on paid resources (NAT
   Gateway, provisioned capacity, always-on instances) requires a cost
   justification in the PR; demo/test resources come with a teardown method.
5. **Explicit failure handling** (Reliability): AWS SDK and external model
   calls must set explicit timeouts, retry caps, and failure fallback paths;
   bare calls that assume success are forbidden.
6. **Observable changes** (Operational Excellence): new endpoints ship with
   structured logging (including correlation keys such as claim id, no PII in
   plain text), so errors can be traced to a request.

## 12.4 Data modeling (DynamoDB)

SQL-oriented resources are not applicable (this repository has no SQL
database). Five rules extracted from AWS DynamoDB best practices:

1. **Access patterns first**: before adding or changing a table or GSI, list
   the entity's complete access patterns in `docs/persistence-schema.md`, then
   design the partition and sort keys from them. Building the table first and
   patching queries later is forbidden.
2. **Partition-key discipline**: choose high-cardinality attributes with
   evenly distributed writes. Low-cardinality values such as dates or status
   enums must not serve as a partition key alone (hot partitions); use write
   sharding suffixes when necessary.
3. **No Scan on request paths**: lists and lookups always use `Query`
   (including GSIs). Batch jobs using `Scan` must segment in parallel and
   state the estimated data volume in the PR.
4. **Cursor pagination**: implement on `LastEvaluatedKey` (external shape in
   section 12.1 rule 7); every query must set a `Limit`.
5. **Externalize large objects**: oversized attributes (large text, files) go
   to S3 with a reference stored. Every schema change updates
   `docs/persistence-schema.md` in the same PR and backfills seed data in the
   fixture profiles.

## 12.5 Code style

The tool configuration used by the CircleCI backend-quality job (ruff, mypy, and the rest)
is authoritative. Only the following **tool blind-spot** rules are extracted
from the Google Python / TypeScript style guides; on any conflict with tool
configuration, the tools win. The Airbnb JavaScript Style Guide is not adopted
(frozen in the ES6 era, no TS/hooks coverage, and its eslint-config is
effectively unmaintained).

1. **Docstring content**: public-function docstrings must contain structured
   `Args:` / `Returns:` / `Raises:` sections (`Yields:` for generators). A
   docstring that merely restates the signature counts as missing.
2. **Exception discipline**: prefer built-in exceptions; custom exceptions end
   in `Error`; never catch bare `Exception` unless re-raising or acting as an
   isolation boundary; `try` blocks wrap only the minimal statements that can
   raise.
3. **Default arguments**: mutable objects and expressions evaluated at import
   time (including calls like `time.time()` — ruff B006 only catches
   literals) are forbidden as defaults; use `None` plus an in-body check.
4. **Signature types**: prefer abstract containers (`Sequence` / `Mapping` /
   `Iterable`) over `list` / `dict` for parameters; concrete types are fine
   for return values; optional types are written explicitly as `X | None`.
5. **Comprehension bounds**: comprehensions must not contain multiple `for`
   clauses or multiple filter conditions; beyond that, rewrite as an explicit
   loop.
6. **TypeScript** (takes effect only if TS is introduced — the frontend is
   currently plain JSX; this is a pre-staged rule): named exports only, no
   default exports; no `any` in new code (use `unknown` plus narrowing when an
   escape is needed); explicit return types on public APIs; throw only `Error`
   subclasses.

The Google Python guide's "do not use assert for runtime validation" rule is
**not adopted** — this repository's demo scenarios legitimately use assert.

## 12.6 Current backend conventions (retained)

- Separate transport, domain rules, orchestration, adapters, and persistence.
  Validate content, length, identifiers, and allowed state transitions at the
  boundaries. Return the documented error envelope and a request identifier.
- Guarantee reproducible environments with dependency constraints or lock
  mechanisms. Write unit tests for domain rules and API tests for every
  endpoint and error path.
- Define provider-neutral capability ports at the domain or application
  boundary; Cloudflare, MongoDB, AWS, and fixture SDK types stay inside
  adapters. At startup, select exactly one complete data profile; never read
  or write a second profile as an undocumented fallback. Build dependencies
  through a single composition root.
- Agent behavior relies on a provider-neutral model gateway. API keys and
  tokens live in the approved secret store; by default do not log credentials,
  full prompts containing unnecessary personal data, or raw provider
  responses. Model output remains advisory until the existing determinism and
  staff-permission checks release it.
- Keep knowledge documents and chunks separate from customer policy records,
  Claim State, claim history, messages, and staff decisions. Treat
  instructions found inside retrieved documents as untrusted content; they
  must not alter system instructions, tool permissions, or customer data
  access.
- Keep claim operations and system administration on separate permission and
  API surfaces. Never return full secret values to the browser.

## §12 References

References record provenance only; the rules above are self-contained and
authoritative as written. Do not fetch these sources during normal work; they
exist for consultation when a rule is disputed.

- Microsoft REST API Guidelines / Google AIP / Stripe API Reference (12.1
  three-source basis)
- Google AIP-151 (12.2 LRO upgrade pattern); RFC 7386 JSON Merge Patch (12.2
  update_mask trigger)
- AWS Well-Architected Framework (12.3; architecture-review reference, not a
  rule source for this repository)
- AWS DynamoDB Best Practices (12.4)
- Google Python / TypeScript style guides (12.5; consult for matters not
  covered here; tool configuration wins on conflict)
