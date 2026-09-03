# Northwind FNOL API Contract

<!-- Existing API tables use compact pipe formatting; preserve that contract while extending it. -->
<!-- markdownlint-disable MD060 -->

## Document Status

| Item | Value |
|---|---|
| Contract version | `0.1.0` |
| API base path | `/api/v1` |
| Internal base path | `/internal/v1` |
| Status | Current versioned transport contract |
| Data | Anonymous or synthetic data only |
| Authority | Initial SPEC, then this contract for transport and schema details |

This document is the normative API contract for the current Northwind FNOL service. It defines the boundary shared by the claimant client, claim operations workbench, agent orchestration, backend domain layer, and replaceable integration adapters.

This contract defines the normative routes under `/api/v1` and `/internal/v1`. A route is treated as implemented only when the verification requirements in this document are satisfied; historical shell routes and dated delivery evidence do not override the contract. New Administration and Control Plane, model-gateway, or knowledge-management routes become normative only when their implementation, consumers, fixtures, tests, and this document change together.

The key words **MUST**, **MUST NOT**, **SHOULD**, and **MAY** describe requirement strength. A contract change MUST update affected clients, server code, fixtures, automated contract tests, and this document in the same pull request.

## Product Boundary

The API supports a trusted, adaptive first-notice-of-loss service. It must preserve one shared claim state while allowing:

- natural-language intake with internal structured Claim State and correction of material misunderstandings;
- fast, guided, professional-review, urgent, human-request, pending-evidence, resume, and fraud-review paths;
- image and document evidence;
- policy and relevant claim-history retrieval with source evidence;
- context-preserving human handoff;
- mock or configured claim creation and conditional assessor routing;
- an internal workbench derived from the same claim state;
- measurement of claimant, agent, and staff effort.

The broader product includes an Administration and Control Plane for versioned system configuration. The bounded Admin API below is restricted to configuration metadata and lifecycle operations; it remains separate from claimant and staff claim operations.

The API does not authorise the agent to approve or reject claims, make an unreviewed high-impact coverage decision, determine fraud, diagnose injury, or claim that emergency services were contacted when they were not.

## Actors and Access

| Actor | Permitted boundary |
|---|---|
| Claimant | Their own claimant-visible claim data, sessions, messages, form corrections, evidence, support requests, and status updates |
| Claims professional | Assigned or permitted workbench claims, internal evidence, handoffs, signals, staff actions, and claimant updates |
| Claims operations | Workbench data, routing and service metrics, subject to operational role permissions |
| System administrator | Versioned system configuration, knowledge, integrations, access, evaluation, health, and audit through a separately contracted Admin API |
| Release approver | Independent publication approval for high-impact configuration; must not be the configuration's sole author |
| Agent service | Claim-scoped orchestration commands and approved internal tools; no unlimited decision authority |
| Integration service | Narrow adapter operation for policy, history, claim creation, evidence storage, or assessor systems |

### Authentication and Authorisation

- All endpoints except liveness and readiness MUST require an authenticated principal.
- Production identity requires an approved identity provider; the exact provider and deployment remain open.
- Development and fixture environments MAY use signed synthetic identities, but the server MUST still enforce role and claim ownership. A client-supplied `customer_id`, role, or staff identity MUST NOT grant access.
- Claimant access MUST be restricted to claims linked to the authenticated claimant.
- Internal routes MUST reject claimant credentials.
- In the fixture environment, internal integration routes use a separate
  `NORTHWIND_SYNTHETIC_INTEGRATION_TOKEN`. This synthetic token is not a production
  identity design and is disabled outside development and test environments.
- Sensitive fields MUST be filtered by the server, not hidden only in the frontend.

The MVP development/test identity adapter provides two explicitly synthetic claimant accounts.
With `NORTHWIND_IDENTITY_MODE=developer` enabled, `POST /api/v1/auth/sessions` validates the
synthetic credential server-side and returns a
short-lived opaque bearer token. Only its hash, authenticated `customer_id`, expiry, and
revocation state are retained by the server. Claimant clients keep this token in memory only.
The adapter is unavailable outside development and test; it is not a production identity
provider or a production-readiness claim. The legacy fixed claimant token remains a bounded
fixture compatibility credential while existing scenario clients migrate, and is likewise
disabled outside development and test.

Current scopes:

| Scope | Purpose |
|---|---|
| `claim:read:self` | Read the claimant's own claim projection |
| `claim:write:self` | Add messages, corrections, evidence, and support requests |
| `workbench:read` | Read authorised internal claim projections |
| `workbench:write` | Assign work, decide signals, resolve handoffs, and update claim state |
| `operations:read` | Read aggregate operational metrics |
| `agent:execute` | Run claim-scoped agent orchestration |
| `tools:invoke` | Invoke allow-listed integration adapters |

## Data Visibility

Every persisted field belongs to one visibility class.

| Visibility | Examples | Claimant API | Workbench API |
|---|---|---|---|
| `claimant_visible` | Claim status, form values, evidence status, next step, staff updates | Included | Included |
| `shared` | Confirmed incident facts, provenance, messages intended for both parties | Included when relevant | Included |
| `internal_only` | Fraud-review signals, internal routing, staff notes, model reasoning, internal confidence | Never included | Included only for authorised roles |

The claimant API MUST NOT return fraud-review signals, internal tags, internal notes, raw policy reasoning, other customers' history, or hidden model reasoning. It SHOULD explain customer-relevant uncertainty in plain language without exposing a sensitive internal label.

## Protocol Conventions

### Transport

- HTTPS is required outside local development.
- JSON requests use `Content-Type: application/json`.
- Dates and times use RFC 3339 UTC strings, for example `2026-08-10T03:42:10Z`.
- IDs are opaque strings and MUST NOT encode personal data.
- JSON property names use `snake_case`.
- Optional fields are omitted when unknown unless the schema explicitly permits `null`.
- Unknown request fields SHOULD be rejected with `VALIDATION_ERROR` during prototype development.

### Required Headers

| Header | Requirement |
|---|---|
| `Authorization: Bearer <token>` | Required except health endpoints |
| `X-Request-ID` | Optional from client; generated by server when absent and always returned |
| `Idempotency-Key` | Required for state-changing `POST` requests |
| `If-Match: "<revision>"` | Required when a request changes an existing claim |

An idempotency key is scoped to the authenticated actor, HTTP method, and route for at least 24 hours. Reuse with the same request returns the first result. Reuse with a different request returns `409 IDEMPOTENCY_CONFLICT`.

Every claim-state response includes `revision`. A stale `If-Match` value returns `409 REVISION_CONFLICT` with the current revision. Internal adapters MUST NOT bypass this protection when writing shared state.

### Pagination

Collection endpoints accept:

| Query | Type | Rule |
|---|---|---|
| `limit` | integer | Default `25`, minimum `1`, maximum `100` |
| `cursor` | string | Opaque continuation cursor |

Collection response:

```json
{
  "items": [],
  "page": {
    "next_cursor": null
  }
}
```

### HTTP Status Codes

| Status | Use |
|---|---|
| `200` | Successful read or state change |
| `201` | Resource created |
| `202` | Accepted asynchronous operation |
| `204` | Successful operation with no response body |
| `400` | Malformed request or invalid transition |
| `401` | Missing or invalid authentication |
| `403` | Authenticated but not authorised |
| `404` | Resource not found or deliberately concealed |
| `409` | Revision, idempotency, or state conflict |
| `413` | Upload exceeds configured limit |
| `415` | Unsupported media type |
| `422` | Schema validation failed |
| `429` | Rate limit exceeded |
| `500` | Unexpected server error |
| `502` | Required integration failed |
| `503` | Service or required dependency unavailable |

## Administration and Control Plane API

The administration surface is available under `/internal/v1/admin` and requires an authenticated
administrator principal with both `admin:read` and `admin:write` scopes. It never reads or writes
Claim State, WorkItems, handoffs, or claimant messages.

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/internal/v1/admin/configurations` | List current configuration revisions, optionally filtered by `domain` |
| `POST` | `/internal/v1/admin/configurations` | Create a new draft configuration; requires `Idempotency-Key` |
| `GET` | `/internal/v1/admin/configurations/{configuration_id}` | Read a configuration revision |
| `PATCH` | `/internal/v1/admin/configurations/{configuration_id}` | Create a new draft revision; requires `If-Match` |
| `POST` | `/internal/v1/admin/configurations/{configuration_id}/validate` | Validate a draft against supplied scenario results; requires `If-Match` and `Idempotency-Key` |
| `POST` | `/internal/v1/admin/configurations/{configuration_id}/publish` | Publish an approved high-impact draft; requires `If-Match` and `Idempotency-Key` |
| `POST` | `/internal/v1/admin/configurations/{configuration_id}/withdraw` | Withdraw a draft or published revision; requires `If-Match` and `Idempotency-Key` |
| `POST` | `/internal/v1/admin/configurations/{configuration_id}/rollback` | Publish an approved prior revision as a new record; requires `If-Match` and `Idempotency-Key` |
| `GET` | `/internal/v1/admin/configurations/{configuration_id}/audit` | Read append-only lifecycle audit events |

Configuration records contain an opaque `configuration_id`, monotonically increasing `revision`,
`domain`, `impact`, lifecycle `state`, non-secret `values`, protected `secret_references`,
`author`, `reason`, optional `validation_evidence`, `effective_time`, `previous_version`, and
`rollback_target`. Secret values are rejected in `values` and are never returned.

Lifecycle states are `draft`, `awaiting_approval`, `published`, `withdrawn`, or `superseded`.
Validation accepts explicit results for each named scenario, including evidence. A failed result
is recorded and returns `422 VALIDATION_FAILED` without changing the configuration state. A normal-
impact draft publishes after all supplied scenarios pass; a high-impact draft moves to
`awaiting_approval` and requires an explicit publish operation by an identity other than its sole
author. An author publication attempt returns `403 CONFIGURATION_APPROVER_CONFLICT` and leaves the
record awaiting approval. Every transition, including a
rejected transition, records actor, reason, outcome, revision, prior revision when applicable,
top-level changed fields, and timestamp in the audit collection. Changed-field metadata names
fields only and never copies configuration or secret values. State-changing POST requests require
`Idempotency-Key`; replaying the same request
returns the original response and reusing a key with different parameters returns `409
IDEMPOTENCY_CONFLICT`. Stale or missing/invalid `If-Match` values return `409 REVISION_CONFLICT` or
`409 REVISION_REQUIRED`; missing resources return `404 CONFIGURATION_NOT_FOUND`; invalid state
changes return `400 INVALID_CONFIGURATION_TRANSITION`; plaintext secrets return
`422 SECRET_VALUE_FORBIDDEN`.

For the `data_profile` domain, `values` is a closed object containing exactly
`data_runtime_profile` (`fixture`, `local_mvp`, `cloudflare`, `mongodb`, or `aws`) and
`object_storage_adapter` (`fixture` or `s3_compatible`). The compatibility matrix is:
`fixture` → `fixture` or `s3_compatible`; `local_mvp`, `cloudflare`, `mongodb`, and `aws` →
`s3_compatible`. This prevents incoherent mixed-provider bundles. Unverified cloudflare,
mongodb, and aws profiles may be retained as drafts for configuration review, but validation
returns `422 PROVIDER_CONFIGURATION_UNAVAILABLE` and they cannot be published. Invalid fields or
combinations return `422 PROVIDER_CONFIGURATION_INVALID`.

For the `model` domain, `values` is a closed provider-neutral object containing
`protocol`, `provider`, `model_identifier`, `base_url`, `credential_environment_variable`,
`profile_id`, `purpose`, `privacy_class`, `prompt_version`, `evaluation_status`,
`timeout_seconds`, `structured_output`, and `tools`. The credential field contains only an
environment-variable name; the secret itself remains outside the configuration record. Every
model configuration must declare `impact=high`; an omitted or normal impact returns `422
PROVIDER_CONFIGURATION_INVALID` and cannot enter the lifecycle. Model validation permits
publication only when `evaluation_status` is `configured`; protocol, base URL, and credential
environment-variable name match the deployment-owned startup settings; and purpose, privacy
class, executable prompt identifier, and structured-output capability match the claimant Runtime
contract. The current executable prompt identifier is `northwind-fnol-motor-claimant-v3`. A
degraded, unavailable, deployment-mismatched, or Runtime-incompatible profile returns `422
PROVIDER_CONFIGURATION_UNAVAILABLE` and remains a draft. Other invalid or incomplete model values
return `422 PROVIDER_CONFIGURATION_INVALID`.

Runtime consumers use the provider-neutral configuration service to read the single active
`published` record for a domain. Draft, awaiting-approval, withdrawn, superseded, and unverified
provider records are never returned by that boundary. The model runtime resolves the active
published `model` record before each provider request, so a configuration published after startup
becomes effective for the next turn. A process without a published model record may use its
explicit startup model settings as a bootstrap-only compatibility path; it never combines fields
from a draft or superseded record. The runtime repeats the deployment-binding check before
constructing a provider adapter or reading a credential environment variable. A stored published
record cannot redirect a deployment-approved credential to another endpoint or weaken the
claimant Runtime's purpose, privacy, prompt-version, or structured-output boundary.

## Claimant Identity and Account API

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/auth/sessions` | Authenticate a development/test synthetic claimant and create an opaque session |
| `GET` | `/auth/session` | Read the current authenticated claimant session |
| `DELETE` | `/auth/session` | Revoke the current claimant session |
| `GET` | `/account` | Read the authenticated claimant's profile and communication preferences |
| `PATCH` | `/account/profile` | Update the authenticated claimant's approved profile fields |
| `PATCH` | `/account/preferences` | Update the authenticated claimant's communication preferences |

`POST /api/v1/auth/sessions` is the only development/test authentication exception to the
general bearer requirement. It accepts `email` and `password`, returns `201` with
`customer_id`, `access_token`, `token_type`, `expires_at`, and `development_identity: true`,
and returns the same bounded `401 AUTHENTICATION_REQUIRED` response for unknown email and bad
password. The request cannot supply `customer_id`, role, scopes, or claim ownership.

All other routes above require the issued bearer token. Expired, invalid, and revoked tokens
return `401`. Logout revokes the server-side session and returns `204`. Account responses are
derived from the authenticated principal and never accept a customer identifier in their path
or payload. Profile updates accept `display_name` and `phone`; preference updates accept the
boolean `email` and `sms` fields. These fixture records contain anonymous `.invalid` addresses
only and must not be represented as real Northwind customer data.

## Shared Types

### Resource Relationships

```text
Customer
  \-- Working Claim
        |-- Session
        |     \-- Message
        |-- Structured Form Field
        |-- Evidence
        |-- Agent Decision
        |-- Internal Signal
        |-- Handoff
        |-- Staff Action
        |-- Claimant Update
        |-- Claim Event
        |-- External Claim Reference
        |-- External-service Consent
        \-- Assessor Routing Result
```

A `Working Claim` is the authoritative FNOL record owned by this product. An `External Claim Reference` exists only after the configured claims service accepts claim creation. A session is a period of interaction with the working claim; ending a session does not end or duplicate the claim.

All claim-scoped child records MUST carry `claim_id`. Session messages MUST also carry `session_id`. Persistence may denormalise read projections, but the API and event history retain these relationships.

### Identifiers

Examples use readable prefixes, but clients MUST treat all identifiers as opaque.

| Resource | Example |
|---|---|
| Customer | `cus_01J4Y7M8M6` |
| Claim | `clm_01J4Y7Q2AW` |
| Session | `ses_01J4Y7RPN8` |
| Message | `msg_01J4Y7T1KC` |
| Evidence | `evd_01J4Y7V5QJ` |
| External task | `tsk_01J4Y7VZ82` |
| External request | `erq_4d29a6dbafdf5ed57152f15c` |
| Decision | `dec_01J4Y7W90S` |
| Handoff | `hnd_01J4Y7XG2C` |
| Signal | `sig_01J4Y7Z0EH` |
| Staff action | `act_01J4Y80B7D` |
| Claim event | `evt_01J4Y81HNM` |

### Current Agent Action Compatibility

The currently implemented transport field `AgentAction` is one of:

```text
ASK | CLARIFY | CONFIRM | PROCEED | UPDATE | HANDOFF | URGENT_HANDOFF | CREATE_CLAIM
```

This flat enum is retained for compatibility with current clients, fixtures, and stored
Agent Decisions. It must not be extended as the foundation of new Agent behaviour.
Policy lookup, history lookup, evidence extraction, claim creation, and assessor routing
remain tools or side effects in the current transport.

The target product action system uses separate `conversation`, `claim`, `human`,
`external`, and `runtime` namespaces and permits several conversation moves and command
proposals in one turn. It requires a coordinated transport migration described under
the internal Agent turn boundary below. No target field or route is treated as
implemented merely because it is described in the design documents.

### Claim State

The canonical internal claim state keeps independent dimensions. It MUST NOT collapse them into a single route label.

```json
{
  "severity": "standard",
  "coverage": "clear",
  "evidence": "pending_generation",
  "fraud_signal": "none",
  "customer_support": "guided",
  "urgency": "normal",
  "workflow_state": "ready_for_next",
  "next_action": "CREATE_CLAIM"
}
```

| Field | Allowed values | Visibility |
|---|---|---|
| `severity` | `unassessed`, `fast_track`, `standard`, `complex` | ... |
| `coverage` | `not_assessed`, `clear`, `ambiguous`, `review_required` | ... |
| `evidence` | `not_started`, `received`, `unofficial`, `incomplete`, `pending_generation`, `inconsistent` | ... |
| `fraud_signal` | `none`, `review_required` | Internal only |
| `customer_support` | `self_service`, `guided`, `human_requested`, `accessibility_required` | Shared when relevant |
| `urgency` | `normal`, `urgent`, `immediate_safety_risk` | Shared, with internal routing detail excluded |
| `workflow_state` | `collecting`, `ready_for_next`, `awaiting_evidence`, `professional_review`, `created` | Shared through role-appropriate wording |
| `next_action` | `AgentAction` | Internal action; claimant receives `customer_next_step` |

A newly created claim should initialise `severity = unassessed`, `coverage = not_assessed`, and `evidence = not_started`.

### Working Claim

The canonical backend record has these fields. API projections omit fields the caller is not authorised to see.

| Field | Type | Required | Rule |
|---|---|---:|---|
| `claim_id` | string | Yes | Server-generated working claim identifier |
| `customer_id` | string | Yes | Derived from authenticated identity; never trusted from a claimant request |
| `revision` | integer | Yes | Starts at `1` and increases on every material state change |
| `channel` | enum | Yes | Initial value `web_agent`; future channels require a contract change |
| `locale` | string | Yes | BCP 47 language tag such as `en-NZ` |
| `incident_type` | string | No | Registered claim-family projection; may be unknown at creation. Branch evaluation reconciles it with the source-aware `incident.type` form field and does not treat a matching proposed or disputed model-derived value as confirmed. |
| `claim_state` | `ClaimState` | Yes | Canonical internal multi-dimensional state |
| `form` | field map | Yes | Registered field code to `StructuredFormField`; initially empty |
| `evidence_summary` | `EvidenceSummary` | Yes | Authoritative aggregate over the full persisted evidence set; claimant projections recompute it from claimant-visible evidence only |
| `route` | string | No | Configured processing route, not a decision outcome |
| `active_session_id` | string | No | Current active session when one exists |
| `external_claim` | object | No | Claim service result after creation begins |
| `external_service_consents` | array | Yes | Internal task-specific consent records; omitted from claimant projections |
| `assessor_routing` | object | No | Provider-neutral assessor result after an authorised request succeeds |
| `customer_next_step` | object | Yes | Claimant-safe status, responsibility, and expected timing |
| `created_at` | timestamp | Yes | Server-generated creation time |
| `updated_at` | timestamp | Yes | Server-generated last material update time |

`external_claim` contains `external_claim_id`, `claim_number`, `creation_status`, `route`, `next_step`, `expected_by`, and `created_at`. It MUST NOT be populated merely because a working claim was started.

### Session

| Field | Type | Required | Rule |
|---|---|---:|---|
| `session_id` | string | Yes | Server-generated interaction identifier |
| `claim_id` | string | Yes | Parent working claim |
| `status` | enum | Yes | `active`, `paused`, or `closed` |
| `summary` | string | No | Compact factual summary for resume and model context |
| `unresolved_questions` | array | Yes | Typed question IDs and related field codes; initially empty |
| `pending_items` | array | Yes | Evidence or actions still outstanding; initially empty |
| `prior_commitments` | array | Yes | Customer-visible commitments and promised next steps; initially empty |
| `context_revision` | integer | Yes | Claim revision from which the summary was produced |
| `started_at` | timestamp | Yes | Session creation time |
| `last_active_at` | timestamp | Yes | Last accepted claimant or agent message time |
| `closed_at` | timestamp | No | Present only when closed |

Complete messages remain in durable storage. `summary`, `unresolved_questions`, and selected recent message references form a bounded resume package; they do not replace the formal claim record.

#### Session Lifecycle

A session has one of three states:

- `active`: currently accepting claimant messages;
- `paused`: temporarily inactive while resumable context is retained;
- `closed`: the interaction has ended and the session no longer accepts new messages.

Session lifecycle transitions are server-controlled.

A session MAY move from `active` to `paused` after claimant inactivity or when the current interaction is interrupted.

When a claimant resumes an existing working claim, the server starts a new interaction session using the current claim state and bounded resume context. A previously paused session MAY be closed when the new session is created.

Only one active claimant session per claim is permitted.

Messages MUST NOT be accepted for a closed session.

### Message

| Field | Type | Required | Rule |
|---|---|---:|---|
| `message_id` | string | Yes | Server-generated message identifier |
| `claim_id` | string | Yes | Parent working claim |
| `session_id` | string | Yes | Parent interaction session |
| `client_message_id` | string | Claimant messages | Client-generated retry key, unique within the claim |
| `actor` | enum | Yes | `claimant`, `agent`, `staff`, or `system` |
| `visibility` | enum | Yes | `claimant_visible`, `shared`, or `internal_only` |
| `content` | object | Yes | Typed text or status content; empty content is rejected |
| `evidence_refs` | string array | Yes | Attached evidence IDs; initially empty |
| `in_reply_to` | string | No | Related message ID when applicable |
| `created_at` | timestamp | Yes | Server-generated accepted time |

Claimant text content uses `{ "type": "text", "text": "..." }`. File bytes are evidence resources, not embedded base64 message fields. Staff notes use `internal_only` and MUST NOT appear through claimant message endpoints.

`actor` defines the sender and `visibility` defines the persisted audience boundary. A message
returned by a successful mutation or list response is durably stored and therefore has delivery
state `delivered` in the clients. This means durable in-app persistence, not email, SMS, or push
delivery. `sending`, `rejected_before_delivery`, `delivery_outcome_unknown`, and `retrying` are
transient client states and MUST NOT be inserted into persisted message history. A client MUST use
`delivery_outcome_unknown` when a transport failure could have hidden a successful commit. It
retains the text and original idempotency identifiers so replay restores the delivered record
without creating a duplicate. The complete state
and page flow is defined in `docs/claimant-staff-messaging-journey.md`.

The current staff reply helper is a deterministic template built from claimant-safe state; it does
not call the Agent or model gateway and MUST NOT be labelled as Agent- or AI-generated. Template
draft state is internal UI state, not a `MessageRecord`. Only an authenticated, assigned staff
submission creates a shared message; building or accepting a template never sends it automatically.

An `in_reply_to` reference MUST identify a message in the same claim and interaction session.
Message lists use the stable total order `(created_at, message_id)` ascending (newest-last). Equal
timestamps therefore cannot cause cursor pagination to duplicate or skip records.

### Customer Next Step

```json
{
  "status": "ready_to_create",
  "summary": "Your report is ready to be created as a claim.",
  "responsible_party": "northwind",
  "expected_by": "2026-08-11T05:00:00Z",
  "can_resume": true,
  "required_items": []
}
```

`responsible_party` is `claimant`, `northwind`, `claims_professional`, or `external_party`. An absent service estimate MUST be represented by an omitted `expected_by` plus an honest summary, not a fabricated time.

### Structured Form Field

The form is a map keyed by a registered field code. Every entry uses the same envelope:

```json
{
  "value": "Rear-ended while stopped at traffic lights",
  "source": "claimant",
  "source_refs": ["msg_01J4Y7T1KC"],
  "status": "confirmed",
  "needed_for": "current_action",
  "confidence": 1.0,
  "updated_at": "2026-08-10T03:42:10Z",
  "updated_by": {
    "actor_type": "claimant",
    "actor_id": "cus_01J4Y7M8M6"
  }
}
```

| Property | Type | Rule |
|---|---|---|
| `value` | JSON value | Typed according to the field registry; may be `null` only for missing or pending fields |
| `source` | enum | `claimant`, `image`, `document`, `policy`, `claim_history`, `inference`, `staff` |
| `source_refs` | string array | IDs of messages, evidence, policy citations, history records, or staff actions |
| `status` | enum | `proposed`, `confirmed`, `disputed`, `missing`, `pending_generation` |
| `needed_for` | enum | `current_action`, `later_action` |
| `confidence` | number | Optional `0.0` to `1.0`; never a substitute for confirmation |
| `updated_at` | timestamp | Server generated |
| `updated_by` | actor reference | Server derived from the authenticated actor |

Initial common field codes:

| Field code | Type | Purpose |
|---|---|---|
| `policy.policy_number` | string | Locate the relevant policy |
| `claimant.client_number` | string | Claimant-facing Northwind client reference |
| `claimant.role` | enum | Policyholder, authorised representative, or other reporter |
| `claimant.contact_preference` | enum | `in_app`, `email`, `phone`, or `sms` when supported |
| `incident.type` | string | Motor, home, contents, or configured subtype |
| `incident.occurred_at` | timestamp | When the incident occurred |
| `incident.location` | object | Structured place plus claimant wording |
| `incident.description` | string | Claimant-confirmed factual account |
| `incident.injury_or_danger` | boolean | Explicit safety routing input; not a diagnosis |
| `incident.cause` | string | Cause classification used for coverage assessment (e.g. sudden vs gradual) |
| `loss.description` | string | Damage, loss, or affected property |
| `parties.other_parties` | array | Other involved parties when known |
| `authorities.police_report_reference` | string | Reference if already issued |
| `authorities.emergency_services_notified` | boolean | Whether emergency services were contacted |
| `vehicle.registration` | string | Motor-specific vehicle reference |
| `vehicle.damage_description` | string | Motor-specific damage account |
| `vehicle.drivable` | boolean | Motor-specific immediate status |
| `property.address` | object | Home or contents risk location |
| `property.affected_areas` | array | Home-specific affected areas |

The backend MUST maintain a versioned field registry with validation and display metadata. New product fields require a registry change; clients MUST NOT invent arbitrary field codes.

### Evidence

```json
{
  "evidence_id": "evd_01J4Y7V5QJ",
  "claim_id": "clm_01J4Y7Q2AW",
  "kind": "police_report",
  "status": "pending_generation",
  "file_status": "not_available",
  "original_filename": null,
  "media_type": null,
  "size_bytes": null,
  "source": "claimant",
  "related_fields": ["authorities.police_report_reference"],
  "needed_for": ["later_action"],
  "provenance": {
    "reported_in_message_id": "msg_01J4Y7T1KC",
    "captured_at": "2026-08-10T03:45:00Z"
  },
  "claimant_note": "The police report has not been issued yet.",
  "created_at": "2026-08-10T03:45:00Z",
  "updated_at": "2026-08-10T03:45:00Z"
}
```

| Field | Allowed values or rule |
|---|---|
| `kind` | Registered evidence type such as `incident_image`, `police_report`, `receipt`, `repair_quote`, or `other_document` |
| `status` | `received`, `unofficial`, `incomplete`, `pending_generation`, `inconsistent` |
| `file_status` | `not_available`, `awaiting_upload`, `uploading`, `uploaded`, `processing`, `ready`, `failed` |
| `source` | `claimant`, `staff`, `external_system` |
| `related_fields` | Registered form field codes supported or challenged by the item |
| `needed_for` | One or more business actions; later evidence MUST NOT block an unrelated safe current action |

Extracted facts use the structured form envelope with `source` set to `image` or `document`. They remain `proposed` until claimant confirmation or an authorised staff decision.

### Current Compatibility Agent Decision

```json
{
  "decision_id": "dec_01J4Y7W90S",
  "action": "CONFIRM",
  "reason_codes": ["MATERIAL_FACTS_PROPOSED"],
  "customer_reason": "Please check the incident details before I continue.",
  "state_changes": [],
  "proposed_signals": [],
  "required_tools": [
    {
      "tool": "policy_lookup",
      "status": "completed",
      "result_refs": ["pol_01J4Y93M22"]
    }
  ],
  "next_action_requirements": ["confirm:incident.occurred_at"],
  "handoff_priority": null,
  "customer_next_step": {
    "status": "confirmation_required",
    "summary": "Check the date, location, and description.",
    "responsible_party": "claimant",
    "can_resume": true,
    "required_items": ["incident.occurred_at", "incident.location", "incident.description"]
  },
  "authority": {
    "proposed_by": "agent",
    "validated_by": "rule_engine",
    "outcome": "authorised"
  },
  "created_at": "2026-08-10T03:46:00Z"
}
```

`authority.outcome` is `authorised`, `blocked`, or `review_required`. A blocked or review-required proposal MUST NOT execute its high-impact state change.

`AgentDecision` is the current persisted and transported compatibility shape. It must not
be relabelled as a target `TurnPlan`, `AgentProposal`, `ExecutionPlan`, or `TurnResult`.
Those records distinguish model proposal, runtime approval, execution, and actual outcome
and require new schemas, persistence, consumers, fixtures, and contract tests before
entering this normative HTTP contract.

### Internal Signal

```json
{
  "signal_id": "sig_01J4Y7Z0EH",
  "claim_id": "clm_01J4Y7Q2AW",
  "code": "HISTORY_INCONSISTENCY_REVIEW",
  "category": "fraud_review",
  "status": "review_required",
  "source": "claim_history",
  "evidence_refs": ["his_01J4Y95E0P", "msg_01J4Y7T1KC"],
  "confidence": 0.72,
  "required_action": "Review the cited records and decide the signal.",
  "queue": "fraud_review",
  "created_at": "2026-08-10T03:47:00Z",
  "updated_at": "2026-08-10T03:47:00Z"
}
```

Signal status is `proposed`, `review_required`, `confirmed`, `dismissed`, `overridden`, or `resolved`. A signal records evidence for professional review; it MUST NOT state that the claimant committed fraud.

### Handoff

```json
{
  "handoff_id": "hnd_01J4Y7XG2C",
  "claim_id": "clm_01J4Y7Q2AW",
  "type": "professional_review",
  "status": "queued",
  "priority": "high",
  "queue": "coverage_review",
  "reason_codes": ["COVERAGE_AMBIGUOUS"],
  "requested_action": "Confirm whether the cited policy section applies.",
  "packet": {
    "incident_summary": "Claimant-confirmed summary",
    "form_revision": 7,
    "form_snapshot": {},
    "evidence_refs": ["evd_01J4Y7V5QJ"],
    "evidence": [
      {
        "evidence_id": "evd_01J4Y7V5QJ",
        "kind": "police_report",
        "status": "pending_generation",
        "file_status": "not_available",
        "source": "claimant",
        "visibility": "shared",
        "related_fields": ["authorities.police_report_reference"],
        "needed_for": ["later_action"]
      }
    ],
    "missing_items": [],
    "pending_items": ["evd_01J4Y7V5QJ"],
    "conflicts": [],
    "policy_citation_refs": ["pol_01J4Y93M22"],
    "history_evidence_refs": [],
    "source_refs": ["msg_01J4Y7T1KC"],
    "prior_customer_updates": [],
    "promised_next_step": "A claims professional will review the policy wording."
  },
  "assigned_to": null,
  "created_at": "2026-08-10T03:48:00Z",
  "accepted_at": null,
  "resolved_at": null
}
```

Handoff status transitions:

```text
requested -> queued -> accepted -> in_progress -> resolved
                    \-> cancelled
```

Priority is `standard`, `high`, `urgent`, or `immediate`. Queue is a configured value such as `claimant_support`, `coverage_review`, `complex_claims`, `urgent_support`, or `fraud_review`.

The staff-only packet carries the evidence list with its source, lifecycle and file state,
visibility, related fields, and purpose. It does not copy storage keys, checksums, or extraction
provenance. Claimant handoff responses exclude the complete packet, and claimant evidence
projections continue to exclude `internal_only` items.

### Staff Action

```json
{
  "action_id": "act_01J4Y80B7D",
  "claim_id": "clm_01J4Y7Q2AW",
  "action_type": "coverage_review",
  "status": "open",
  "assigned_to": "stf_01J4Y9ADW2",
  "requested_outcome": "Decide whether the cited wording applies.",
  "result": null,
  "due_at": null,
  "created_at": "2026-08-10T03:49:00Z",
  "completed_at": null
}
```

Status is `open`, `in_progress`, `completed`, or `cancelled`. Completion MUST include a result, reason code, actor, time, and any authorised state changes.

### Claim Event

Claim events are append-only audit records:

```json
{
  "event_id": "evt_01J4Y81HNM",
  "claim_id": "clm_01J4Y7Q2AW",
  "event_type": "form_field_confirmed",
  "actor": {
    "actor_type": "claimant",
    "actor_id": "cus_01J4Y7M8M6"
  },
  "reason_codes": ["CLAIMANT_CONFIRMED"],
  "source_refs": ["msg_01J4Y7T1KC"],
  "previous_revision": 6,
  "resulting_revision": 7,
  "request_id": "req_01J4Y9C60M",
  "occurred_at": "2026-08-10T03:50:00Z"
}
```

Events contain safe audit metadata and references. Large message bodies, files, model prompts, and secrets MUST NOT be copied into events.

## Claimant API

### Endpoint Catalogue

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/claims` | Start a working FNOL claim and its first session |
| `GET` | `/claims` | List the authenticated claimant's reports |
| `GET` | `/claims/{claim_id}` | Read the claimant-visible claim projection |
| `POST` | `/claims/{claim_id}/sessions` | Start or resume a session |
| `GET` | `/claims/{claim_id}/sessions/{session_id}` | Read resumable session state |
| `POST` | `/claims/{claim_id}/sessions/{session_id}/messages` | Submit a message and execute one agent turn |
| `GET` | `/claims/{claim_id}/sessions/{session_id}/messages` | Read paginated claimant-visible messages |
| `PATCH` | `/claims/{claim_id}/form` | Correct or update structured fields |
| `POST` | `/claims/{claim_id}/form/confirmations` | Confirm selected material fields |
| `POST` | `/claims/{claim_id}/creation` | Create an external claim after deterministic validation |
| `POST` | `/claims/{claim_id}/assessor-routing/consent` | Record bounded claimant permission for the contextual assessor action |
| `POST` | `/claims/{claim_id}/assessor-routing` | Send the authorised assessor request and return its claimant-safe state |
| `GET` | `/claims/{claim_id}/evidence` | List claimant-visible evidence state |
| `POST` | `/claims/{claim_id}/evidence` | Register expected, missing, or pending evidence |
| `POST` | `/claims/{claim_id}/evidence/uploads` | Request an evidence upload target |
| `PUT` | `/claims/{claim_id}/evidence/{evidence_id}/content` | Upload file bytes to an issued fixture-storage target |
| `POST` | `/claims/{claim_id}/evidence/{evidence_id}/complete` | Complete and validate an upload |
| `POST` | `/claims/{claim_id}/evidence/{evidence_id}/fact-decisions` | Confirm or reject proposed extracted facts |
| `POST` | `/claims/{claim_id}/support-requests` | Explicitly request human support |
| `GET` | `/claims/{claim_id}/updates` | Read claimant-visible progress updates |

### `POST /api/v1/claims`

Starts a working FNOL record. This is not yet a claim in the external claims system.

Request:

```json
{
  "channel": "web_agent",
  "locale": "en-NZ",
  "incident_type": "motor"
}
```

`incident_type` MAY be omitted when it is not yet known.

Response `201`:

```json
{
  "claim": {
    "claim_id": "clm_01J4Y7Q2AW",
    "revision": 1,
    "workflow_state": "collecting",
    "external_claim": null,
    "customer_next_step": {
      "status": "describe_incident",
      "summary": "Tell me what happened in your own words.",
      "responsible_party": "claimant",
      "can_resume": true,
      "required_items": []
    },
    "created_at": "2026-08-10T03:40:00Z",
    "updated_at": "2026-08-10T03:40:00Z"
  },
  "session": {
    "session_id": "ses_01J4Y7RPN8",
    "claim_id": "clm_01J4Y7Q2AW",
    "status": "active",
    "started_at": "2026-08-10T03:40:00Z",
    "last_active_at": "2026-08-10T03:40:00Z"
  }
}
```

### `GET /api/v1/claims`

Returns only the authenticated claimant's reports. Each item contains `claim_id`, creation state, plain-language status, next step, last update time, and whether the report can be resumed. Internal state dimensions are excluded.

Filters: `workflow_state`, `updated_after`, plus standard pagination.

Response `200` uses the standard collection envelope. Each item contains
`claim_id`, `revision`, `incident_type`, `workflow_state`, `external_claim`,
`customer_next_step`, `created_at`, `updated_at`, and `can_resume`.

### `GET /api/v1/claims/{claim_id}`

Response `200`:

```json
{
  "claim_id": "clm_01J4Y7Q2AW",
  "revision": 7,
  "incident_type": "motor",
  "workflow_state": "ready_for_next",
  "form": {},
  "evidence_summary": {
    "received": 2,
    "pending": 1,
    "needs_attention": 0
  },
  "external_claim": null,
  "external_service_action": null,
  "customer_next_step": {},
  "created_at": "2026-08-10T03:40:00Z",
  "updated_at": "2026-08-10T03:50:00Z"
}
```

The claimant-facing `evidence_summary` MUST be calculated only from evidence records visible through the claimant evidence projection. It MUST NOT include counts derived from `internal_only` evidence or any record excluded from `GET /claims/{claim_id}/evidence`. The persisted Working Claim retains the authoritative aggregate over the full persisted evidence set for staff and operational use; persistence adapters MUST preserve that full aggregate. Claimant-safe aggregation is applied only at the claimant projection boundary.

The `form` contains claimant-visible structured field records. `external_claim`, when present, contains `claim_number`, `creation_status`, `route`, `created_at`, and claimant-visible expected timing.

`external_service_action` is omitted as `null` until an external participant action is a
relevant next step. The controlled assessor action appears only after a motor claim has been
created on the fixture route, its location is confirmed, and no open handoff or professional
review blocks the action. It contains the service and provider labels, purpose, claimant-safe
summary of the minimum data to be shared, consent state, progress/result state, and the
provider-neutral routing result when accepted. It never exposes the raw consent record,
authorisation decision, internal signals, or complete claim context.

### `POST /api/v1/claims/{claim_id}/sessions`

Starts a new interaction session for an existing working claim. The server restores the current claim snapshot, unresolved work, and prior commitments; it does not copy the complete conversation into the response or model context.

Request:

```json
{
  "intent": "resume"
}
```

Response `201` includes:

```json
{
  "session_id": "ses_01J4YB0J3S",
  "claim_id": "clm_01J4Y7Q2AW",
  "status": "active",
  "resume": {
    "summary": "You reported a rear-end collision and confirmed the incident details.",
    "unresolved_questions": [],
    "pending_items": ["police_report"],
    "prior_commitments": ["You can add the police report later without restarting."],
    "customer_next_step": {}
  },
  "started_at": "2026-08-20T01:10:00Z",
  "last_active_at": "2026-08-20T01:10:00Z"
}
```

Only one active claimant session per claim is permitted. If an active session already exists, the server MAY return that session instead of creating another one. If only paused sessions exist, the server creates a new active session using the claim's resumable context.

### `GET /api/v1/claims/{claim_id}/sessions/{session_id}`

Returns session status, compact resume summary, unresolved questions, pending items, prior commitments, and current customer next step. It MUST NOT return hidden internal state or the complete conversation by default.

### `POST /api/v1/claims/{claim_id}/sessions/{session_id}/messages`

Stores the claimant message, runs one validated agent turn, persists resulting state, and returns the customer-visible outcome.

Request:

```json
{
  "client_message_id": "mobile-7fce2f14",
  "content": {
    "type": "text",
    "text": "I was rear-ended while stopped at traffic lights. Nobody is injured."
  },
  "evidence_refs": []
}
```

`client_message_id` is generated by the client and deduplicates retries within the claim. Empty text without evidence is rejected.

When the explicitly configured Agent runtime uses a model gateway, a timeout, rate limit,
or retryable provider failure returns `503 DEPENDENCY_UNAVAILABLE` with `retryable: true`.
Authentication, configuration, unsupported-capability, incomplete, refused, malformed-response,
and other non-retryable model failures return `502 DEPENDENCY_FAILED` with `retryable: false`.
Both outcomes use provider-neutral messages, preserve the current Claim revision, and do not write
the claimant message, Agent decision, or idempotency result. A schema-valid partial result is still
discarded unless the adapter normalises the provider termination state as complete. Provider
response bodies, credentials, prompts, and internal model context are never returned.

Response `200`:

```json
{
  "claim_id": "clm_01J4Y7Q2AW",
  "session_id": "ses_01J4Y7RPN8",
  "claim_revision": 3,
  "claimant_message": {
    "message_id": "msg_01J4Y7T1KC",
    "actor": "claimant",
    "content": {
      "type": "text",
      "text": "I was rear-ended while stopped at traffic lights. Nobody is injured."
    },
    "created_at": "2026-08-10T03:42:10Z"
  },
  "agent_message": {
    "message_id": "msg_01J4YC22FP",
    "actor": "agent",
    "content": {
      "type": "text",
      "text": "I have recorded that you were stopped when another vehicle hit yours and that no one is injured. Please check the details shown."
    },
    "created_at": "2026-08-10T03:42:12Z"
  },
  "form_changes": [
    {
      "field_code": "incident.description",
      "field": {
        "value": "Rear-ended while stopped at traffic lights",
        "source": "claimant",
        "source_refs": ["msg_01J4Y7T1KC"],
        "status": "proposed",
        "needed_for": "current_action",
        "confidence": 0.96,
        "updated_at": "2026-08-10T03:42:12Z"
      }
    }
  ],
  "decision": {
    "decision_id": "dec_01J4Y7W90S",
    "action": "CONFIRM",
    "reason_codes": ["MATERIAL_FACTS_PROPOSED"],
    "customer_reason": "Please check the incident details before I continue.",
    "customer_next_step": {}
  },
  "handoff": null,
  "dynamic_form": {
    "claim_id": "clm_01J4Y7Q2AW",
    "claim_revision": 3,
    "field_registry_version": "3",
    "branch_rules_version": "vp-dynamic-form-branch-rules-v1",
    "selected_family": "motor",
    "active_branches": ["family.motor", "incident.collision"],
    "fields": [
      {
        "field_code": "incident.occurred_at",
        "selection_state": "required_now",
        "value_state": "missing",
        "source": null,
        "reason": "Missing and required for the current safe action."
      }
    ]
  }
}
```

Only the customer-safe decision projection is returned. Internal required tools, confidence, signals, and authority details remain available through authorised internal APIs and events.

`dynamic_form` is a claimant-safe projection of the latest applied branch evaluation whose
evaluated and resulting revision both equal the current Claim revision. It exposes only active,
claimant-visible fields; inactive and system-owned fields remain outside this response. Selection
state (`required_now`, `candidate_now`, or `pending_later` in this projection) is separate from the
stored value state. The projection is omitted when no current-revision evaluation exists.

### `GET /api/v1/claims/{claim_id}/sessions/{session_id}/messages`

Returns claimant-visible messages ordered newest-last by default. Supported query: `before`, `after`, `limit`, and `cursor`. Staff-only notes and hidden system messages are excluded.

### `PATCH /api/v1/claims/{claim_id}/form`

Corrects or supplies structured fields. It does not accept server-owned provenance or audit timestamps.

Request:

```json
{
  "updates": [
    {
      "field_code": "incident.occurred_at",
      "value": "2026-08-09T22:15:00Z",
      "status": "confirmed",
      "correction_reason": "The incident was at 10:15 pm, not 9:15 pm."
    }
  ]
}
```

Response `200` returns `claim_id`, new `revision`, updated fields, invalidated decisions if any, and `customer_next_step`. A correction that changes a material decision MUST cause re-evaluation before that decision executes.

### `POST /api/v1/claims/{claim_id}/form/confirmations`

Request:

```json
{
  "field_codes": [
    "incident.occurred_at",
    "incident.location",
    "incident.description"
  ]
}
```

All fields must exist and be confirmable. Response `200` returns the new claim revision, confirmed fields, any new decision, and the current customer next step.

When all controlled intake fields are confirmed, `customer_next_step.status` becomes
`ready_to_create`. Confirmation does not itself invoke an external claims service.

### `POST /api/v1/claims/{claim_id}/creation`

The claimant client MAY offer a guided Motor presentation over the same resources used by the
conversational intake. The guided presentation creates the Working Claim before its first page is
saved, writes registered form fields through `PATCH /form`, uses the Evidence API for materials,
and calls this creation endpoint only after the controlled intake fields are confirmed. It does
not create a second draft store or a separate staff queue.

The current guided prototype records acceptance of declaration
`guided-motor-prototype-v1` as a persisted claimant message immediately before creation. This is
repeatable prototype evidence of actor, wording, version, and time; it is not a Northwind-approved
legal signature contract. A production declaration requires approved wording, identity assurance,
consent rules, retention, and a dedicated typed acceptance contract before it may be described as
an electronic signature.

When the claimant continues without any supporting file, the guided Motor client registers one
claimant-owned `incomplete` evidence item needed for a `later_action`. The created claim therefore
remains visible in the Workbench `awaiting_evidence` view without blocking controlled creation.
The `standard_motor_intake` fixture route assigns the created Working Claim deterministically to
`stf_demo`. This is a repeatable prototype allocation rule, not an approved Northwind workforce
routing policy; configured production allocation requires an authenticated assignment service and
an approved routing rule.

Creates an external claim through the configured provider-neutral claims adapter. The endpoint
accepts no provider payload. It derives the confirmed form, evidence references, pending evidence,
and controlled prototype route from the persisted Working Claim.

Current deterministic fixture creation is limited to the controlled motor path. Other incident
types remain unconfigured until approved routing rules are available.

The request requires `If-Match` and `Idempotency-Key` headers and has no body. The service rejects
creation when required intake fields are not confirmed, a human handoff is open, the report is in
professional review, or the Working Claim has already been created. Pending later evidence does not
by itself block this operation and is passed to the adapter as outstanding work.

Before invoking the adapter, the service records a deterministic `CREATE_CLAIM` decision with
`CLAIM_CREATION_AUTHORISED`. A model proposal or claimant-supplied decision ID cannot authorise
this operation.

During the action-contract migration, this deterministic decision is the compatibility
representation of an authorised `claim.create` action. The public response remains
unchanged until the new ActionEnvelope and turn-result schemas are implemented and
versioned together with clients and tests.

Response `201`:

```json
{
  "claim_id": "clm_01J4Y7Q2AW",
  "revision": 5,
  "decision": {
    "decision_id": "dec_01J4YD82JA",
    "action": "CREATE_CLAIM",
    "reason_codes": ["CLAIM_CREATION_AUTHORISED"],
    "customer_reason": "The controlled intake fields are confirmed and no open handoff blocks creation.",
    "customer_next_step": {}
  },
  "external_claim": {
    "external_claim_id": "ext_fixture_1042",
    "claim_number": "NWF-2026-001042",
    "creation_status": "created",
    "route": "standard_motor_intake",
    "next_step": "Claims intake review",
    "source": "fixture",
    "expected_by": "2026-08-11T05:00:00Z",
    "created_at": "2026-08-10T03:55:00Z"
  },
  "external_service_action": {
    "service_identity": "vehicle_damage_assessment_routing",
    "service_name": "Vehicle damage assessment",
    "provider": "Controlled assessment fixture",
    "purpose": "Request an assessor for the vehicle damage recorded in this claim. This does not decide coverage or approve repairs.",
    "shared_data_summary": [
      "Your Northwind claim and external claim references",
      "Northwind routing authority and your permission reference",
      "The vehicle damage assessment request",
      "Your confirmed incident region"
    ],
    "status": "consent_required",
    "consent_status": null,
    "routing": null,
    "can_request": true
  },
  "customer_next_step": {
    "status": "claim_created",
    "summary": "Claims intake review",
    "responsible_party": "northwind"
  }
}
```

An idempotent replay restores the same response. The mock adapter supplies synthetic values only;
this contract does not assert a Northwind provider schema or AWS implementation.

### `POST /api/v1/claims/{claim_id}/assessor-routing/consent`

Records claimant permission for the exact controlled vehicle-assessment scope. The request
requires `Idempotency-Key` and `If-Match`:

```json
{
  "consent": true
}
```

The client cannot widen the participant, action, or fields. The server records permission only
for the claim and external-claim references, Northwind routing authority, consent reference,
vehicle-damage assessment action, and confirmed incident region. Permission and Northwind
routing authority remain separate requirements.

Response `201`, or `200` for an identical replay, returns the new revision,
`customer_next_step`, and the claimant-safe `external_service_action` with status
`ready_to_request`. Raw consent references and the internal consent list are not returned.
The consent, single Claim revision advance, and idempotency response are one repository
mutation: a failed transaction leaves all three unchanged.

This endpoint is available only when the external service action is a relevant next step. A
draft, non-motor, pending or failed claim-creation result, open handoff, professional review, or
already accepted assessor request is rejected without recording consent.

### `POST /api/v1/claims/{claim_id}/assessor-routing`

Sends the controlled provider-neutral assessor request after active claimant permission has been
recorded. The request has no body and requires `Idempotency-Key` and `If-Match`. The server derives
the external claim reference, current Northwind authority, active consent, requested action, and
confirmed region from the shared Working Claim; the claimant cannot supply provider or routing
payload fields.

Response `201`, or `200` for an identical replay, returns the resulting claim revision,
`customer_next_step`, and the claimant-safe action. Status is `assigned` only when an individual
assessor reference was returned and `queued` when only a queue accepted the request.

Timeout and unavailable responses use `503 DEPENDENCY_UNAVAILABLE` with `retryable: true`.
Access-denied and malformed responses use `502 DEPENDENCY_FAILED` with `retryable: false`. All
four leave the consented Working Claim revision unchanged, do not report assignment, and retain
the same operation identity for an unchanged permitted retry. Automatic retry counts remain
unapproved; the claimant client offers only an explicit retry for retryable failures.

The authorised decision and prepared operation identity are persisted together before the
provider call. The service also persists one operational `tsk_` task and its `erq_` request,
including the selected stakeholder, readable purpose, disclosed field names, separate Northwind
authority and claimant-consent references, authorised Claim revision, preparation time, first
send time, and stable operation identity. The request is available only through the protected
internal task projection; raw authority, consent, delivery evidence, and provider references do
not enter this claimant response. A timeout retry reuses that durable authority and request
record rather than replacing either with a new identity or timestamp. If provider acceptance and the Claim update succeed but saving the public
idempotency response fails, the same request restores the authoritative assigned or queued state;
the claimant client also reloads that state before presenting a failure message.
If provider acceptance is durable but a concurrent Claim mutation wins the following
compare-and-set, the first request returns the bounded revision conflict. Only the identical
claimant request with the original idempotency key, revision, consent, authority, and operation
identity may reconcile that accepted result without another provider call. An unrelated stale
request remains a revision or idempotency conflict.

### `GET /api/v1/claims/{claim_id}/evidence`

Returns claimant-visible evidence metadata, processing state, purpose, upload result, and plain-language next step. It never returns internal-only extraction notes or other claims' evidence.

The response contains `claim_id`, current `revision`, `items`, and
`customer_next_step`. Evidence items deliberately omit storage keys, upload
checksums, extraction state, and internal provenance.

### `POST /api/v1/claims/{claim_id}/evidence`

Registers evidence when no file is currently available.

Request:

```json
{
  "kind": "police_report",
  "status": "pending_generation",
  "related_fields": ["authorities.police_report_reference"],
  "needed_for": ["later_action"],
  "claimant_note": "Police said the report will be available next week."
}
```

This request requires `Idempotency-Key` and `If-Match`. Response `201` returns
the evidence resource, new claim revision, and customer next step. A
`pending_generation` item MUST NOT block an action that does not require it.
Evidence with a received file must use the upload flow rather than being
registered directly as `received`.

### `POST /api/v1/claims/{claim_id}/evidence/uploads`

Requests an upload target.

Request:

```json
{
  "kind": "incident_image",
  "original_filename": "rear-damage.jpg",
  "media_type": "image/jpeg",
  "size_bytes": 1842201
}
```

Response `201`:

```json
{
  "evidence_id": "evd_01J4Y7V5QJ",
  "revision": 8,
  "upload": {
    "method": "PUT",
    "url": "https://example.invalid/signed-upload",
    "headers": {
      "Content-Type": "image/jpeg"
    },
    "expires_at": "2026-08-10T04:05:00Z"
  },
  "constraints": {
    "max_size_bytes": 10485760,
    "allowed_media_types": ["image/jpeg", "image/png", "application/pdf"]
  },
  "customer_next_step": {
    "status": "add_evidence",
    "summary": "Upload the requested evidence when it is available.",
    "responsible_party": "claimant",
    "expected_by": null,
    "can_resume": true,
    "required_items": []
  }
}
```

This request requires `Idempotency-Key` and `If-Match`. The URL is illustrative.
A configured S3-compatible adapter returns a short-lived upload capability that MAY
contain bucket/addressing information, a staging object path, and SigV4 access-key
identity. It MUST NOT contain the secret access key. Protected storage keys MUST NOT
appear in the persistent claimant Claim or Evidence projections. A replay after the
capability expires MUST re-sign the same upload intent without creating another Evidence
record or advancing Claim revision. The adapter MAY use fixture
storage or the active profile's object storage without changing the client
contract.

### `POST /api/v1/claims/{claim_id}/evidence/{evidence_id}/complete`

Confirms upload completion and starts validation or extraction.

Request:

```json
{
  "upload_checksum": "sha256:7e9f..."
}
```

This request requires `Idempotency-Key` and `If-Match`. Response is `200` when
processing is complete or `202` when processing continues. It returns the
claimant-safe evidence resource, new claim revision, `status_url`, and the
current customer next step. The server MUST validate media type, size,
ownership, stored object identity, and the submitted SHA-256 checksum before
accepting the item. A configured object adapter records the checksum computed
from the stored bytes and a safe adapter source identifier; it does not treat a
claimant-declared checksum as provider-verified provenance. Image-derived fields
remain proposed until a claimant or authorised staff member confirms them;
completion never silently writes extracted values into the confirmed form.

For the fixture runtime, the upload target is the authenticated
`PUT /api/v1/claims/{claim_id}/evidence/{evidence_id}/content` route. It requires the claimant
bearer token, registered media type, exact registered byte length, and use before the target's
`expires_at`. An expired target is rejected and the client must replay the upload-intent request to
obtain a current target. Completion hashes the stored bytes and rejects a claimant-supplied checksum
that does not match; the supplied value is never treated as proof by itself. The application reads
fixture-proxy content as a stream and stops as soon as either the registered byte length or the
application-wide evidence maximum would be exceeded. `Content-Length` is checked when present but
is never the sole size control. Provider-backed profiles return an object-store URL and reject the
fixture-only content route before consuming its request body, without changing the upload-target
contract.

The Sprint 2 mock adapter returns `202` and records the public `file_status` as
`processing` after an image or PDF upload is accepted. Filename, media type,
size, and processing status can be read back from the evidence list. Storage
keys, checksums, processing references, and file contents remain internal.

Authorised staff can read completed fixture evidence through
`GET /api/v1/workbench/claims/{claim_id}/evidence/{evidence_id}/content`. This applies the same
staff claim-access boundary as Workbench detail and returns the registered media type with an
inline filename. It never exposes a storage key or checksum, and claimant credentials cannot use
the staff route. The sibling `/content-data` route applies the same checks and returns the filename,
media type, and Base64 file bytes for browser-safe image preview and download in the static
Workbench client.

### `POST /api/v1/claims/{claim_id}/evidence/{evidence_id}/fact-decisions`

Confirms or rejects facts proposed by completed image or document processing.

Request:

```json
{
  "field_codes": ["incident.description"],
  "decision": "confirmed"
}
```

This request requires `Idempotency-Key` and `If-Match`. Every selected field
must still be `proposed`, use `image` or `document` as its source, and reference
the same evidence item. A confirmed fact becomes `confirmed`. A rejected fact
uses the form status `disputed` so it cannot be mistaken for accepted claim
information. Both outcomes retain the original source reference and record the
proposal and decision times in internal provenance.

### `POST /api/v1/claims/{claim_id}/support-requests`

Request:

```json
{
  "reason": "I want to speak to a person.",
  "support_need": "human_requested",
  "preferred_channel": "phone"
}
```

`support_need` is `human_requested`, `accessibility_required`, `distress`, or `urgent`. Response `201` returns the customer-safe handoff projection, next step, and delivery state.

`delivery.state` reports whether the staff queue system was notified:

- `delivered` means the notification service accepted the handoff.
- `queued_locally` means the notification service could not be reached. The
  handoff is still saved, the claim revision still advances exactly once, and
  the Workbench queue still shows the claim, because that queue is derived from
  persisted claim state rather than from the notification. Only the push
  notification is missing, and `delivery.limitations` says so in
  claimant-safe words.

Notification runs only after the handoff is durable, so a notification outage
never fails the claimant request and never loses it. A retry with the same
idempotency key returns the same handoff and does not notify twice.

`GET /health/ready` reports the notification service under the
`handoff_dispatch` check.

The current controlled fixture rule transfers the first explicit human request immediately and records `prototype_immediate_transfer` as the applied rule. A repeated request, distress, urgent condition, or accessibility need MUST also transfer immediately. Whether production keeps immediate transfer or offers one brief, transparent choice to finish the current step remains an open product decision.

### `GET /api/v1/claims/{claim_id}/updates`

Returns staff and system updates visible to the claimant. Each update includes `update_id`, `summary`, `responsible_party`, `expected_by` when known, `created_at`, and related evidence or claim references.

## Workbench API

### Endpoint Catalogue

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/workbench/claims` | Query queue projections and filters |
| `GET` | `/workbench/claims/{claim_id}` | Read full authorised claim detail |
| `GET` | `/workbench/claims/{claim_id}/evidence/{evidence_id}/content` | View completed evidence content as authorised staff |
| `GET` | `/workbench/claims/{claim_id}/evidence/{evidence_id}/content-data` | Read browser-safe evidence content as authorised staff |
| `POST` | `/workbench/claims/{claim_id}/assignments` | Assign or reassign ownership |
| `POST` | `/workbench/claims/{claim_id}/staff-actions` | Create a staff action |
| `PATCH` | `/workbench/claims/{claim_id}/staff-actions/{action_id}` | Progress or complete a staff action |
| `POST` | `/workbench/claims/{claim_id}/signals/{signal_id}/decisions` | Decide an internal signal |
| `POST` | `/workbench/claims/{claim_id}/handoffs/{handoff_id}/accept` | Accept a handoff |
| `POST` | `/workbench/claims/{claim_id}/messages` | Send a persisted claimant-visible staff message |
| `POST` | `/workbench/claims/{claim_id}/handoffs/{handoff_id}/resolve` | Resolve a handoff and write back state |
| `POST` | `/workbench/claims/{claim_id}/updates` | Send a claimant-visible update |
| `GET` | `/workbench/claims/{claim_id}/events` | Read the claim audit timeline |
| `GET` | `/operations/metrics` | Read aggregate operational metrics |

### `GET /api/v1/workbench/claims`

Supported filters:

| Filter | Values |
|---|---|
| `view` | `urgent`, `human_requests`, `new_untriaged`, `ready_to_progress`, `awaiting_evidence`, `professional_review`, `ready_to_create`, `created_routed` |
| `workflow_state` | Canonical workflow state |
| `priority` | `standard`, `high`, `urgent`, `immediate` |
| `assignee_id` | Opaque staff ID or `unassigned` |
| `next_action` | `AgentAction` |
| `tag` | Registered internal tag code |
| `updated_before`, `updated_after` | RFC 3339 timestamp |

Each item includes claim ID, safe display reference, state dimensions, priority, queue, route,
next responsibility, evidence state and counts, open handoff summary, assignee, integration status,
service timing, and update time. It is a projection of shared claim state, not a separately
editable board record.

The response is shaped as `{ "items": [...], "page": { "next_cursor": null } }`. Each item
contains `claim_id`, `revision`, `customer_reference`, `incident_type`, `workflow_state`,
`queue`, `priority`, `next_action`, `route`, `evidence_state`, `evidence_summary`,
`next_action_summary`, `responsible_party`, `claim_creation_status`,
`assessor_routing_status`, `open_handoff_count`, `assignee_id`, `created_at`, and `updated_at`.
Queue assignment, priority, and assignee are derived from the shared claim state and active
persisted handoffs. Creation and assessor-routing statuses are nullable until those integrations
have produced a result.

`urgent` contains claims with an open `urgent` or `immediate` handoff. `human_requests`
contains claims with an open claimant-support handoff whose support need is `human_requested`.
Queue results are ordered by priority (`immediate`, `urgent`, `high`, `standard`) and then by
oldest claim creation time so staff can accept the highest-priority work first.

### `GET /api/v1/workbench/claims/{claim_id}`

Returns the authorised internal projection assembled from the same repository records used by
claimant routes:

```json
{
  "claim_id": "clm_01J4Y7Q2AW",
  "revision": 7,
  "customer_reference": "customer-1042",
  "channel": "web_agent",
  "locale": "en-NZ",
  "incident_type": "motor",
  "claim_state": {},
  "form": {},
  "route": "professional_review",
  "active_session_id": "ses_01J4Y7RPN8",
  "evidence_summary": {},
  "evidence": [],
  "sessions": [],
  "messages": [],
  "decisions": [],
  "retrievals": [],
  "signals": [],
  "handoffs": [],
  "staff_actions": [],
  "customer_updates": [],
  "external_claim": null,
  "assessor_routing": null,
  "customer_next_step": {},
  "created_at": "2026-08-10T03:40:00Z",
  "updated_at": "2026-08-10T03:50:00Z"
}
```

The Workbench `evidence_summary` is the authoritative aggregate over the full persisted evidence set, including authorised internal evidence. It MUST NOT be recomputed from the narrower claimant-visible evidence projection.

`sessions` includes compact summaries, unresolved questions, pending items, prior commitments,
and context revisions. `messages` includes the complete persisted communication history,
including internal-only staff or system records. `decisions` includes internal authority,
tool, and proposed-signal context. `retrievals` contains the provider-neutral policy and relevant
claim-history records, including provenance and recorded uncertainty. `signals` projects persisted
proposed signals and connects retrieval-backed signals to their source evidence through
`source_refs` and `source_evidence`; recorded staff decisions include their actor, reason codes,
result summary, and evidence references. `handoffs` is a typed staff-only projection of the persisted handoff records and
includes routing fields, the staff-visible `trigger`, and the complete transfer packet. An
internal `professional_review_required` trigger does not set `support_need`: that field remains
specific to claimant support intent. Claimant routes return only the
separate `ClaimantHandoff` projection and never expose the queue, internal reasons, requested
action, applied rule, assignment, source message, or packet. `external_claim` and
`assessor_routing` use the shared typed creation and routing results, including their status,
next step, and expected timing. Internal fields are never added to claimant projections unless
their claimant-safe contract explicitly includes them.

The current repository has no separate persisted staff-action or customer-update records. Those
arrays therefore remain empty rather than synthesising a second lifecycle or manual status.

Access to policy excerpts, history evidence, fraud-review signals, and staff notes MAY be further restricted by role.

### `POST /api/v1/workbench/claims/{claim_id}/assignments`

Request:

```json
{
  "assignee_id": "stf_01J4Y9ADW2",
  "queue": "coverage_review",
  "reason_code": "HANDOFF_ACCEPTED"
}
```

Response `200` returns the new claim revision and assignment. Assignment does not silently resolve the related handoff or action.

### `POST /api/v1/workbench/claims/{claim_id}/staff-actions`

Request:

```json
{
  "action_type": "coverage_review",
  "assigned_to": "stf_01J4Y9ADW2",
  "requested_outcome": "Decide whether the cited wording applies.",
  "source_refs": ["pol_01J4Y93M22", "hnd_01J4Y7XG2C"]
}
```

Response `201` returns the staff action and new claim revision.

### `PATCH /api/v1/workbench/claims/{claim_id}/staff-actions/{action_id}`

Request to complete:

```json
{
  "status": "completed",
  "result": {
    "outcome": "professional_review_completed",
    "summary": "The cited wording applies to the reported event.",
    "reason_codes": ["POLICY_SECTION_CONFIRMED"],
    "source_refs": ["pol_01J4Y93M22"]
  },
  "state_changes": [
    {
      "path": "claim_state.coverage",
      "to": "clear"
    }
  ],
  "customer_update": {
    "summary": "The policy review is complete and your report can continue.",
    "responsible_party": "northwind"
  }
}
```

The server validates actor authority and state transitions. Response `200` returns the action, resulting claim revision, and customer update when created.

### `POST /api/v1/workbench/claims/{claim_id}/signals/{signal_id}/decisions`

Request:

```json
{
  "decision": "dismissed",
  "reason_codes": ["SOURCE_RECORD_NOT_COMPARABLE"],
  "summary": "The cited historical record concerns a different insured item.",
  "evidence_refs": ["his_01J4Y95E0P"]
}
```

`decision` is `confirmed`, `dismissed`, `overridden`, or `resolved`. Confirmation preserves the signal for authorised follow-up; it does not declare fraud or automatically reject or block claim creation.

### Handoff Accept and Resolve

`POST /api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/accept` accepts the queued handoff for the authenticated staff member or an authorised `assignee_id`.

After a handoff is accepted, both parties may continue using the persisted session message
history. A claimant message during an open handoff is routed to staff without an automatic Agent
reply. Prefixing claimant text with `@agent` explicitly requests an Agent turn. Staff messages use
`POST /api/v1/workbench/claims/{claim_id}/messages`; they move an accepted handoff to
`in_progress` but do not resolve it. `resolve` remains a separate, explicit lifecycle operation.

The prototype clients use these provider-neutral HTTP resources for explicit message refreshes.
Real-time delivery infrastructure remains replaceable and is not part of the API contract.

Resolve request:

```json
{
  "result": {
    "outcome": "support_completed",
    "summary": "The claimant's question was answered and the report can continue.",
    "reason_codes": ["SUPPORT_NEED_MET"]
  },
  "state_changes": [],
  "customer_update": {
    "summary": "Your report is ready to continue online.",
    "responsible_party": "claimant"
  }
}
```

Resolving a handoff MUST record the staff result, state changes, claimant update, actor, timestamps, and resulting claim revision.

### `POST /api/v1/workbench/demo/seed-scenarios`

Loads a bounded, mixed local workbench demonstration queue through the canonical MVP journey
catalogue. AT-01 exercises the clear path, AT-06 exercises claimant, external-agency, and
internal pending-evidence waits, AT-04 and AT-05 exercise urgent and standard human handoff,
and AT-02 exercises professional review. AT-10 is an additional created claim routed to an
assessor; it does not replace a core path.
This endpoint is not a handoff-only seed boundary. It is an explicit staff action: the
workbench never calls it during page load. The route requires the synthetic staff credential, is
available only in development and test environments, and returns
`409 DEMO_SEED_REQUIRES_EMPTY_QUEUE` if claims already exist. Reset the local demo before loading
this set again. Runtime demo records are maintained under `backend/demo_data/scenarios/`, not
under the test fixture tree.

AT-02 also supplies the bounded structured MVP record graph: its `customer_reference` and
`claim_id` connect the Working Claim to typed policy and claim-history retrievals, evidence,
messages, and a professional-review handoff. The handoff packet references those records by
their stable identifiers. Policy/history payloads remain available only from the authorised
Workbench claim-detail route; claimant routes do not expose retrieval records, provider
references, claim history, internal messages, or the staff packet. Both web clients discover
the queue and claim detail through these APIs rather than embedding fixture payloads or IDs.

Response `200`:

```json
{
  "status": "seeded",
  "scenario_ids": [
    "AT-01-clear-motor",
    "AT-06-pending-evidence",
    "AT-04-urgent",
    "AT-02-coverage-ambiguity",
    "AT-05-human-request",
    "AT-10-controlled-assessor"
  ],
  "claim_ids": [
    "clm_fixture_at01",
    "clm_fixture_at06",
    "clm_fixture_at04",
    "clm_fixture_at02",
    "clm_fixture_at05",
    "clm_fixture_at10"
  ]
}
```

### `POST /api/v1/workbench/demo/reset`

Resets the running local demonstration state. The route requires the synthetic
staff credential and is therefore unavailable outside the development and test
environments. It clears claims, sessions, messages, decisions, evidence,
handoffs, staff records, idempotency records, and mock integration results.

Every runtime component must explicitly implement the demo-reset boundary. If
the repository or any adapter does not opt in, the server returns `409
DEMO_RESET_UNAVAILABLE` before clearing any component. This prevents the local
command from deleting data through a future production persistence or provider
adapter.

Response `200`:

```json
{
  "status": "reset",
  "cleared": {
    "claims": 2,
    "evidence": 1,
    "handoffs": 1,
    "idempotency_records": 6,
    "mock_claim_results": 1
  }
}
```

Use `py -3.12 scripts/reset_demo.py` while the local backend is running. The
command prints the cleared record counts and exits non-zero for connection,
authentication, unsupported-component, or invalid-response failures.

### `POST /api/v1/workbench/claims/{claim_id}/updates`

Creates a claimant-visible update. Internal notes use the staff action or event model and MUST NOT be sent through this endpoint.

Request:

```json
{
  "summary": "We are waiting for the police report. You do not need to restart your report.",
  "responsible_party": "claimant",
  "expected_by": null,
  "related_refs": ["evd_01J4Y7V5QJ"]
}
```

### `GET /api/v1/workbench/claims/{claim_id}/events`

Returns authorised append-only claim events with standard pagination. Filters: `event_type`, `actor_type`, `occurred_after`, and `occurred_before`.

### `GET /api/v1/operations/metrics`

Required query: `from`, `to`. Optional filters: `incident_type`, `route`, `workflow_state`, and `handoff_reason`.

Response groups aggregate metrics only:

```json
{
  "period": {
    "from": "2026-08-10T00:00:00Z",
    "to": "2026-08-11T00:00:00Z"
  },
  "claims": {
    "started": 20,
    "created": 12,
    "handed_off": 5
  },
  "claimant_effort": {
    "questions": 84,
    "corrections": 11,
    "repeated_questions": 1,
    "median_time_to_next_action_seconds": 410
  },
  "agent_effort": {
    "input_tokens": 120000,
    "output_tokens": 28000,
    "retrieval_calls": 32,
    "tool_calls": 48,
    "errors": 2,
    "retries": 3
  },
  "staff_effort": {
    "handoffs": 5,
    "staff_actions": 8,
    "median_time_to_accept_seconds": 320,
    "handoff_completeness_rate": 0.8
  }
}
```

Prototype metrics validate observability, not Northwind production performance. Small groups MUST not expose identifiable claim or staff behaviour.

## Internal Orchestration and Adapter API

Internal endpoints are service-to-service only. The backend MAY implement an adapter in-process, but it MUST preserve these typed request and response boundaries so fixture repositories can be replaced without changing product clients.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/internal/v1/agent/turns` | Produce the current compatibility Agent Decision proposal |
| `POST` | `/internal/v1/policy/search` | Retrieve cited policy evidence |
| `POST` | `/internal/v1/knowledge/search` | Retrieve applicable approved knowledge chunks with exact citations |
| `POST` | `/internal/v1/claim-history/search` | Retrieve relevant history evidence |
| `POST` | `/internal/v1/claims/create` | Create a claim through the configured claims adapter |
| `GET` | `/internal/v1/claims/{claim_id}/external-tasks` | List operational third-party tasks with their request and linked evidence identifiers |
| `POST` | `/internal/v1/claims/{claim_id}/evidence/{evidence_id}/processing` | Record completed evidence extraction |
| `POST` | `/internal/v1/assessors/route` | Request a rule-authorised assessor action |

### `POST /internal/v1/agent/turns`

The orchestration request contains references and a bounded context package, not every stored message:

```json
{
  "claim_id": "clm_01J4Y7Q2AW",
  "claim_revision": 7,
  "session_id": "ses_01J4Y7RPN8",
  "trigger_message_id": "msg_01J4Y7T1KC",
  "context": {
    "claim_snapshot": {},
    "unresolved_questions": [],
    "recent_message_refs": ["msg_01J4Y7T1KC"],
    "policy_evidence_refs": [],
    "history_evidence_refs": [],
    "token_budget": 6000
  }
}
```

Response is a complete current-compatibility `AgentDecision` proposal. Deterministic validation MUST run before high-impact changes or side effects. The full model prompt, hidden reasoning, and secrets are not part of the public contract or ordinary logs.

The current endpoint maps `ASK`, `CLARIFY`, `CONFIRM`, `PROCEED`, `UPDATE`,
`HANDOFF`, `URGENT_HANDOFF`, and `CREATE_CLAIM` to its legacy decision shape. New
provider adapters must not create an incompatible private vocabulary or mistake this
compatibility enum for the complete target action model.

The persisted decision records both `customer_response` and
`customer_next_step`. `customer_response` is the contextual conversational
reply to the triggering message. `customer_next_step` is the structured status,
responsibility, required work, and timing shown outside the conversation. The
Agent message uses `customer_response`; clients must not manufacture a chat
reply by repeating the next-step summary. For a model-backed proposal, these
claimant-visible fields and `customer_reason` are server-rendered from the
validated action and authority outcome; untrusted model prose is not persisted
as the claimant response. The internal decision records `proposal_source` and
bounded model provenance when applicable. The executable prompt identifier, provider model, and
provider request identifiers must not appear in claimant projections.

Routine model context is task-minimal. It includes the current claimant text and
only explicitly allow-listed, current-action form values. Policy numbers, contact
preferences, addresses and incident locations, other parties, police references,
emergency-service records, and vehicle registrations are excluded. A model proposal
cannot create internal review signals; a non-empty model `proposed_signals` value
invalidates the complete turn before persistence.

#### Target Agent Turn Migration Boundary

The target Agent Runtime contract uses:

```text
provider-neutral ModelRequest
-> current ModelResponse or a future higher-level ModelResult
-> structured AgentProposal
-> Registry and authority validation
-> ExecutionPlan containing approved and rejected ActionEnvelopes
-> tool and Claim-state execution
-> TurnResult containing actual outcomes and final role projection
```

A target `TurnPlan` may contain multiple detected intents, conversation moves,
content-branch candidates, form-patch proposals, Claim-command proposals, tool requests,
unresolved work, and limitations, with one primary Runtime control directive.

This section is a migration boundary, not an implemented route or payload. The target
types beyond the existing `ModelRequest`, `ModelResponse`, and legacy `AgentProposal`
enter a versioned HTTP contract only when backend models, Model Gateway,
persistence, claimant and Workbench consumers, fixtures, generated OpenAPI, and contract
tests are updated in the same pull request. Until then, `/internal/v1/agent/turns`
continues to use the compatibility request and `AgentDecision` response above.

### `POST /internal/v1/knowledge/search`

Retrieves approved knowledge chunks after exact applicability filtering. Requires an integration
principal. This route searches policy wording and guidance; it does not retrieve a customer's
structured policy schedule or make a coverage decision.

Request:

```json
{
  "question": "How much excess do I have to pay?",
  "jurisdiction": "NZ",
  "visibility": "customer_and_staff",
  "document_id": "nw-policy-motor-standard-mvp-2026-1",
  "authority": "northwind_synthetic_demo",
  "version": "MVP-2026.1",
  "insurer": "Northwind Insurance",
  "product": "motor",
  "effective_at": "2026-08-25T00:00:00Z",
  "limit": 3
}
```

An `evidence_found` response contains exact `document_id`, `chunk_id`, `section_path`, source URI,
version, checksum, and source text for every result. `no_evidence` returns no results and an honest
scope limitation. `unavailable` returns no results and a claimant-safe dependency limitation.
Provider errors and object-store identifiers are not exposed. Missing applicability fields fail
request validation rather than broadening the search.
When a structured Policy Schedule supplies a wording document identifier, the caller includes
`document_id`; retrieval then fails closed unless the indexed wording matches that exact document.
The approved document catalogue comes from the controlled publication manifest. Applicability is
filtered before indexed objects are read, and a chunk whose governed identity, source metadata,
or checksum differs from that manifest is treated as unavailable rather than returned as evidence.

### `POST /internal/v1/policy/search`

Retrieves provider-neutral policy facts for one claim. Requires an integration
principal.

Request:

```json
{
  "claim_id": "clm_01J4Y7Q2AW",
  "policy_reference": "synthetic-policy-101",
  "question": "Does this event require professional coverage review?",
  "effective_at": "2026-08-09T22:15:00Z"
}
```

Response:

```json
{
  "result_id": "pol_01J4Y93M22",
  "status": "evidence_found",
  "source": {
    "system": "fixture_policy_administration",
    "reference": "synthetic-policy-101",
    "retrieved_at": "2026-08-19T03:45:30Z"
  },
  "facts": {
    "policy_reference": "synthetic-policy-101",
    "product": "motor",
    "status": "active",
    "excess_amount": 500.0,
    "currency": "NZD",
    "coverage_sections": ["accidental_damage", "third_party_liability"]
  },
  "uncertainty": [],
  "limitations": [],
  "retrieved_at": "2026-08-19T03:45:30Z"
}
```

Status is `evidence_found`, `no_evidence`, `ambiguous`, or `unavailable`.

- `evidence_found` returns allow-listed facts with the `source` that supplied
  them, and persists a retrieval record against the claim.
- `ambiguous` returns the same facts plus explicit `uncertainty`. Each
  uncertainty becomes a staff-only professional-review signal. Ambiguity is
  reported as evidence for a person; it is never resolved here.
- `no_evidence` means the provider answered and holds no matching record.
- `unavailable` means the provider could not answer. It carries `limitations`
  and never carries `facts` or a `source`, and nothing is persisted, because an
  absent answer must not become a finding.

Retrieval provides evidence and limitations, not authority to decide coverage.
Provider-only scoring, fraud labels, and coverage verdicts are discarded at the
adapter boundary and never appear in a response or in storage.

### `POST /internal/v1/claim-history/search`

Retrieves purpose-limited claim history. Requires an integration principal.

Request:

```json
{
  "claim_id": "clm_01J4Y7Q2AW",
  "history_reference": "synthetic-history-204",
  "purpose": "relevant_history_review",
  "limit": 10
}
```

Response:

```json
{
  "result_id": "his_01J4Y95E0P",
  "status": "evidence_found",
  "source": {
    "system": "fixture_claims_history",
    "reference": "synthetic-history-204",
    "retrieved_at": "2026-08-19T03:46:20Z"
  },
  "facts": {
    "history_reference": "synthetic-history-204",
    "incident_type": "motor",
    "occurred_at": "2025-10-03T00:00:00Z",
    "status": "closed",
    "outcome": "settled"
  },
  "uncertainty": [],
  "limitations": [],
  "retrieved_at": "2026-08-19T03:46:20Z"
}
```

`purpose` is an allow-list, not free text, so a caller cannot widen the reason
for reading a claimant's history. `relevant_history_review` is the only accepted
value; anything else is rejected with `422`. Status values and the `unavailable`
rules match the policy endpoint.

Results provide evidence only and MUST NOT return an automated fraud
conclusion.

### Retrieval provider availability

### Dependency availability

`GET /health/ready` reports what is actually wired behind every replaceable
adapter:

| Check | Meaning |
|---|---|
| `persistence` | the selected transactional repository adapter |
| `policy`, `claim_history` | the retrieval adapter |
| `knowledge_documents`, `knowledge_retrieval` | the knowledge store and retrieval adapters |
| `handoff_dispatch` | the staff queue notification service |
| `evidence_storage` | the evidence object store |
| `claims_service` | the external claim-creation service |

Each reports `using_fixture` when the fixture adapter answers under the production
contract, `configured_service` when the explicitly configured S3-compatible object
adapter passes its bucket health check, and `unavailable` while a required adapter is
in an outage. A fixture says it is a fixture; it never claims to be the real provider.

Every unconfirmed provider capability stays visible as its own check and remains
`pending_confirmation` until its access is verified, so a working fixture can never be
mistaken for a confirmed Cloudflare, MongoDB, AWS, or Northwind service.

The application already exposes provider-neutral seams for `persistence` and `agent`:
`create_app()` injects a `PersistenceRepository` and an `AgentTurnProvider`, defaulting
to the current `FixtureRepository` and `ControlledAgent` implementations. The fixture
data runtime reports `persistence`, evidence, policy/history, and knowledge capabilities
as `using_fixture`. The remaining Agent gap is model-provider readiness, so `agent`
continues to report `not_configured` until a model gateway is configured and verified.

An evidence-storage outage is reported to the caller as `503`
`DEPENDENCY_UNAVAILABLE` with `retryable: true`, never as a media-type or size
rejection, and leaves the claim unchanged. Registering evidence the claimant
does not yet hold does not touch the object store, so that path keeps working
during an outage.

### `GET /internal/v1/claims/{claim_id}/external-tasks`

Lists the provider-neutral operational tasks recorded for one Working Claim. The route requires
integration-service credentials and is not a claimant or browser projection. Each item carries
the task's claim association, service identity, requested action, integration source, operation
status, delivery state, bounded failure or provider reference when present, creation and update
times, the request preparation/send record when one exists, and the evidence identifiers mapped
to that task. `request` remains nullable for task records created before request persistence was
introduced.

The query accepts a positive `limit`, defaulting to 25, and an opaque `cursor`. Values above 100
are truncated to 100; values below 1 return `422 VALIDATION_ERROR`. Results use the stable
`(created_at, task_id)` ascending order and return the next cursor in `page.next_cursor`. Clients
must reuse the returned cursor unchanged.

```json
{
  "claim_id": "clm_01J4Y7Q2AW",
  "items": [
    {
      "task": {
        "task_id": "tsk_01J4Y7VZ82",
        "claim_id": "clm_01J4Y7Q2AW",
        "service_identity": "vehicle_damage_assessment_routing",
        "requested_action": "vehicle_damage_assessment",
        "integration_source": "fixture",
        "status": "accepted",
        "delivery": "submitted",
        "delivery_evidence": "fixture routing acknowledgement: asr_fixture_11d35f649a",
        "failure_code": null,
        "provider_reference": "asr_fixture_11d35f649a",
        "created_at": "2026-09-02T01:01:00Z",
        "updated_at": "2026-09-02T01:01:01Z"
      },
      "request": {
        "request_id": "erq_4d29a6dbafdf5ed57152f15c",
        "task_id": "tsk_01J4Y7VZ82",
        "claim_id": "clm_01J4Y7Q2AW",
        "service_identity": "vehicle_damage_assessment_routing",
        "requested_action": "vehicle_damage_assessment",
        "purpose": "Route the vehicle damage assessment request using the confirmed incident region. This does not decide coverage or approve repairs.",
        "disclosed_fields": [
          "authorisation_ref",
          "claim_id",
          "claimant_consent_ref",
          "external_claim_id",
          "location.region",
          "requested_action"
        ],
        "authorisation": {
          "northwind_authority_ref": "dec_01J4Y7V7B2",
          "claimant_consent_ref": "cns_01J4Y7V8PT",
          "authorised_revision": 8
        },
        "prepared_at": "2026-09-02T01:01:00Z",
        "sent_at": "2026-09-02T01:01:01Z",
        "operation_id": "asr_op_b6bd9fb0b17ec1138d914c5d"
      },
      "evidence_ids": ["evd_01J4Y7V5QJ"]
    }
  ],
  "page": {"next_cursor": null}
}
```

The task record stays outside shared Claim State. A fixture task remains labelled `fixture`, and
the route never converts an unavailable or unverified provider capability into
`configured_service`. Provider references and delivery evidence are operational fields and must
not be copied into claimant projections. `request.sent_at` means Northwind invoked the selected
service entry; it does not by itself prove provider receipt. Task `delivery=submitted` is recorded
only when the entry returns a named acknowledgement. In the fixture profile that acknowledgement
and provider reference remain explicitly synthetic.

### `POST /internal/v1/claims/{claim_id}/evidence/{evidence_id}/processing`

Records the typed result of image or document extraction after an accepted
upload reaches `processing`.

Request:

```json
{
  "facts": [
    {
      "field_code": "incident.description",
      "value": "Rear panel damage is visible.",
      "confidence": 0.87
    }
  ]
}
```

This service-to-service request requires integration credentials,
`Idempotency-Key`, and `If-Match`. It moves the evidence file from `processing`
to `ready` and writes registered extracted fields as `proposed`.

Extraction may only fill a field the shared form does not hold yet. If any
target field already exists — in any state, including `proposed`, `disputed`,
`missing`, and `pending_generation`, not only `confirmed` — the request is
rejected with `409 INVALID_STATE_TRANSITION` and nothing is written. Writing
into an occupied field would replace its value, source, and source references,
so an earlier claimant proposal or a disputed value would stop being traceable.
The existing field must be resolved first.

Transition provenance records source, actor, and accepted time for the file and
each proposed fact.

### `POST /internal/v1/claims/create`

Creates the external claim only after a validated `CREATE_CLAIM` decision.

Request:

```json
{
  "working_claim_id": "clm_01J4Y7Q2AW",
  "claim_revision": 9,
  "authorised_decision_id": "dec_01J4YD82JA",
  "confirmed_form": {},
  "evidence_refs": ["evd_01J4Y7V5QJ"],
  "pending_evidence": [
    {
      "evidence_id": "evd_01J4Y7V5QJ",
      "kind": "police_report",
      "needed_for": ["later_action"]
    }
  ],
  "route": "standard_motor_intake"
}
```

Response `201` or `200` for an idempotent replay:

```json
{
  "external_claim_id": "ext_fixture_1042",
  "claim_number": "NWF-2026-001042",
  "creation_status": "created",
  "route": "standard_motor_intake",
  "next_step": "Claims intake review",
  "source": "fixture",
  "expected_by": "2026-08-11T05:00:00Z",
  "created_at": "2026-08-10T03:55:00Z"
}
```

The adapter MUST use the working claim ID as its idempotency reference. `creation_status` is `created`, `pending`, or `failed`. Pending evidence is preserved as outstanding work rather than silently dropped.

`source` is `fixture` for the explicitly selected deterministic adapter or `configured_service` for a
confirmed provider adapter. A result MUST NOT claim `configured_service` merely because
an integration is planned. An unavailable configured service remains explicit and MUST
NOT silently fall through to another data runtime profile.

The request and response above are the provider-neutral boundary. Provider table names,
partition keys, regions, SDK payloads, ARNs, credentials and vendor error bodies MUST
remain inside a future adapter and are rejected if supplied as request fields.

### `POST /internal/v1/assessors/route`

Request requires an authorised rule or staff decision:

```json
{
  "claim_id": "clm_01J4Y7Q2AW",
  "external_claim_id": "ext_fixture_1042",
  "authorisation_ref": "dec_01J4YEBP6X",
  "claimant_consent_ref": "cns_01J4YECONSENT",
  "requested_action": "vehicle_damage_assessment",
  "location": {
    "region": "Auckland"
  }
}
```

Response returns `routing_status`, assessor or queue reference when assigned, claimant-visible next step, expected timing when known, and limitations. Assessor routing MUST NOT be triggered solely by `severity`.

Response `201`, or `200` for an idempotent replay:

```json
{
  "routing_status": "assigned",
  "assessor_reference": "asr_fixture_01",
  "queue_reference": "QUE-AUC-001",
  "next_step": "An assessor will review the confirmed claim information.",
  "expected_by": "2026-08-12T05:00:00Z",
  "limitations": [
    "Synthetic fixture routing; no production assessor was contacted."
  ]
}
```

The authorisation reference must resolve to an authorised decision containing
`ASSESSOR_RULE_AUTHORISED` for the current claim revision. The claimant-consent reference
must resolve from the shared Working Claim to a granted record for
`vehicle_damage_assessment_routing`, the requested action, and the minimum request fields.
The consent actor must be the claimant linked to that Working Claim. Authorised-representative
consent is not accepted until representative identity and authority are explicitly modelled.
Northwind authority and claimant consent are separate requirements; a severity value by itself
is not routing authority.

The controlled fixture can return assigned or queued success. Timeout and unavailable
return `DEPENDENCY_UNAVAILABLE` with `retryable: true`; access-denied or malformed fixture
outcomes return `DEPENDENCY_FAILED` with `retryable: false`. All four preserve the current
claim and include a bounded `assessor_service` reason. An identical retry after a transient
failure uses the same operation identity, and an identical retry after success returns the
accepted result without creating another task.

The first authorised attempt durably reserves the operation identity and complete request
fingerprint before invoking the provider. Reusing that identity with changed input is an
idempotency conflict even when the first attempt timed out or the provider was unavailable.
Provider acceptance is recorded before the Claim State compare-and-set. If a concurrent claim
mutation wins that compare-and-set, an unchanged retry reconciles the recorded result against
the latest claim revision without creating a second provider task.

## Reason Codes

Reason codes are stable machine-readable identifiers. The initial registry includes:

| Category | Codes |
|---|---|
| Intake | `REQUIRED_FIELD_MISSING`, `MATERIAL_FACTS_PROPOSED`, `CLAIMANT_CONFIRMED`, `CLAIMANT_CORRECTED` |
| Evidence | `EVIDENCE_PENDING_GENERATION`, `EVIDENCE_INCOMPLETE`, `EVIDENCE_UNOFFICIAL`, `EVIDENCE_INCONSISTENT`, `EXTRACTION_REQUIRES_CONFIRMATION` |
| Policy | `POLICY_EVIDENCE_FOUND`, `COVERAGE_AMBIGUOUS`, `POLICY_SECTION_CONFIRMED` |
| Support | `HUMAN_REQUESTED`, `REPEATED_HUMAN_REQUEST`, `ACCESSIBILITY_SUPPORT_REQUIRED`, `DISTRESS_DETECTED`, `SUPPORT_NEED_MET` |
| Safety | `INJURY_REPORTED`, `CONTINUING_DANGER`, `IMMEDIATE_SAFETY_RISK` |
| Review | `COMPLEX_EVENT_REVIEW`, `CONFLICT_REQUIRES_REVIEW`, `HISTORY_INCONSISTENCY_REVIEW`, `SOURCE_RECORD_NOT_COMPARABLE` |
| Workflow | `NEXT_ACTION_READY`, `CLAIM_CREATION_AUTHORISED`, `CLAIM_CREATED`, `ASSESSOR_RULE_AUTHORISED`, `HANDOFF_ACCEPTED` |
| Integration | `POLICY_SERVICE_UNAVAILABLE`, `HISTORY_SERVICE_UNAVAILABLE`, `CLAIMS_SERVICE_UNAVAILABLE`, `EVIDENCE_PROCESSING_FAILED` |

New codes require documentation and contract tests. Free-text explanations may accompany a code but MUST NOT replace it.

## Error Contract

All errors use one envelope:

```json
{
  "error": {
    "code": "REVISION_CONFLICT",
    "message": "The claim changed after this page was loaded.",
    "request_id": "req_01J4Y9C60M",
    "details": [
      {
        "field": "If-Match",
        "reason": "Expected revision 7; current revision is 8."
      }
    ],
    "retryable": true,
    "current_revision": 8
  }
}
```

| Error code | Status | Meaning |
|---|---:|---|
| `VALIDATION_ERROR` | `422` | Request schema or field validation failed |
| `AUTHENTICATION_REQUIRED` | `401` | No valid principal |
| `ACCESS_DENIED` | `403` | Principal lacks permission |
| `RESOURCE_NOT_FOUND` | `404` | Resource absent or concealed |
| `INVALID_STATE_TRANSITION` | `400` | Requested transition is not allowed |
| `REVISION_REQUIRED` | `409` | Required `If-Match` header absent |
| `REVISION_CONFLICT` | `409` | Claim changed since the client read it |
| `IDEMPOTENCY_CONFLICT` | `409` | Key was reused with a different request |
| `VALIDATION_FAILED` | `422` | One or more requested validation scenarios failed |
| `CONFIGURATION_APPROVER_CONFLICT` | `403` | A high-impact configuration's sole author attempted publication |
| `PROVIDER_CONFIGURATION_INVALID` | `422` | Provider configuration is incomplete or structurally invalid |
| `PROVIDER_CONFIGURATION_UNAVAILABLE` | `422` | Provider configuration is unverified or outside deployment authority |
| `SECRET_VALUE_FORBIDDEN` | `422` | Secret values must use protected references |
| `ACTIVE_SESSION_EXISTS` | `409` | A conflicting active session exists |
| `UNSUPPORTED_MEDIA_TYPE` | `415` | File type is not allowed |
| `UPLOAD_TOO_LARGE` | `413` | File exceeds configured size |
| `RATE_LIMITED` | `429` | Caller exceeded a limit |
| `DEPENDENCY_UNAVAILABLE` | `503` | Required service is unavailable |
| `DEPENDENCY_FAILED` | `502` | Required service returned an invalid or failed result |
| `INTERNAL_ERROR` | `500` | Unexpected server failure |

Customer error messages MUST be actionable and MUST NOT expose stack traces, prompts, credentials, internal-only signals, policy records belonging to another customer, or infrastructure details.

Agent Runtime and Model Gateway may use a richer internal error record with `layer`,
`retry_class`, `state_effect`, safe message key, diagnostic reference, and optional safe
provider category. That internal record maps to the existing public error envelope; it
does not expose provider payloads or silently create new HTTP status semantics.

The target internal registry includes distinct conditions for model timeout, rate limit,
unavailability, refusal, incomplete or malformed output, capability mismatch, context
overflow, inapplicable or conflicting retrieval, unverifiable evidence, invalid tool
arguments, unavailable tools, unknown external outcomes, idempotency conflict, and
handoff-queue failure. These codes become normative API values only with implementation
and contract tests.

## Health Endpoints

### `GET /health/live`

Returns `200` when the process can serve requests:

```json
{
  "status": "ok"
}
```

### `GET /health/ready`

Returns readiness without secrets or private configuration:

```json
{
  "status": "degraded",
  "checks": {
    "persistence": "using_fixture",
    "data_runtime_profile": "fixture",
    "object_storage_adapter": "fixture",
    "agent": "not_configured",
    "policy": "using_fixture",
    "claim_history": "using_fixture",
    "knowledge_documents": "using_fixture",
    "knowledge_retrieval": "using_fixture",
    "claims_service": "using_fixture",
    "aws_claims_service": "pending_confirmation",
    "evidence_storage": "using_fixture"
  },
  "checked_at": "2026-08-10T03:58:00Z"
}
```

Readiness is `ok`, `degraded`, or `unavailable`. A required configured data capability
reporting `unavailable` makes overall readiness `unavailable`; otherwise the current
fixture/model combination remains `degraded`. A fixture is not reported as a real
connected service.

`data_runtime_profile` and `object_storage_adapter` identify the single selected runtime
bundle and object-store adapter. They are labels only; connection credentials, endpoints,
physical keys, and provider payloads are never returned. A process must report one profile and
must not combine capabilities from another profile.

The `agent` check is `not_configured` for the default controlled prototype provider and
`configured` when the provider-neutral model gateway has composed successfully. The
latter reports local configuration only; it does not claim remote connectivity, valid
credentials, model quality, or production readiness. Readiness never returns the model
base URL, model identifier, credential reference, or credential value.

## Model Provider Boundary

Model transport is an internal dependency and does not add a public API route. Agent
orchestration consumes the provider-neutral `ModelRequest` and `ModelResponse` contracts,
then converts structured output to the existing `AgentProposal`. Existing deterministic
authority and state validation still controls execution.

`ModelResponse` distinguishes complete, incomplete, refused, and unknown provider termination.
Only a complete response can become an `AgentProposal`; all other outcomes fail before the Message
API writes Claim State, messages, decisions, or idempotency results.

The implemented `openai_compatible` adapter supports official, relay, and local
compatible chat-completions endpoints through configuration. Non-compatible protocols
register another adapter against the same internal contract without changing claimant
or staff routes. Capability and failure semantics are documented in
[Model Gateway](model-gateway.md).

## Persistence and Provider Boundary

The public API does not expose physical keys, collection or table names, indexes, object-store keys, vector-index names, model-provider payloads, runtime-profile configuration, or external claims-system schemas.

The persistence layer MUST support at least:

- customers and permitted communication preferences;
- working claims and independent state dimensions;
- structured form field records and revisions;
- sessions, compact summaries, unresolved questions, and commitments;
- complete messages stored outside routine model context;
- evidence metadata, provenance, processing state, and secure object references;
- current Agent Decisions and, after the coordinated migration, TurnPlans,
  AgentProposals, ExecutionPlans, ActionEnvelopes, ToolRequests and results, and
  TurnResults;
- content-branch references, lifecycle state, and independent WorkItems;
- reason codes, policy and Registry versions, authority checks, state effects, usage,
  latency, and limitations;
- internal signals and lifecycle decisions;
- handoffs, assignments, staff actions, and claimant updates;
- external claim creation results and conditional assessor actions;
- external-request preparation, disclosure, authority, submission, tracking,
  verification, unknown outcome, and reconciliation records;
- append-only claim events and aggregate metric events;
- idempotency records and optimistic-concurrency revisions.

Fixture and configured adapters MUST implement the same provider-neutral domain ports.
Exactly one complete data runtime profile is selected when a process starts. Cloudflare,
MongoDB, AWS, and fixture profiles are alternatives; the API MUST NOT silently combine
their persistence or retrieval stores. Detailed data classes, profile composition, and
RAG boundaries are defined in `docs/data-architecture.md`.

The current composition root implements the complete fixture bundle. Selecting an
unimplemented Cloudflare, MongoDB, or AWS profile fails process startup explicitly; it
does not create a partial provider bundle or fall back to fixture capabilities. The
selected deployment profile itself is not returned by the public API.

The model gateway remains an implemented provider-neutral internal dependency, and model
selection is independent of the mutually exclusive data-runtime profile. Future model
profile management, Gateway administration, and other Admin API routes and payloads are
added to this contract only with the corresponding implementation, consumer,
persistence, fixture, generated-OpenAPI, and contract-test changes.

## Contract Verification

Before an endpoint is treated as implemented:

- request, success, and error schemas have automated contract tests;
- authentication, ownership, role, and visibility rules are tested;
- idempotency and stale-revision behaviour are tested for mutations;
- state transitions and reason codes are tested against repeatable fixtures;
- internal-only fields are proven absent from claimant responses;
- integration failure preserves working claim progress and returns a bounded error;
- generated OpenAPI output matches this contract;
- the claimant client and workbench use the versioned route.

## Open Decisions

These decisions do not prevent continued MVP implementation, but production behaviour cannot be claimed until they are resolved:

1. Production identity, Northwind data schemas, matching keys, access methods, regions, and available provider services.
2. Production field registry and required fields by motor, home, and contents claim type.
3. Approved coverage, severity, fraud-review, urgent escalation, claim-creation, and assessor-routing rules.
4. Whether the first explicit human request transfers immediately or offers one brief choice to finish the current step.
5. Production evidence size, media type, malware scanning, retention, and deletion controls.
6. External claims-system and assessor-system response semantics and service-level expectations.
7. Production rate limits, idempotency retention, audit retention, and operational metric access thresholds.
8. Final deployment topology: in-process adapters or separately deployed internal services.
9. Admin API resources, configuration approval levels, publication, rollback, secret references, and audit access.
10. Model-gateway and knowledge-management API capabilities introduced by issues #204 and the Control Plane delivery plan.
11. Versioning and compatibility period for replacing the legacy eight-action
    `AgentDecision` transport with TurnPlan, namespaced ActionEnvelope, ExecutionPlan,
    and TurnResult contracts.
12. Production model-profile capabilities, privacy classes, fallback groups, evaluation
    thresholds, and validity periods for each Agent purpose.
