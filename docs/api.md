# Northwind FNOL API Contract

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

The broader product includes an Administration and Control Plane for versioned system configuration, but this version of the API contract does not yet define an Admin API. Administration must remain separate from claimant and staff claim operations.

The API does not authorise the agent to approve or reject claims, make an unreviewed high-impact coverage decision, determine fraud, diagnose injury, or claim that emergency services were contacted when they were not.

## Actors and Access

| Actor | Permitted boundary |
|---|---|
| Claimant | Their own claimant-visible claim data, sessions, messages, form corrections, evidence, support requests, and status updates |
| Claims professional | Assigned or permitted workbench claims, internal evidence, handoffs, signals, staff actions, and claimant updates |
| Claims operations | Workbench data, routing and service metrics, subject to operational role permissions |
| System administrator | Versioned system configuration, knowledge, integrations, access, evaluation, health, and audit through a separately contracted Admin API |
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
        \-- External Claim Reference
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
| Decision | `dec_01J4Y7W90S` |
| Handoff | `hnd_01J4Y7XG2C` |
| Signal | `sig_01J4Y7Z0EH` |
| Staff action | `act_01J4Y80B7D` |
| Claim event | `evt_01J4Y81HNM` |

### Agent Action

`AgentAction` is one of:

```text
ASK | CLARIFY | CONFIRM | PROCEED | UPDATE | HANDOFF | URGENT_HANDOFF | CREATE_CLAIM
```

Policy lookup, history lookup, evidence extraction, claim creation, and assessor routing are tools or side effects. They are not additional agent actions.

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
| `incident_type` | string | No | Registered claim type; may be unknown at creation |
| `claim_state` | `ClaimState` | Yes | Canonical internal multi-dimensional state |
| `form` | field map | Yes | Registered field code to `StructuredFormField`; initially empty |
| `evidence_summary` | `EvidenceSummary` | Yes | Authoritative aggregate over the full persisted evidence set; claimant projections recompute it from claimant-visible evidence only |
| `route` | string | No | Configured processing route, not a decision outcome |
| `active_session_id` | string | No | Current active session when one exists |
| `external_claim` | object | No | Claim service result after creation begins |
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

### Agent Decision

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
| `GET` | `/claims/{claim_id}/evidence` | List claimant-visible evidence state |
| `POST` | `/claims/{claim_id}/evidence` | Register expected, missing, or pending evidence |
| `POST` | `/claims/{claim_id}/evidence/uploads` | Request an evidence upload target |
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
  "customer_next_step": {},
  "created_at": "2026-08-10T03:40:00Z",
  "updated_at": "2026-08-10T03:50:00Z"
}
```

The claimant-facing `evidence_summary` MUST be calculated only from evidence records visible through the claimant evidence projection. It MUST NOT include counts derived from `internal_only` evidence or any record excluded from `GET /claims/{claim_id}/evidence`. The persisted Working Claim retains the authoritative aggregate over the full persisted evidence set for staff and operational use; persistence adapters MUST preserve that full aggregate. Claimant-safe aggregation is applied only at the claimant projection boundary.

The `form` contains claimant-visible structured field records. `external_claim`, when present, contains `claim_number`, `creation_status`, `route`, `created_at`, and claimant-visible expected timing.

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
  "handoff": null
}
```

Only the customer-safe decision projection is returned. Internal required tools, confidence, signals, and authority details remain available through authorised internal APIs and events.

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
  "customer_next_step": {
    "status": "claim_created",
    "summary": "Claims intake review",
    "responsible_party": "northwind"
  }
}
```

An idempotent replay restores the same response. The mock adapter supplies synthetic values only;
this contract does not assert a Northwind provider schema or AWS implementation.

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

This request requires `Idempotency-Key` and `If-Match`. The URL is illustrative
and is never stored in fixtures or claim records. The adapter MAY use fixture
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
ownership, and stored object identity before accepting the item. Image-derived
fields remain proposed until a claimant or authorised staff member confirms
them; completion never silently writes extracted values into the confirmed
form.

The Sprint 2 mock adapter returns `202` and records the public `file_status` as
`processing` after an image or PDF upload is accepted. Filename, media type,
size, and processing status can be read back from the evidence list. Storage
keys, checksums, processing references, and file contents remain internal.

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

Loads a bounded, mixed local workbench demonstration queue. AT-02, AT-04, and AT-05 exercise
professional-review and human-handoff work, AT-06 exercises claimant, external-agency, and
internal pending-evidence waits, while AT-10 exercises a created claim routed to an assessor.
This endpoint is not a handoff-only seed boundary. It is an explicit staff action: the
workbench never calls it during page load. The route requires the synthetic staff credential, is
available only in development and test environments, and returns
`409 DEMO_SEED_REQUIRES_EMPTY_QUEUE` if claims already exist. Reset the local demo before loading
this set again. Runtime demo records are maintained under `backend/demo_data/scenarios/`, not
under the test fixture tree.

Response `200`:

```json
{
  "status": "seeded",
  "scenario_ids": [
    "AT-02-coverage-ambiguity",
    "AT-04-urgent",
    "AT-05-human-request",
    "AT-06-pending-evidence",
    "AT-10-controlled-assessor"
  ],
  "claim_ids": [
    "clm_fixture_at02",
    "clm_fixture_at04",
    "clm_fixture_at05",
    "clm_fixture_at06",
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
| `POST` | `/internal/v1/agent/turns` | Produce and validate one agent decision proposal |
| `POST` | `/internal/v1/policy/search` | Retrieve cited policy evidence |
| `POST` | `/internal/v1/claim-history/search` | Retrieve relevant history evidence |
| `POST` | `/internal/v1/claims/create` | Create a claim through the configured claims adapter |
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

Response is a complete `AgentDecision` proposal. Deterministic validation MUST run before high-impact changes or side effects. The full model prompt, hidden reasoning, and secrets are not part of the public contract or ordinary logs.

The canonical product actions are `ASK`, `CLARIFY`, `CONFIRM`, `PROCEED`,
`UPDATE`, `HANDOFF`, `URGENT_HANDOFF`, and `CREATE_CLAIM`. They are business
action semantics rather than MCP commands or provider tool names. Each action
has stable preconditions, allowed state paths, tool policy, authority outcome,
claimant-response requirement, and prohibited outcomes. A model-backed provider
or MCP-connected tool adapter must implement these semantics rather than create
an incompatible private action vocabulary.

The persisted decision records both `customer_response` and
`customer_next_step`. `customer_response` is the contextual conversational
reply to the triggering message. `customer_next_step` is the structured status,
responsibility, required work, and timing shown outside the conversation. The
Agent message uses `customer_response`; clients must not manufacture a chat
reply by repeating the next-step summary.

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

Each reports `using_fixture` when the adapter answers under the production
contract, and `unavailable` while it is in an outage. A fixture says it is a
fixture; it never claims to be the real provider.

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
`ASSESSOR_RULE_AUTHORISED`. A severity value by itself is not routing authority.

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
| `ACTIVE_SESSION_EXISTS` | `409` | A conflicting active session exists |
| `UNSUPPORTED_MEDIA_TYPE` | `415` | File type is not allowed |
| `UPLOAD_TOO_LARGE` | `413` | File exceeds configured size |
| `RATE_LIMITED` | `429` | Caller exceeded a limit |
| `DEPENDENCY_UNAVAILABLE` | `503` | Required service is unavailable |
| `DEPENDENCY_FAILED` | `502` | Required service returned an invalid or failed result |
| `INTERNAL_ERROR` | `500` | Unexpected server failure |

Customer error messages MUST be actionable and MUST NOT expose stack traces, prompts, credentials, internal-only signals, policy records belonging to another customer, or infrastructure details.

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

Readiness is `ok`, `degraded`, or `unavailable`. A fixture is not reported as a real connected service.

## Persistence and Provider Boundary

The public API does not expose physical keys, collection or table names, indexes, object-store keys, vector-index names, model-provider payloads, runtime-profile configuration, or external claims-system schemas.

The persistence layer MUST support at least:

- customers and permitted communication preferences;
- working claims and independent state dimensions;
- structured form field records and revisions;
- sessions, compact summaries, unresolved questions, and commitments;
- complete messages stored outside routine model context;
- evidence metadata, provenance, processing state, and secure object references;
- agent decisions, reason codes, tool references, and validation outcomes;
- internal signals and lifecycle decisions;
- handoffs, assignments, staff actions, and claimant updates;
- external claim creation results and conditional assessor actions;
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

The model gateway and future Admin API also remain provider-neutral. Their HTTP routes
and payloads are added to this contract only with the corresponding implementation,
consumer, fixture, and contract-test changes.

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
