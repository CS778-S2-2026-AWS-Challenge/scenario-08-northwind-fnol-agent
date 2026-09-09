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

Staff authentication is a separate account and session boundary. `POST
/api/v1/staff/auth/sessions` verifies staff credentials and returns a short-lived opaque bearer
token; only its hash, staff ID, creation time, expiry, and revocation state are stored. `GET
/api/v1/staff/auth/session` and `GET /api/v1/staff/me` require that staff token. `DELETE
/api/v1/staff/auth/session` revokes it immediately. A claimant session cannot cross into these
routes, and a staff session cannot cross into claimant account routes.

Normal-mode local runtimes use the separate SQLite staff identity adapter configured by
`NORTHWIND_STAFF_IDENTITY_DB_PATH`. An initial account may be provisioned explicitly with
`NORTHWIND_STAFF_BOOTSTRAP_EMAIL`, `NORTHWIND_STAFF_BOOTSTRAP_PASSWORD`, and
`NORTHWIND_STAFF_BOOTSTRAP_DISPLAY_NAME`; the plaintext password is never persisted. This is a
real persistent local login path, but it is not an enterprise IdP, SSO, MFA, recovery, or complete
staff-entitlement implementation. Production deployment still requires an approved identity
provider adapter.

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
| `POST` | `/internal/v1/admin/configurations/{configuration_id}/approval` | Record one independent approval decision for an awaiting-approval revision; requires `If-Match` and `Idempotency-Key` |
| `GET` | `/internal/v1/admin/configurations/{configuration_id}/approvals` | Read immutable approval decisions, optionally filtered by revision |
| `POST` | `/internal/v1/admin/configurations/{configuration_id}/publish` | Publish an approved high-impact draft; requires `If-Match` and `Idempotency-Key` |
| `POST` | `/internal/v1/admin/configurations/{configuration_id}/withdraw` | Withdraw a draft or published revision; requires `If-Match` and `Idempotency-Key` |
| `POST` | `/internal/v1/admin/configurations/{configuration_id}/rollback` | Publish an approved prior revision as a new record; requires `If-Match` and `Idempotency-Key` |
| `GET` | `/internal/v1/admin/configurations/{configuration_id}/audit` | Read append-only lifecycle audit events |
| `GET` | `/internal/v1/admin/release-sets` | List runtime release sets, optionally filtered by environment and runtime profile |
| `POST` | `/internal/v1/admin/release-sets` | Create a draft release set from versioned configuration references; requires `Idempotency-Key` |
| `GET` | `/internal/v1/admin/release-sets/{release_set_id}` | Read one release set |
| `POST` | `/internal/v1/admin/release-sets/{release_set_id}/validate` | Validate referenced configuration versions; requires `If-Match` and `Idempotency-Key` |
| `POST` | `/internal/v1/admin/release-sets/{release_set_id}/publish` | Publish a validated release set; requires `If-Match` and `Idempotency-Key` |
| `POST` | `/internal/v1/admin/release-sets/{release_set_id}/rollback` | Publish a validated prior release set as a new record; requires `If-Match` and `Idempotency-Key` |
| `GET` | `/internal/v1/admin/release-sets/{release_set_id}/audit` | Read append-only release-set audit events |
| `GET` | `/internal/v1/admin/runtime-snapshots` | Resolve the complete published release set for an environment and runtime profile |
| `GET` | `/internal/v1/admin/accounts/customers` | List customer account projections with cursor pagination |
| `POST` | `/internal/v1/admin/accounts/customers` | Create a customer account; requires `Idempotency-Key` |
| `PATCH` | `/internal/v1/admin/accounts/customers/{customer_id}` | Update an approved customer account profile or active state; requires `If-Match` and `Idempotency-Key` |
| `GET` | `/internal/v1/admin/accounts/customers/{customer_id}/sessions` | List safe customer session projections with cursor pagination |
| `POST` | `/internal/v1/admin/accounts/customers/{customer_id}/sessions/{session_id}/revoke` | Revoke an active customer session; requires `If-Match` and `Idempotency-Key` |
| `GET` | `/internal/v1/admin/accounts/customers/{customer_id}/audit` | Read append-only customer account audit events |
| `GET` | `/internal/v1/admin/accounts/staff` | List staff account projections with cursor pagination |
| `POST` | `/internal/v1/admin/accounts/staff` | Create a staff account with registered roles; requires `Idempotency-Key` |
| `PATCH` | `/internal/v1/admin/accounts/staff/{staff_id}` | Update a staff display name, roles, or active state; requires `If-Match` and `Idempotency-Key` |
| `GET` | `/internal/v1/admin/accounts/staff/{staff_id}/sessions` | List safe staff session projections with cursor pagination |
| `POST` | `/internal/v1/admin/accounts/staff/{staff_id}/sessions/{session_id}/revoke` | Revoke an active staff session; requires `If-Match` and `Idempotency-Key` |
| `GET` | `/internal/v1/admin/accounts/staff/{staff_id}/audit` | Read append-only staff account audit events |
| `GET` | `/internal/v1/admin/access/policies` | List versioned role and scope access-policy projections |
| `POST` | `/internal/v1/admin/access/policies` | Create an access-policy configuration draft; requires `Idempotency-Key` |
| `GET` | `/internal/v1/admin/audit` | Search bounded append-only audit events by type, subject, actor, or time |
| `GET` | `/internal/v1/admin/integrations` | List adapter health, capability, source, and published configuration references |
| `GET` | `/internal/v1/admin/integrations/{integration_id}` | Run one bounded health check and return the registered integration projection |
| `POST` | `/internal/v1/admin/integrations/{integration_id}/health-check` | Run and persist one bounded integration health check |
| `GET` | `/internal/v1/admin/integrations/{integration_id}/health-checks` | Read bounded persisted health-check history |
| `GET` | `/internal/v1/admin/operations` | List Control Plane operation records by kind or state |
| `GET` | `/internal/v1/admin/operations/metrics` | Read operation counts, model usage, estimated cost, rate-limit state, and configured alerts |
| `GET` | `/internal/v1/admin/operations/{operation_id}` | Read one operation record and its current status |
| `POST` | `/internal/v1/admin/evaluations` | Record immutable model/knowledge/rule evaluation evidence; requires `Idempotency-Key` |
| `GET` | `/internal/v1/admin/evaluations` | List evaluation evidence by purpose or state |
| `GET` | `/internal/v1/admin/evaluations/{evaluation_id}` | Read one immutable evaluation record |
| `POST` | `/internal/v1/admin/knowledge` | Create a governed knowledge source version; requires `Idempotency-Key` |
| `GET` | `/internal/v1/admin/knowledge` | List knowledge source versions and lifecycle states |
| `GET` | `/internal/v1/admin/knowledge/{knowledge_id}` | Read safe metadata and ingestion/publication status |
| `POST` | `/internal/v1/admin/knowledge/{knowledge_id}/ingest` | Run bounded parsing/chunking/indexing and return its operation record |
| `POST` | `/internal/v1/admin/knowledge/{knowledge_id}/validate` | Record retrieval/publication validation scenarios |
| `POST` | `/internal/v1/admin/knowledge/{knowledge_id}/retrieval-check` | Run a scoped retrieval check with exact citations |
| `POST` | `/internal/v1/admin/knowledge/{knowledge_id}/publish` | Publish an indexed validated version after independent review |
| `POST` | `/internal/v1/admin/knowledge/{knowledge_id}/withdraw` | Withdraw a draft or published knowledge version |
| `GET` | `/internal/v1/admin/knowledge/{knowledge_id}/audit` | Read append-only knowledge lifecycle audit events |
| `GET` | `/internal/v1/admin/agent-rules` | List independently versioned Agent instruction, tool-permission, controlled-rule, and feature records |
| `POST` | `/internal/v1/admin/agent-rules/{component}` | Create a versioned Agent-rule component draft; requires `Idempotency-Key` |

Configuration, Release Set, knowledge, Integration, customer-account, staff-account, and account-
session list or detail projections include `allowed_actions`. Each action contains `action_code`, `availability`
(`available`, `confirmation_required`, or `blocked`), `expected_revision`, and a bounded `reason`.
The projection is derived for the authenticated principal from the current server state; clients
must not reconstruct lifecycle or permission rules from resource fields. A client may submit only
an `available` action directly, must obtain explicit user confirmation for
`confirmation_required`, and must not submit a `blocked` action. `expected_revision` supplies the
`If-Match` value for resources whose HTTP mutation contract exposes optimistic revision and is null
where that client-visible contract is absent. The mutation endpoint independently revalidates
identity and state, plus revision when exposed, so the projection is guidance rather than delegated
authority.

`GET /internal/v1/admin/integrations` is a read-only projection of the adapters assembled by the
composition root. It reports only bounded health states (`using_fixture`, `verified`,
`configured_service`, `pending_confirmation`, `unavailable`, or `unknown`), implementation type,
capability, source class, and published integration configuration IDs. It does not expose provider
payloads, credentials, endpoint secrets, or Claim-level external task records. The list supports
the standard `limit` (1–100) and opaque `cursor` parameters. The per-integration route runs the
same connection-status check for one registered ID and returns bounded latency and failure
metadata; it never invokes a claim operation or provider business action.
The POST health-check route persists only the bounded result (status, source, implementation,
latency, failure code, operation identity, and timestamp); the history route returns those records
and never exposes credentials or provider payloads. Each health check also creates a Control Plane
operation record so queued, running, succeeded, and failed execution status is queryable without
turning the health result into a mutable progress field.

Control Plane operation records use opaque `opr_` identifiers and report a typed kind, subject,
state, monotonic revision, bounded progress, status URL, result or stable error code, and timestamps.
They are operational records only; they cannot mutate Claim State, WorkItems, handoffs, messages,
or configuration values. The operation list supports bounded filters and cursor-shaped responses.

Each claimant or staff model call creates a `model_invocation` operation. Its bounded result contains
the model purpose, provider-reported model identifier when available, nullable input/output/total
token counts, and measured latency in milliseconds. Controlled failures use a stable `MODEL_*`
error code. The record never contains prompts, credentials, provider request payloads, raw provider
responses, or claimant message content.

`GET /internal/v1/admin/operations/metrics` aggregates the complete persisted operation ledger. Its
response contains `total`, `by_state`, `by_kind`, model `usage`, `cost`, `rate_limit`, `alerts`, and
`source`. Usage distinguishes all calls from calls with provider-reported total tokens. Cost is a
rounded estimate in currency microunits and reports `configured`, `partial`, or `unconfigured` plus
priced and unpriced call counts. A missing usage report or model price makes the estimate partial;
it is never replaced with zero-cost certainty. Rate-limit state counts `MODEL_RATE_LIMIT` records in
the published window. Token and cost alerts report `unknown` when their aggregate is incomplete.

The single-instance `operational` configuration domain has a closed `values` schema containing
`currency`, one or more unique `model_cost_rates`, `rate_limit_window_seconds`,
`token_alert_threshold`, `cost_alert_threshold_microunits`, and `rate_limit_alert_count`. Each model
rate names `model_identifier`, `input_microunits_per_million_tokens`, and
`output_microunits_per_million_tokens`. Invalid or incomplete values return `422
OPERATIONAL_CONFIGURATION_INVALID`. The metrics projection resolves only the active published
configuration selected by the runtime boundary; absent or invalid configuration remains explicit.

Evaluation records use opaque `eval_` identifiers and retain the model, knowledge, rule,
configuration, dataset, fixture, and source versions used for one evaluation run. They contain
bounded scenario outcomes and numeric metrics, but never store prompts, claimant messages, provider
payloads, credentials, or unrestricted personal data. The evaluation API is append-only: a new
run creates a new record, and an idempotency replay returns the original record.

Knowledge administration uses opaque `knw_` identifiers for immutable source versions. The
metadata contract requires source identity, insurer/product applicability, jurisdiction,
document type, authority, visibility, effective period, source URI/key, and a SHA-256 checksum.
Optional Markdown content is written to the configured object-store adapter; it is never returned
by the metadata API. The workflow records draft, indexed, failed, awaiting-approval, published,
withdrawn, and superseded states. Indexing and retrieval checks create bounded operation records,
and retrieval responses preserve document/version/section/checksum citations. Claim State,
claim-history, customer policy records, and staff decisions are rejected as ordinary RAG sources.

Agent-rule administration exposes four independent configuration domains: `agent_instruction`,
`agent_tool_policy`, `agent_rule`, and `feature`. They reuse the configuration repository's
revision, validation, approval, publication, rollback, supersession, withdrawal, idempotency,
and audit semantics. Instruction, tool-permission, and controlled-rule changes are forced to the
high-impact path; feature settings may use normal impact only when they do not weaken an existing
safety, access, authority, or side-effect boundary. Runtime still consumes only a complete
published Release Set and deterministic action/authority checks remain outside the configuration
record.

Each component accepts one closed `values` schema. Unknown fields, values from another component,
unknown Registry entries, duplicate allow-list entries, and incomplete values return `422
AGENT_CONFIGURATION_INVALID`.

| Component path | Configuration domain | Required `values` fields |
| --- | --- | --- |
| `instructions` | `agent_instruction` | `prompt_version`, `purpose` (`claimant_agent`), and `system_prompt` |
| `tool_permissions` | `agent_tool_policy` | `policy_version`, `allowed_action_codes`, and `allowed_tool_names` |
| `controlled_rules` | `agent_rule` | `rules_version`, `disabled_rule_ids`, and `observation_rule_ids` |
| `features` | `feature` | `feature_version`, `model_assisted_turns`, and `knowledge_retrieval` |

The tool policy can only restrict server-registered actions and tools. It must retain
`conversation.state_limitation`, `human.create_handoff`, `runtime.fail_safe`,
`runtime.interrupt_urgent`, and `handoff_store.create`. Controlled rules can disable or observe
only registered non-protected branch rules; claim-family, urgent, professional-review, and human-
support rules cannot be disabled or reduced to observation. A Release Set that omits any of the
four Agent domains, selects invalid values, or selects an instruction whose `prompt_version` does
not match the selected model fails before the turn with `503
AGENT_RUNTIME_CONFIGURATION_UNAVAILABLE`. A proposal outside the selected action or tool
allow-list fails before Claim State mutation with `503 AGENT_ACTION_NOT_PERMITTED` or `503
AGENT_TOOL_NOT_PERMITTED`.

Configuration records contain an opaque `configuration_id`, monotonically increasing `revision`,
`domain`, `configuration_key`, `impact`, lifecycle `state`, non-secret `values`, protected `secret_references`,
`author`, `reason`, optional `validation_evidence`, `effective_time`, `previous_version`, and
`rollback_target`. `configuration_key` is `default` for single-instance domains and equals
`service_id` for Integration records. Publication and rollback replace only the active record with
the same `(domain, configuration_key)`. Secret values are rejected in `values` and are never
returned.

In the normal runtime profile, Control Plane configuration and Release Set records are persisted
through the configured `NORTHWIND_CONTROL_PLANE_DB_PATH` repository. Developer/test mode may use
the in-memory repository explicitly for isolated fixtures; this does not change the API contract
or permit runtime fallback to an unpublished record.

Account administration uses the existing identity repositories and their configured database
boundaries. Customer creation accepts `email`, `initial_password`, `display_name`, and optional
`phone`; staff creation accepts `email`, `initial_password`, `display_name`, and one or more
registered `roles`. Create responses return the safe account resource and never return password
hashes or credentials. Account projections include `revision` and `updated_at`; PATCH requests use
the projected revision in `If-Match` and return `409 REVISION_CONFLICT` without changing the
account when stale. Deactivating a customer or staff account prevents new authentication while
preserving existing sessions until normal expiry or explicit revocation.

Session list routes return only opaque `ias_` session IDs, state, revision, creation, expiry,
revocation and update timestamps, plus server-projected actions. They never return bearer values
or token hashes. Revocation is a confirmation-required, revision-checked, idempotent operation;
an already expired or revoked session does not become active again. Every accepted account create,
update, and session revocation appends an administration-only audit event. These routes do not
assign Claim ownership, alter Workbench authority, or write Claim State.

Access-policy administration stores role, actor type, scopes, visibility classes, and an optional
protected credential reference as versioned `access` configuration records. A published policy can
restrict the static scopes of matching authenticated actor types; it cannot grant authority beyond
the identity/session boundary or assign roles dynamically. The route exposes only non-secret
projections and reuses configuration revision, validation, approval, publication, withdrawal,
rollback, and audit semantics; it never edits Claim State or grants a browser direct access to a
credential. The cross-resource audit search is an administration-only projection over the same
append-only audit repository and supports bounded filters without returning raw prompts, provider
payloads, secrets, or unrestricted claimant content.

Integration health routes return bounded status, source, implementation, latency, failure code,
and timestamp only. They never expose credentials, provider payloads, or Claim-level external
task records; health checks are operational evidence, not Claim State. A selected Integration's
`health_check_timeout_seconds` bounds its connection-status check. Timeout returns an unavailable
projection with `INTEGRATION_HEALTH_TIMEOUT` and does not invoke a provider business action.

An `integration` configuration's values are provider-neutral and must contain `service_id`,
`capability`, `source` (`fixture` or `configured_service`), `enabled`, and an optional bounded
`health_check_timeout_seconds`. The service ID must be one of the integrations assembled by the
runtime and its capability must match the registered capability; provider-specific payloads,
credentials, and claim-level task data are not valid values. Multiple services can remain
published concurrently because each service has its own Integration publication key.
When an active Release Set exists, internal policy, history, knowledge, evidence-processing,
claim-creation, and assessor routes invoke only their selected, enabled Integration configuration.
An omitted service returns `503 RELEASE_SET_INTEGRATION_NOT_SELECTED`; a disabled service returns
`503 INTEGRATION_DISABLED`; a selected source that contradicts the assembled adapter returns `503
INTEGRATION_CONFIGURATION_MISMATCH`. Handoff notification uses the same guard, but a disabled or
unselected dispatcher preserves the durable handoff and reports the existing local-queue fallback.

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

High-impact publication requires an immutable approval decision recorded for the exact validated
revision by an administrator other than the configuration author. The approval endpoint records
the reviewer, decision, reason, revision, and timestamp without editing configuration values.
An approved decision keeps the revision in `awaiting_approval` until the separate publish request;
a rejected decision records the review and creates the next draft revision with validation evidence
cleared. Reusing an approval identity for the same revision is rejected, and approval records are
never rewritten or returned with secret values.

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
contract. The current executable prompt identifier is `northwind-fnol-claimant-v5`. A
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

Release Sets provide the cross-domain publication boundary. A release set contains immutable
domain-keyed configuration references, service-keyed Integration references, product-keyed
knowledge references, an environment, and a runtime profile. Each reference carries the selected
record ID and revision. Its lifecycle is `draft`, `validation`, `published`,
`superseded`, or `withdrawn`. Validation fails when a referenced configuration or knowledge
version is missing, has the wrong domain, service or product key, or is not itself `published`; a failed
validation does not change any configuration, knowledge, or release-set state. Publication makes
one complete release set active for the `(environment, runtime_profile)` pair and supersedes the
previous active set atomically. Rollback creates a new published release set that references the
selected prior set and preserves both histories. Release-set writes use `If-Match` and
`Idempotency-Key`, and every accepted or rejected transition records an append-only audit event.

`GET /internal/v1/admin/runtime-snapshots` returns the active release set, its referenced
configuration records, service-keyed Integration records, and selected published knowledge
versions as one runtime snapshot. It
fails with `404 ACTIVE_RELEASE_SET_NOT_FOUND` when no published set exists, with
`409 RELEASE_SET_CONFIGURATION_UNAVAILABLE` when a published set cannot resolve one of its
referenced immutable configuration versions, with `422 RELEASE_SET_INTEGRATION_NOT_FOUND` or `422
RELEASE_SET_INTEGRATION_NOT_PUBLISHED` when a selected Integration revision cannot be resolved,
and with `422 RELEASE_SET_KNOWLEDGE_NOT_FOUND` or
`422 RELEASE_SET_KNOWLEDGE_NOT_PUBLISHED` when a selected knowledge version cannot be resolved.
Runtime consumers must not combine fields
from separate release sets or silently replace a missing selected Integration or knowledge
version with another published version.

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

## Staff Identity API

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/staff/auth/sessions` | Verify staff credentials and create an opaque session |
| `GET` | `/staff/auth/session` | Read the current authenticated staff session |
| `DELETE` | `/staff/auth/session` | Revoke the current staff session |
| `GET` | `/staff/me` | Read the authenticated staff member's minimal Workbench profile |

Only `POST /api/v1/staff/auth/sessions` is public. It accepts `email` and `password`, and returns
`staff_id`, `access_token`, `token_type`, `expires_at`, and `development_identity`. It never accepts
a role, scope, Claim assignment, or staff identifier from the client. The other routes require the
issued staff bearer token and reject claimant credentials. `GET /staff/me` returns the staff ID,
display name, email, roles, and development-identity marker; the server derives Workbench scopes
from the authenticated staff boundary rather than trusting the returned profile in later requests.

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
It is deprecated for model-backed Runtime turns: a model response containing one of these
values is rejected with `LEGACY_AGENT_ACTION_DEPRECATED` and is never mapped into the target
namespaces or a controlled fallback. Historical records remain readable for migration only.
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
  "evidence": "pending",
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
| `evidence` | `not_started`, `received`, `unofficial`, `invalid`, `pending`, `unavailable`, `in_conflict` | ... |
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
| `incident_type` | string | No | Compatibility projection of the registered product family; may be unknown at creation. Branch evaluation reconciles it with the source-aware `claim.product_family` form field. The independent `incident.type` field records the event subtype. |
| `claim_state` | `ClaimState` | Yes | Canonical internal multi-dimensional state |
| `form` | field map | Yes | Registered field code to `StructuredFormField`; initially empty |
| `contents_items` | object array | Yes | Optional source-aware `ContentsItem` records; empty unless the Claim is a contents path |
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
| `question_budget` | integer | Yes | Maximum Agent question turns retained across resumed sessions; defaults to 9 |
| `question_turn_count` | integer | Yes | Accepted Agent turns that asked for a registered fact |
| `requested_fact_count` | integer | Yes | Total registered facts requested by recorded Agent questions |
| `repeated_question_count` | integer | Yes | Questions whose complete registered fact set had already been requested |
| `post_session_follow_up_required` | boolean | Yes | True when the bounded question budget is exhausted before the current requirements are satisfied |
| `question_history` | object array | Staff only | Stable question identity, trigger message, registered field codes, purpose, repeat marker, and time |
| `started_at` | timestamp | Yes | Session creation time |
| `last_active_at` | timestamp | Yes | Last accepted claimant or agent message time |
| `closed_at` | timestamp | No | Present only when closed |

Complete messages remain in durable storage. `summary`, `unresolved_questions`, question counters,
and selected recent message references form a bounded resume package; they do not replace the
formal claim record. Claimant session responses expose the counters and remaining budget but omit
the internal `question_history`. The authorised Workbench session projection includes the history
for effort and repetition review. Starting a new session for the same Claim carries the counters
and history forward so a restart cannot reset the claimant-effort boundary.

#### Session Lifecycle

A session has one of three states:

- `active`: currently accepting claimant messages;
- `paused`: temporarily inactive while resumable context is retained;
- `closed`: the interaction has ended and the session no longer accepts new messages.

Session lifecycle transitions are server-controlled.

A session MAY move from `active` to `paused` after claimant inactivity or when the current interaction is interrupted.

`POST /api/v1/claims/{claim_id}/sessions/{session_id}/pause` is the explicit P17.1 interruption boundary. It requires the current Claim revision through `If-Match` plus an `Idempotency-Key`, atomically marks the current session `paused`, aligns that Session's recovery snapshot to the accepted Claim revision, clears the Claim's active-session pointer, stores bounded recovery context, and creates exactly one open Claim-scoped recovery Follow-up for the `resume_incomplete_claim` purpose. The accepted Claim revision is part of the idempotency fingerprint, so reusing the same key with a different `If-Match` value returns `409 IDEMPOTENCY_CONFLICT`. It does not create a second Claim State, send a follow-up, make an abandonment decision, or apply a retention transition.

The recovery Follow-up persists purpose, source references, responsible party, channel, due time, status, attempt count, and a contact-permission condition. An authenticated claimant may receive a `pending` in-app recovery Follow-up; that record does not authorise email, SMS, or phone contact. An anonymous browser claimant has no durable authorised contact channel in P17.1, so the record is persisted as `blocked` with `contact_permission=not_authorised`, no channel, and no due time. P17.2 owns any later scheduling, delivery, attempt, or escalation policy.

After that checkpoint, claimant Claim detail and Claim list projections may include `incomplete_context` containing the interruption time, last meaningful activity, bounded resume point, and the claimant-safe open Follow-up state. Pause is accepted only when the authoritative Claim is not `created` and `customer_next_step.can_resume=true`; terminal or explicitly non-resumable Claims return `409 INVALID_STATE_TRANSITION`. Claimant and Workbench projections use the same incomplete predicate: an eligible resumable non-terminal Claim, no authoritative active Session, a relevant paused recovery checkpoint, and an open recovery Follow-up. This applies to every resumable non-terminal workflow state, not only `collecting`. The persisted checkpoint also records the exact durable source reference for the latest qualifying claimant message or accepted claimant business action.

When a claimant resumes an existing working claim, the server starts a new interaction session using the current Claim State and bounded resume context and atomically marks the open recovery Follow-up `resolved`. A later interruption of that resumed Session may create the next recovery Follow-up for the same purpose because only one open Claim+purpose record is allowed at a time.

Only one active claimant session per claim is permitted.

Messages MUST NOT be accepted for a closed or paused session.

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
| `status` | enum | `proposed`, `confirmed`, `disputed`, `missing`, `pending_generation`, `unavailable`, `superseded` |
| `needed_for` | enum | `current_action`, `later_action` |
| `confidence` | number | Optional `0.0` to `1.0`; never a substitute for confirmation |
| `resolution_state` | enum | `resolved`, `needs_confirmation`, `clarification_required`, `unavailable`, or `superseded` |
| `precision` | enum | `exact`, `approximate`, `range`, `partial`, or `unknown`; temporal values preserve claimant precision |
| `current_assertion_id` | string/null | Current assertion selected from immutable assertion history |
| `assertions` | object array | Source-linked assertion history; repetition, refinement, correction, conflict, and irrelevant input remain distinguishable |
| `updated_at` | timestamp | Server generated |
| `updated_by` | actor reference | Server derived from the authenticated actor |

Initial common field codes:

| Field code | Type | Purpose |
|---|---|---|
| `policy.policy_number` | string | Locate the relevant policy |
| `claimant.client_number` | string | Staff-only Northwind client reference supplied by identity |
| `claimant.role` | enum | Policyholder, authorised representative, or other reporter |
| `claimant.contact_preference` | enum | `in_app`, `email`, `phone`, or `sms` when supported |
| `claim.product_family` | enum | `motor`, `home`, or `contents`; source-aware family field projected through top-level `incident_type` for compatibility |
| `incident.type` | enum | `collision`, `fire`, `water`, `theft`, `weather`, or `other`; never the product family |
| `incident.occurred_at` | timestamp | When the incident occurred |
| `incident.location` | object | Structured place plus claimant wording |
| `incident.description` | string | Claimant-confirmed factual account |
| `incident.injury_or_danger` | boolean | Explicit safety routing input; not a diagnosis |
| `incident.cause` | string | Cause classification used for coverage assessment (e.g. sudden vs gradual) |
| `loss.description` | string | Damage, loss, or affected property |
| `parties.other_parties` | boolean | Whether another person or organisation is involved; participant details use separate records |
| `authorities.police_report_reference` | string | Reference if already issued |
| `authorities.emergency_services_notified` | boolean | Whether emergency services were contacted |
| `vehicle.registration` | string | Motor-specific vehicle reference |
| `vehicle.damage_description` | string | Motor-specific damage account |
| `vehicle.drivable` | boolean | Motor-specific immediate status |
| `property.address` | object | Home or contents risk location |
| `property.affected_areas` | array | Home-specific affected areas |
| `property.ongoing_risk` | enum | `none`, `active_leak`, `fire`, `collapse`, `exposure`, or `other`; current home safety condition |
| `property.habitable` | boolean | Whether the home is currently safe to occupy; does not replace professional safety advice |

### Contents items

`contents_items` is an optional list on Claim projections. Each item is an independent,
source-aware record and is not flattened into the Dynamic Form. Evidence associations remain
separate Evidence records until the item-association contract is implemented.

Claimant projections use a role-safe `ClaimantContentsItem` view: `confidence` and `updated_by`
are internal assessment metadata and are omitted. `source_refs` is limited to public message and
evidence identifiers (`msg_*` and `evd_*`); retrieval, staff, policy, inference, and other
internal references are omitted. Workbench projections retain the full authorised record.

| Property | Type | Rule |
|---|---|---|
| `item_id` | string | Stable identifier unique within a Claim |
| `description` | string | Claimant- or staff-sourced item description |
| `category` | string | Opaque display category; category vocabulary/bounding is a follow-up registry decision |
| `quantity` | integer | At least 1 |
| `loss_type` | enum | `damaged`, `lost`, `stolen`, or `destroyed` |
| `ownership` | enum | `owned`, `leased`, `borrowed`, `gifted`, or `other` |
| `estimated_value` | object/null | Non-negative `amount` plus ISO-4217-style three-letter `currency`; not a settlement value |
| `source` / `source_refs` | enum / string array | Same provenance boundary as structured form fields |
| `status` | enum | Existing `FormStatus`; `proposed` is used for inference and `disputed` for conflicts |
| `needed_for` | enum | `current_action` or `later_action` |
| `confidence` | number/null | Optional 0.0–1.0 confidence; never confirmation |
| `resolution_state` | enum | Same resolution states as structured form fields |
| `current_assertion_id` | string/null | Current item assertion selected from immutable item history |
| `assertions` | object array | Immutable item assertion history with relation, status, and source references |
| `updated_at` / `updated_by` | timestamp / actor reference | Server-maintained provenance |

The backend MUST maintain a versioned field registry with validation and display metadata. New product fields require a registry change; clients MUST NOT invent arbitrary field codes.

Every claimant Dynamic Form projection includes deterministic `requirements`: `satisfied`,
`missing_required_now`, `pending_later`, `next_required_item`, `ready`,
`current_action_total`, and `current_action_satisfied`. The backend recalculates this projection
from authoritative Claim State, the selected registered branch, and the current action. Clients
must not calculate readiness or choose required fields locally.

Each field assertion records a stable identifier, the reported wording when available, normalized
value, source references, relation, status, precision, optional reason code, and creation time. A
later claimant statement is resolved against existing assertions rather than silently discarded.

### Evidence

```json
{
  "evidence_id": "evd_01J4Y7V5QJ",
  "claim_id": "clm_01J4Y7Q2AW",
  "kind": "police_report",
  "status": "pending",
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
| `status` | `missing`, `pending`, `received`, `unofficial`, `invalid`, `unavailable`, `superseded`, `expired` |
| `file_status` | `not_available`, `awaiting_upload`, `uploading`, `uploaded`, `processing`, `ready`, `failed` |
| `source` | `claimant`, `staff`, `external_system` |
| `related_fields` | Registered form field codes supported or challenged by the item |
| `needed_for` | One or more business actions; later evidence MUST NOT block an unrelated safe current action |
| `references` | Typed statements about a second record or claim fact. **Staff-visible only** |

`status` carries the condition of the material and `file_status` the upload and
processing lifecycle. They answer different questions and MUST NOT be read as
alternatives to each other: `pending` with `not_available` is a document that does not
exist yet, and `pending` with `awaiting_upload` is a file on its way in.

Three conditions are statements about a *second* thing and therefore cannot be carried by
`status` alone. Each is recorded as an `EvidenceReference`:

| Field | Allowed values or rule |
|---|---|
| `relation` | `conflicts_with`, `superseded_by`, `unavailability_established_by` |
| `evidence_id` | The other evidence record; required for every relation except a conflict against a claim fact |
| `field_code` | The claim field contradicted; permitted only with `conflicts_with` |
| `state` | `unresolved` or `resolved`; exactly one of `evidence_id` and `field_code` is set |
| `reason` | Why the relation exists, in terms a staff member can act on |
| `raised_at` | When it was recorded |
| `resolved_at` | Present if and only if `state` is `resolved`, and never before `raised_at` |

A material can be `received`, `ready`, and contested at the same time, so conflict is a
reference rather than a status. A record may carry an unresolved `conflicts_with` only
when it is `received` with a `ready` file: a conflict is established by comparing settled
evidence, and material still arriving, or that never arrived, cannot be the thing another
record disagrees with.

`references` does not appear in the claimant projection. A claimant is told a check is in
progress; which side is doubted, and why, is staff-only.

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
        "status": "pending",
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
provenance.

`policy_citation_refs` contains opaque `retrieval_id` values for persisted
`PolicyRetrievalRecord` records that were authoritative and relevant at transfer time.
`history_evidence_refs` uses the same rule for persisted
`ClaimHistoryRetrievalRecord` records. These fields do not copy human-readable policy
wording or mutable provider output into the Handoff packet.

`source_refs` may additionally retain the bounded transfer-time provenance required to
reconstruct why the handoff was created: authoritative message or Evidence references,
relevant active Review Signal identities and their source references, and immutable Staff
Tag Registry coordinates in the form
`tag_registry:<registry_id>:<registry_version>:<tag_code>`. The packet does not copy the
complete mutable Workbench tag or signal projection.

An empty policy or history reference list is not evidence that retrieval succeeded. When
a source was not relevant, the surrounding handoff context must make that interpretation
clear. When retrieval failed or the source was unavailable, the handoff reason,
`reason_codes`, requested action, or promised next step must preserve that limitation
explicitly. An unexplained empty list is insufficient when a required source was
unavailable.

Current responsibility remains authoritative in live Claim and Workbench state. The
transfer packet records the requested action and transfer-time responsibility context but
does not create a second mutable ownership field. The receiving Workbench therefore
presents the immutable handoff-time context separately from current responsibility and
current signal state.

Claimant routes use this customer-safe handoff projection:

```json
{
  "handoff_id": "hnd_01J4Y7XG2C",
  "status": "queued",
  "support_need": "human_requested",
  "summary": "A Northwind support request has been queued with the details already provided.",
  "created_at": "2026-08-10T03:48:00Z"
}
```

This projection appears in support-request responses, Agent-turn responses, and claim-read
responses when a claimant-created handoff is active. It excludes the internal `priority`, queue,
routing reasons, assignment, and complete packet. Claimant evidence projections continue to
exclude `internal_only` items.

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
| `POST` | `/claims/{claim_id}/sessions/{session_id}/pause` | Persist an interruption checkpoint and initial follow-up task; requires `If-Match` and `Idempotency-Key` |
| `GET` | `/claims/{claim_id}/sessions/{session_id}` | Read resumable session state |
| `POST` | `/claims/{claim_id}/sessions/{session_id}/messages` | Submit a message and execute one agent turn |
| `GET` | `/claims/{claim_id}/sessions/{session_id}/messages` | Read paginated claimant-visible messages |
| `GET` | `/claims/{claim_id}/sessions/{session_id}/events` | Stream claimant-safe Claim and conversation change notifications |
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
| `GET` | `/claims/capabilities` | Read the published claimant model profiles and default profile |

### `GET /api/v1/claims/capabilities`

Returns the published claimant model catalog without endpoint credentials. The response includes
`default_model_profile_id` (currently `qwen-local` when that profile is published) and each
profile's stable ID, provider model label, protocol, structured-output capability, and tool-call
capability. The frontend uses the default only when creating a Session; an existing Session's
profile cannot be changed by a message request.

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
    "model_profile_id": "qwen-local",
    "started_at": "2026-08-10T03:40:00Z",
    "last_active_at": "2026-08-10T03:40:00Z"
  }
}
```

`model_profile_id` may be supplied in the create request. The selected profile must be published,
configured for claimant use, and declare both structured output and tool calling; otherwise the
server returns `MODEL_PROFILE_UNAVAILABLE`. A resumed Session retains its original profile.

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
  "active_session_id": "ses_01J4Y7RPN8",
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
  "dynamic_form": null,
  "customer_next_step": {},
  "handoff": null,
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

`dynamic_form` is the claimant-safe Dynamic Form projection applicable to the returned Claim
snapshot. It is built from the newest applied branch evaluation valid at or before the current
Claim revision, and its `claim_revision` matches the returned Claim revision. An unrelated Claim
update can therefore carry the last applicable field selection forward without asking the browser
to infer whether it is still valid. The field is `null` only when the Claim has no applied branch
evaluation. Inactive and system-owned fields remain outside this projection.

`handoff` is `null` when no claimant-created handoff is active. Otherwise it contains the
claimant-safe handoff projection defined above and never contains internal `priority` or routing
fields.

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
  "model_profile_id": "qwen-local",
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

The optional `model_profile_id` in a start/resume request is accepted only when it agrees with
the existing Session binding. The server never silently replaces an unavailable or withdrawn
profile with another model.

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

On the target namespaced Runtime path the model must first call `claim.read`. The Runtime executes
the read against the authenticated Claim, sends the assistant tool call and result back to the
same model, and accepts only the final `conversation.answer` plus `runtime.continue` response.
The resulting response has `decision: null`, preserves the current Claim revision, and records
the internal two-invocation trace. The deprecated eight-action model contract is rejected with
`LEGACY_AGENT_ACTION_DEPRECATED`; it is never mapped to a namespaced action or controlled
fallback.

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

`dynamic_form` is a claimant-safe projection of the applied branch evaluation after the turn. It
exposes only active, claimant-visible fields; inactive and system-owned fields remain outside this
response. Selection state (`required_now`, `candidate_now`, or `pending_later` in this projection)
is separate from the stored value state. The projection is `null` when the Claim has no applied
branch evaluation.

### `GET /api/v1/claims/{claim_id}/sessions/{session_id}/messages`

Returns claimant-visible messages ordered newest-last by default. Supported query: `before`, `after`, `limit`, and `cursor`. Staff-only notes and hidden system messages are excluded.

### `GET /api/v1/claims/{claim_id}/sessions/{session_id}/events`

Opens a `text/event-stream` connection for the authenticated claimant or the browser's current
anonymous claimant session. The Claim and session ownership checks are identical to the ordinary
claimant read boundary. `after_revision` is the last Claim revision already applied by the client;
the server rejects a cursor newer than the current Claim with `409 INVALID_EVENT_CURSOR` and the
current revision.

When shared Claim State advances, the stream emits `claim.updated`:

```text
id: 4
event: claim.updated
data: {"event_id":"4","claim_id":"clm_01J4Y7Q2AW","session_id":"ses_01J4Y7RPN8","claim_revision":4,"resources":["claim","messages"],"emitted_at":"2026-09-03T05:10:00Z"}
```

This event is a resource hint, not a second Claim projection. It contains no messages, handoff
packet, internal signals, staff identity, model metadata, or hidden reasoning. After receiving it,
the claimant client reloads `GET /claims/{claim_id}` and the active session's message list through
their existing visibility-filtered endpoints. Reconnection sends the last applied Claim revision,
so changes missed while disconnected are recovered. The server sends comment-only keep-alives;
clients ignore them and reconnect with bounded backoff if the transport closes.

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
claimant-owned `pending` evidence item needed for a `later_action`. The created claim therefore
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
    "failure_code": null,
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
four leave the consented Working Claim revision unchanged and do not report assignment.
Automatic retry counts remain unapproved; the claimant client offers only an explicit retry for
retryable failures.

A permitted retry continues the same operation, task, and request record. The operation identity
is derived from the claim, the active claimant permission, and the requested action, so it does
not depend on the client presenting the original `Idempotency-Key`: a retry that presents a new
key is the same operation, not a second one, and a claimant who reloads the page can still retry.
A retry that changed the request is refused, because the operation holds the first attempt's
request fingerprint and it is compared before anything else.

An attempt the adapter reports as having reached the assessor before it failed is not a failure
the claimant may retry. Whether a request was submitted is reported by the adapter, never inferred
from the failure code: the same `timeout` can describe an attempt that never left and one whose
acknowledgement was lost. A submitted timeout, or any partial response, records the task and its
routing operation as `unknown_outcome`, and the response is `409 INVALID_STATE_TRANSITION` with
`retryable: false` and `details[].reason` `unknown_outcome`. While that task stands, every further
request on the claim is refused the same way before any operation is prepared and before the
assessor is contacted, whatever idempotency key it carries; no second task, operation, or request
is created. The refusal is lifted by establishing what happened to the original request, not by
repeating it.

A replay of an accepted request succeeds only when its operational task ended accepted and the owed
assessment material resolves to that task. Where an interrupted attempt left that state incomplete in a
way the replay can finish — the task still prepared, or the owed material or its link missing — the
replay completes it before responding. Where the task is missing or recorded as failed, the replay
returns `409 IDEMPOTENCY_CONFLICT` with `retryable: false`, saves nothing to the claim, and does not
report assignment.

After a failed attempt the claimant state does not return to `ready_to_request`.
`external_service_action.status` becomes `retryable_failure` for a timeout or unavailable
response that did not reach the assessor, `terminal_failure` for an access-denied or malformed
one, and `awaiting_reconciliation` for an attempt that may already have reached the assessor, and
`failure_code` carries the provider-neutral reason. `can_request` stays true only for a retryable
failure, because a terminal failure requires Northwind to review the request before another
attempt, and an unresolved outcome must be established before one is sent.
The state is derived from the recorded external task rather than stored on the claim: a failed
attempt leaves every claim field unchanged, so the claimant still sees what happened on a
later read without the failure having altered the claim.

Once the assessor has returned a result, `customer_next_step` reports that it arrived and that
Northwind is reviewing it, with `responsible_party` `claims_professional` and no `expected_by`: the
claim is no longer waiting on the external party, and the time the request was expected by has
already been met. The routing status is unchanged, because the assessor assignment still stands.
The report itself is not projected to the claimant. It is `simulation_only` and its verification
state is `review_required` by construction, so the claimant is told that an answer exists and is
being checked, never what it says; the record stays internal to the staff Evidence surface.

`customer_next_step` is corrected against that state for the two cases in which the action is
withdrawn. It is a stored field written when permission is recorded, and a failed attempt changes
no claim field, so on its own it keeps saying that Northwind can now send the request. Where
`external_service_action.status` is `terminal_failure` or `awaiting_reconciliation`, the projected
next step instead reports that Northwind is reviewing or checking the request, with
`responsible_party` `claims_professional` and no required items. A `retryable_failure` keeps the
stored next step, which agrees with `can_request`. The correction is derived for the read; the
stored field is not rewritten, so a failed attempt still changes nothing on the claim.

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
compare-and-set, the first request returns the bounded revision conflict. The same claimant's
request for the same claim, permission, and action then reconciles that accepted result without
another provider call, whichever idempotency key it presents, because that is the operation
identity. A request that is genuinely a different one remains a revision or idempotency conflict:
a changed request is refused against the operation's recorded fingerprint, and a request under a
different permission or action is a different operation.

### `GET /api/v1/claims/{claim_id}/evidence`

Returns claimant-visible evidence metadata, processing state, purpose, upload result, and plain-language next step. It never returns internal-only extraction notes or other claims' evidence.

The response contains `claim_id`, current `revision`, `items`, and
`customer_next_step`. Evidence items deliberately omit storage keys, upload
checksums, extraction state, and internal provenance.

The `status_url` returned by upload completion is this Claim Evidence collection
(`GET /api/v1/claims/{claim_id}/evidence`). It is the authoritative polling
projection for the same Evidence record: clients reread it after `202` and do
not manufacture `processing`, `ready`, `failed`, or retry state locally.

### `POST /api/v1/claims/{claim_id}/evidence`

Registers evidence when no file is currently available.

Request:

```json
{
  "kind": "police_report",
  "status": "pending",
  "related_fields": ["authorities.police_report_reference"],
  "needed_for": ["later_action"],
  "claimant_note": "Police said the report will be available next week."
}
```

This request requires `Idempotency-Key` and `If-Match`. Response `201` returns
the evidence resource, new claim revision, and customer next step. A
`pending` item MUST NOT block an action that does not require it. Evidence with a
received file must use the upload flow rather than being registered directly as
`received`, and a condition that describes content that exists — `invalid`,
`superseded`, `expired` — cannot be registered at all, because registration records
material that has not arrived.

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

An anonymous browser session may continue its conversation and read its own
Claim, but it cannot create a durable Evidence record or receive an upload
capability. File selection is a temporary browser action until the claimant
signs in; the server returns `401 AUTHENTICATION_REQUIRED` before checking the
Claim or Evidence identifier. After sign-in, the existing anonymous Claim is
promoted through the login/resume boundary and the claimant starts the upload
with a new authenticated intent. An abandoned anonymous file selection leaves
no Evidence record or protected object to clean up.

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

`support_need` is `human_requested`, `accessibility_required`, `distress`, or `urgent`. Response
`201` returns the customer-safe handoff projection, next step, and delivery state. The handoff
contains `handoff_id`, `status`, `support_need`, `summary`, and `created_at`; it does not contain
the internal routing `priority`.

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
| `GET` | `/workbench/staff/online` | Read a paginated page of currently claimable online staff |
| `GET` | `/workbench/staff/presence` | Read the authenticated staff member's presence lease |
| `PATCH` | `/workbench/staff/presence` | Heartbeat or change the authenticated staff member's presence |
| `GET` | `/workbench/claims/filter-metadata` | Read canonical staff queue filter options |
| `GET` | `/workbench/claims/{claim_id}` | Read full authorised claim detail |
| `GET` | `/workbench/claims/{claim_id}/evidence/{evidence_id}/content` | View completed evidence content as authorised staff |
| `GET` | `/workbench/claims/{claim_id}/evidence/{evidence_id}/content-data` | Read browser-safe evidence content as authorised staff |
| `POST` | `/workbench/claims/{claim_id}/assignments` | Assign or reassign ownership |
| `POST` | `/workbench/claims/{claim_id}/cowork-requests` | Request or invite cowork access through a projected ownership action |
| `POST` | `/workbench/claims/{claim_id}/transfer-requests` | Request a primary-owner transfer through a projected ownership action |
| `PATCH` | `/workbench/claims/{claim_id}/collaboration-requests/{request_id}` | Accept or reject a projected cowork or transfer request |
| `POST` | `/workbench/claims/{claim_id}/requeue` | Release primary ownership when the projected action is executable |
| `POST` | `/workbench/claims/{claim_id}/staff-actions` | Create a staff action |
| `PATCH` | `/workbench/claims/{claim_id}/staff-actions/{action_id}` | Progress or complete a staff action |
| `POST` | `/workbench/claims/{claim_id}/signals/{signal_id}/decisions` | Decide an internal signal |
| `POST` | `/workbench/claims/{claim_id}/handoffs/{handoff_id}/accept` | Accept a handoff |
| `POST` | `/workbench/claims/{claim_id}/messages` | Send a persisted claimant-visible staff message |
| `POST` | `/workbench/claims/{claim_id}/handoffs/{handoff_id}/resolve` | Resolve a handoff and write back state |
| `POST` | `/workbench/claims/{claim_id}/updates` | Send a claimant-visible update |
| `GET` | `/workbench/claims/{claim_id}/events` | Read the claim audit timeline |
| `POST` | `/workbench/agent/sessions` | Create a private persistent Staff Agent session |
| `GET` | `/workbench/agent/sessions` | List the authenticated staff member's Staff Agent sessions |
| `GET` | `/workbench/agent/capabilities` | Read published Staff Agent model profiles |
| `GET` | `/workbench/agent/sessions/{session_id}/messages` | Read one owned Staff Agent session |
| `POST` | `/workbench/agent/sessions/{session_id}/messages` | Ask the Staff Agent with an explicit Claim scope |
| `POST` | `/workbench/agent/sessions/{session_id}/messages/{message_id}/drafts/{draft_id}/execute` | Confirm one saved Staff Agent draft and run its registered Workbench action |
| `GET` | `/workbench/conversations` | List accessible Claim conversations and owned Staff Agent sessions |
| `GET` | `/operations/metrics` | Read aggregate operational metrics |

### Staff Agent sessions

Staff Agent sessions are private to the authenticated staff identity and remain stable across
Workbench pages and browser refreshes. They are not Claim conversation sessions and are never
exposed through claimant routes. `GET /api/v1/workbench/conversations` includes them with
`kind: "staff_agent"` so the staff member can resume them from Claim conversations.

`POST /api/v1/workbench/agent/sessions` accepts an optional `title` and published
`model_profile_id`, and creates a `sas_` session. The selected profile is persisted on that
session; omitting it selects the published default. A message cannot override the session's
profile.
`GET /api/v1/workbench/agent/sessions` lists only sessions owned by the authenticated staff
member. `GET /api/v1/workbench/agent/sessions/{session_id}/messages` returns that session's
ordered `staff` and `assistant` messages; another staff identity receives `404` rather than an
ownership disclosure.

Every `POST /api/v1/workbench/agent/sessions/{session_id}/messages` request must include an
explicit `claim_ids` array. An empty array is a valid general question. The array may contain up
to five unique existing Claim IDs; the service never infers scope from the current page, an open
Claim tab, prior session messages, or the question text.

```json
{
  "client_message_id": "staff-question-01J4YB0J3S",
  "content": "Compare the missing evidence for these two Claims.",
  "claim_ids": ["clm_01J4Y7Q2AW", "clm_01J4Y8P1TZ"]
}
```

The service assembles bounded conversation history, selected Claim projections, operational
records (fields, evidence, policy/history retrievals, review signals, handoffs, staff actions,
customer updates, and external-service tasks), and authorised knowledge retrieval context. It
preserves source and availability limitations while building that context. It invokes the distinct
`staff_assistant` model purpose under the
`staff_internal_fnol` privacy class and prompt `northwind-fnol-staff-assistant-v1`. The response
returns the saved session, the staff message and the assistant message. Each assistant message
records the provider model used for the session profile. Assistant messages may include source
references and drafts of `claimant_message`, `internal_note`, or `external_request` kind. Every
persisted draft receives a stable `draft_id`; an executable draft may additionally carry a
registered Workbench `action_code`, its `target_ref`, and a candidate payload. A draft can name only
a Claim in the request scope.

The Staff Agent still has no mutation authority. A staff member must explicitly confirm a saved
draft through the execution endpoint. That endpoint only adapts into an existing registered
Workbench action route, which owns permission, consent, If-Match revision, idempotency, audit, and
Claim State checks. The response is an authoritative action result, never a model claim that work
was completed. A draft without a registered action, an external-request draft without an available
provider action, missing confirmation, malformed payload, denied action, stale revision, or
unavailable dependency is rejected with the bounded error from the underlying route and leaves
Claim State unchanged. Model unavailability, malformed output, or an out-of-scope draft fails the
complete turn before either message is persisted. When no Staff Agent model profile is configured,
message submission returns `503 DEPENDENCY_UNAVAILABLE`.

When execution succeeds, the underlying Workbench idempotency record stores the originating Staff
Agent `session_id`, assistant `message_id`, and `draft_id` alongside the registered action and
resulting Claim revision. This durable source link is written in the same mutation boundary as the
action result. Reusing the idempotency key with another draft or through a non-Agent route returns
`409 IDEMPOTENCY_CONFLICT`; an execution response alone is not the audit record.

The execution request is deliberately small because the saved draft carries the candidate action:

```json
{
  "confirmed": true,
  "payload": {}
}
```

`payload` may contain staff edits, but it is validated against the registered action before the
existing handler runs. The request requires `Idempotency-Key`; Claim-mutating actions also require
the current `If-Match` Claim revision.

`GET /api/v1/workbench/agent/capabilities` returns the credential-free published model profile
catalog for Staff authentication.

### `GET /api/v1/workbench/claims`

Supported filters:

| Filter | Values |
|---|---|
| `limit` | Page size from 1 to 100; defaults to 25 |
| `cursor` | Opaque cursor returned by the preceding page |
| `view` | `all`, `processing`, `waiting_user`, `waiting_material`, `waiting_third_party`, `completed`, `abandoned`, `closed`, `urgent`, `human_requests`, `incomplete_claims`, `ready_to_progress`, `awaiting_evidence`, `professional_review`, `ready_to_create`, `created_routed` |
| `workflow_state` | Canonical workflow state |
| `priority` | `routine`, `standard`, `high`, `urgent`, `immediate` |
| `assignee_id` | Opaque staff ID or `unassigned` |
| `next_action` | `AgentAction` |
| `tag` | One published staff tag code from the backend Staff Tag Registry |
| `search` | Case-insensitive text, up to 200 characters |
| `updated_before`, `updated_after` | RFC 3339 timestamp |

Filters can be combined and are applied before queue ordering and cursor pagination.
`search` matches only staff-list projection fields: Claim ID, display reference, incident family
and summary, current requested outcome, and projected tag codes and labels. Claimant display name
is not searchable until an authorised staff-safe identity projection populates it. Search does not
inspect unprojected Claim fields or change the backend rank order.

Each item includes claim ID, safe display reference, state dimensions, terminal disposition,
priority, queue, route,
next responsibility, evidence state and counts, open handoff summary, assignee, integration status,
service timing, and update time. It is a projection of shared claim state, not a separately
editable board record.

The response is shaped as
`{ "items": [...], "page": { "next_cursor": null }, "view_counts": { "status": "available", "items": [...], "limitation": null } }`.
A non-null `next_cursor` is passed back through `cursor` to read the next ordered page. Invalid
cursors return `422 VALIDATION_ERROR`. Each item contains the safe Claim, claimant and incident
summaries; lifecycle and workflow state; ownership and priority projections; `work_summary`;
integration status; tags; and creation and update times. It is a projection of shared Claim state,
not a separately editable board record.

`work_summary.queue_key` is exactly one of seven lifecycle-placement views for every listable
Claim. The server applies terminal precedence before active placement:

| Queue | Authoritative mapping |
|---|---|
| `completed` | `terminal_disposition.value=completed` |
| `abandoned` | `terminal_disposition.value=abandoned` |
| `closed` | `terminal_disposition.value=closed` |
| `processing` | Non-terminal `draft_active`, `staff_support`, `professional_review`, `ready_to_create`, or `creating` lifecycle |
| `waiting_user` | `waiting_customer` without claimant material required for the current action |
| `waiting_material` | `waiting_customer` with claimant Evidence missing information that is `required_now` |
| `waiting_third_party` | `waiting_external`; this takes precedence over other waiting reasons |

Active handoffs and professional review therefore remain in `processing`. Operational views are
independent, overlapping projections: the same Claim may appear in `processing` and, for example,
`human_requests` or `professional_review`; a completed Claim may also match `created_routed`.
`all` is the union of the four active queues and excludes all three terminal queues.

`terminal_disposition` is the P17-owned authoritative record embedded in `WorkingClaim`. It is
either null or contains `value`, registered `reason_code`, one or more immutable `source_refs`,
typed `recorded_by`, `recorded_at`, and `recorded_revision`. It is not a second lifecycle enum and
does not rewrite the retained `claim_state`. A successful external Claim creation records
`completed` with reason `CLAIM_CREATED` and references both the authorising decision and created
external Claim in the same Claim revision. `abandoned` and `closed` are never inferred from
`withdrawn`, `expired`, free text, action history, or a missing session. A `created` lifecycle
without its authoritative terminal record, or a terminal record that contradicts the external
Claim result, returns `503 PROJECTION_UNAVAILABLE` rather than falling through to `processing`.

`view_counts.items` contains one entry for every server-published view in metadata order. Counts
are computed from the same authorised Claim set after applying `workflow_state`, `priority`,
`assignee_id`, `next_action`, `tag`, `search`, `updated_before`, and `updated_after`; they ignore
the selected `view`, `cursor`, and `limit`. A count failure does not discard a usable page: the
server returns its rows with `view_counts.status: "unavailable"`, an empty `items` list, and a
non-null `limitation`. Clients must not convert unavailable totals into zero. An unknown or no
longer published `view` returns `422 VALIDATION_ERROR` and is never treated as `all`.

`tags` is a backend projection from authoritative Claim fields and branches, Evidence records,
WorkItems, handoffs, external-operation results, and review Signals. The Workbench client MUST
render this projection and MUST NOT infer tags from summaries, queue names, route names, or free
text. Each tag has this shape:

```json
{
  "tag_instance_id": "clm_01J4Y7Q2AW:impact.vehicle_not_drivable",
  "code": "impact.vehicle_not_drivable",
  "registry_version": "0.3",
  "label": "Vehicle not drivable",
  "description": "Summarises the reported practical impact: Vehicle not drivable.",
  "category": "impact",
  "status": "active",
  "visibility": "staff_only",
  "basis": "reported",
  "source_actor": "claimant",
  "freshness": "current",
  "projection_mode": "deterministic",
  "attention_level": null,
  "source_refs": ["msg_01J4Y7RPN8", "field:vehicle.drivable"],
  "activated_at": "2026-08-10T03:45:00Z",
  "display_weight": 30
}
```

Stable codes are an API concern; staff interfaces display the natural-language `label` and make
the basis, source actor, freshness, status, attention level, activation time, and sources available
through progressive disclosure. Tags classify a Claim for staff
and do not independently determine queue priority. Staff cannot directly edit a tag: a correction,
Signal decision, handoff, Evidence change, WorkItem transition, or authorised business action
changes the source record and the backend recomputes the projection. Claimant routes MUST NOT
include this staff-only projection.

The `tag` filter uses the same backend Registry and filterability rule as `filter-metadata`.
Unknown, draft, deprecated, retired, or non-filterable codes return `400 INVALID_TAG_FILTER`; a
published, filterable code returns only Claims whose computed `tags` contains that code. The
current endpoint accepts one code. Future grouped OR/AND filtering requires an explicit contract
extension.

`urgent` contains Claims whose projected priority is `urgent` or `immediate`. `human_requests`
contains Claims with an active handoff whose support need is `human_requested`.
`incomplete_claims` contains resumable non-terminal Claims with no authoritative active Session,
a relevant durable paused recovery checkpoint, and an open recovery Follow-up. It is an operational
overlay rather than an active lifecycle queue and does not infer a triage status.
Queue results are ordered by the backend priority rank (`immediate`, `urgent`, `high`, `standard`,
`routine`) and then by due time/creation time. The client does not recalculate this order.

### `GET /api/v1/workbench/claims/filter-metadata`

Returns the backend-owned queue filter contract for authenticated staff. The response contains
`views`, `workflow_states`, `priorities`, and all published, filterable `tags`, plus
`tag_registry_version`. Every option contains `value` and `label`; each view also contains its
`overview`, `active`, `terminal`, or `operational` group, and tag options contain `category`. Array order is the
server-owned display order. The Workbench uses these values to validate route state, group and
render controls, and associate authoritative `view_counts` instead of maintaining a second enum or
deriving options or totals from loaded Claim pages.
`priorities` contains every `WorkPriorityLevel` that the queue can project, including `routine`
for Claims whose workflow state is still `collecting`.

### `GET /api/v1/workbench/claims/{claim_id}`

Returns the authorised internal Claim projection assembled from the same repository records used by
claimant routes. The response deliberately contains summaries rather than a database-shaped dump;
large resources are loaded from the dedicated sub-resources below:

```json
{
  "claim_id": "clm_01J4Y7Q2AW",
  "revision": 7,
  "display_reference": "NW-1042",
  "claimant": {"customer_id": "customer-1042"},
  "incident": {"family": "motor", "summary": "Rear-end collision; vehicle remains drivable."},
  "lifecycle_state": "staff_support",
  "terminal_disposition": null,
  "workflow_state": "professional_review",
  "ownership": {"state": "assigned", "current_staff_access": "primary"},
  "priority_projection": {"level": "high", "rank": 120, "due_at": null, "is_overdue": false},
  "work_summary": {"queue_key": "processing", "primary_action_code": "human.accept_handoff", "primary_action_target_ref": "hnd_01J4Y7XG2C", "missing_information": [{"kind": "field", "code": "incident.description", "label": "Incident Description", "status": "disputed", "attention": "required_now", "blocked_action": "confirm", "responsible_party": "claims_professional", "source_refs": ["msg_01J4Y7T1KC"]}], "risk_signals": []},
  "integration_summary": {"external_wait_count": 0},
  "tags": [],
  "claim_state": {},
  "source_summary": {"status": "available", "items": [{"kind": "field", "record_ref": "field:incident.description", "label": "Incident Description", "context": "Incident Description is recorded for the current action.", "source_label": "Claimant statement", "status": "disputed", "source_refs": ["msg_01J4Y7T1KC"], "related_fields": [], "needed_for": ["current_action"], "responsible_party": null, "confidence": 0.96, "updated_at": "2026-08-10T03:42:12Z"}], "limitation": null},
  "allowed_actions": [],
  "section_summaries": {"fields": {}, "conversation": {}, "evidence": {}, "reference_checks": {}, "external_services": {}, "activity": {}},
  "customer_next_step": {},
  "created_at": "2026-08-10T03:40:00Z",
  "updated_at": "2026-08-10T03:50:00Z"
}
```

`work_summary.missing_information` carries one `external_service` item per recorded external task.
A terminal external failure is classified `required_now` with `claims_professional` responsibility
and the blocked requested action, so it becomes `work_summary.primary_blocker`: the contract
requires Northwind to review such a request before another attempt, and waiting on the external
party is not what happens next. Every other external state stays `follow_up` owned by the external
party. No second item is created for the same task.

`integration_summary.waiting_external_services`, and the `external_wait_count` derived from it,
exclude a task whose provider result has been received. A result is separate from task status, so
the task remains `accepted`; counting it as waiting would tell staff the claim is waiting on the
external party while the same claim's external-request lifecycle reports that the result requires
their review.

`section_summaries` reports availability, counts, and attention totals. Complete records are loaded
only when staff opens a section:

| Section | Endpoint |
| --- | --- |
| Fields | `GET /workbench/claims/{claim_id}/fields` |
| Sessions/messages | `GET /workbench/claims/{claim_id}/sessions` and `.../sessions/{session_id}/messages` |
| Evidence | `GET /workbench/claims/{claim_id}/evidence` |
| Policy/history/RAG | `GET /workbench/claims/{claim_id}/retrievals` |
| Signals | `GET /workbench/claims/{claim_id}/signals` |
| Handoffs/work items/customer updates | The corresponding typed sub-resource endpoints |
| External requests | `GET /workbench/claims/{claim_id}/external-requests` |
| Audit activity | `GET /workbench/claims/{claim_id}/events` |

Each sub-resource returns its own availability and limitation metadata. A failed optional source
does not invalidate the core Claim projection.
`source_summary` is a staff-only, source-preserving overview assembled from structured fields,
Evidence, active Handoffs, WorkItems, external tasks, and source-linked allowed actions. Its
`status` is `available`, `empty`, `partial`, or `unavailable`. `partial` and `unavailable` include
an honest `limitation`. Each item contains a stable `kind` and `record_ref`, a human-readable
`label`, `context`, and `source_label`, the source record's explicit `status`, and available
traceability dimensions: `source_refs`, `related_fields`, `needed_for`, `responsible_party`,
`confidence`, and `updated_at`. Opaque references supplement the human-readable context; they are
not the only explanation.

`work_summary.missing_information` is the staff Gap projection. Each entry contains `kind`, `code`,
`label`, explicit `status`, `attention`, `blocked_action` when supported, `responsible_party`, and
`source_refs`. Supported status values are `missing`, `disputed`, `conflicting`, `pending`,
`unavailable`, and `uncertain`. The projection derives these states from structured fields,
Evidence, active Handoff packets, open WorkItems, external-task records, and explicit source
availability. It does not infer provider success, verification, risk conclusions, or ownership
from free text.

`tags` follows the typed Staff Tag Registry contract;
`allowed_actions` is the authoritative runtime action projection. Each entry contains the action
registry version, exact `action_code`, target type and `target_ref`, availability (`available`,
`confirmation_required`, or `blocked`), confirmation metadata, expected and claimant-visible
effects, source references, failure codes, audit requirements, revision, result state, projected
input definitions, and typed immutable `payload_defaults`. The versioned definitions in
`backend/domain/workbench_action_registry.py` own these fields, registered choices, permission
requirements, and fixed completion effects. Projection, mutation validation, and persistence all
consume that registry. A mutating Workbench control and the corresponding runtime endpoint MUST resolve
the exact action-code/target pair and MUST NOT infer availability from role, ownership, list order,
or the presence of another action. `confirmation_required` is not equivalent to `available`: the
client must complete the projected confirmation step, and submitting the dedicated mutation is the
explicit confirmation recorded by the current endpoints. The runtime returns `403 ACCESS_DENIED`
with structured `action_code` and `target_ref` details when the exact action is absent or blocked;
it returns `409 REVISION_CONFLICT` before action resolution when the projection revision is stale.
The client may collect only the projected inputs and must submit the projected fixed fields unchanged.
An input with `required: true` is always required. An input with `required: false` and a
`required_when` object becomes required when the named projected field equals the registered value;
for example, `result.summary` and any projected `customer_update.summary` are required when
`status` is `completed`, but remain optional for `in_progress` and `cancelled` WorkItem
transitions. Ownership actions project their complete mutation inputs: cowork access requests and
requeue require `reason`; cowork invitations require `staff_id` and `reason`; transfer requests
require `target_staff_id` and `reason`; and cowork or transfer decisions require a registered
`decision` choice. Ownership mutation routes reject fields that are not present in the exact
projected action input set. Reusing an `Idempotency-Key` replays the original response. A new
key cannot create a second pending cowork request for the same target or a second pending transfer
to the same target; these attempts return `409 OWNERSHIP_CONFLICT` without changing the Claim
revision or creating another request.
For an `abandoned` or `closed` terminal Claim, the primary owner receives `claim.reopen` as
`confirmation_required` only when the retained workflow is resumable and no created external Claim
exists. Other staff may receive the same exact action as `blocked`; a `completed` Claim never
publishes a reopen action. Terminal Claims publish no ordinary active-work mutations. The reopen
action targets the Claim, requires the projected `reason` textarea, carries the prior terminal
sources, and declares `terminal_disposition.clear`, `claim.revision.advance`, and `audit.append`
as its expected effects.
`work_summary.primary_action_code`
and `primary_action_target_ref` identify the backend-selected primary action; either may be null
when no primary action is currently authorised. The pair always identifies the exact same
non-blocked `allowed_actions` entry. Clients display a Staff next action only when both values
exactly resolve to a non-blocked entry; they do not fall back to another action or infer one from
tags, queues, text, role, ownership, or field counts. `customer_next_step` remains a separate
claimant-safe projection.

### `POST /api/v1/workbench/claims/{claim_id}/reopen`

Executes only the exact non-blocked `claim.reopen` action from the current terminal Claim detail.
The route requires staff authentication, `Idempotency-Key`, and `If-Match`. Unknown request fields
are rejected; the body is:

```json
{
  "reason": "The claimant supplied the information needed to continue."
}
```

The authenticated staff member must be the primary owner. Only `abandoned` and `closed` are
reopenable; `completed`, a created external Claim, a non-resumable retained workflow, a missing
target, and an absent or blocked exact action fail explicitly. On success, the server clears only
`terminal_disposition`, preserves the retained `claim_state` and `active_session_id`, advances the
Claim revision exactly once, and atomically stores the staff-scoped idempotency result plus one
internal `action.completed` audit event containing the prior terminal source references, actor,
permission, reason, and resulting revision. The response is the updated
`WorkbenchClaimDetail`; its server-derived `work_summary.queue_key` is the destination queue.

The idempotency fingerprint includes both the request body and expected revision. Replaying the
same operation returns the first response. Reusing the key with a changed reason or `If-Match`
returns `409 IDEMPOTENCY_CONFLICT`; an unseen key with a stale revision returns
`409 REVISION_CONFLICT`. An absent/blocked action returns `403 ACCESS_DENIED`, and a missing Claim
returns `404 RESOURCE_NOT_FOUND` through the existing staff-safe boundary.

### `GET /api/v1/workbench/claims/{claim_id}/external-requests`

Returns each raw external task/request together with a backend-projected `lifecycle`. The lifecycle
contains stakeholder and service labels, the catalogue reference and request provenance, request
type, authority, consent, delivery and verification
states, pending owner, status label/detail, provider reference, returned-result summary and
provenance, result verification and checked Claim revision, linked evidence identifiers, limitation,
next action, and attention flag. `provider_reference` is the provider's routing or acknowledgement
identity and is never populated into `result`. `result` is null until a formal `ExternalTaskResult`
record exists; its `result_verification_state` remains `unverified`, `consistent`, `inconsistent`, or
`review_required` exactly as recorded, and an unverified result is not Claim State or provider
completion. `result_received_at` records ingestion time, while `result_verified_at` and
`result_verified_against_revision` are null until the separate verification operation records a
check. `result_evidence_ids` is empty when the returned result has no linked evidence;
`result_evidence` projects each linked Evidence ID with its current `status` and `file_status` for
staff without exposing storage keys or provider payloads.

`catalogue_reference` names the merged third-party service catalogue row that authorises this
service identity, so a persisted task can be traced to the entry permitting it. It is null for a
service the catalogue does not name.

`provenance` says what the request actually reached, which is not the same question as what was
configured for it:

| Value | Meaning |
|---|---|
| `simulated` | A fixture source. No production provider is involved, however far the request got — a delivery on a fixture records that a synthetic adapter accepted it, not that a provider did |
| `configured` | A configured service whose request has not been submitted. Configuration is not contact |
| `live_attempted` | A configured service whose request was submitted with delivery evidence. It states that an attempt reached a provider; it states nothing about the result, which is `result_verification_state`'s question |

It is derived from `integration_source` and `delivery` rather than stored, so it cannot disagree with
them. `live_attempted` is currently unreachable: the only implemented service identity is a
controlled fixture, and clients MUST NOT read `simulated` as evidence of a provider relationship.

The lifecycle's overall `verification_state`, `pending_owner`, `status_label`, `status_detail`, and
`next_action` remain the backend-owned operational projection. An `unknown_outcome` remains awaiting
reconciliation even when a late result record exists; the Workbench does not infer completion from
that result. The Workbench renders those fields and MUST NOT reconstruct lifecycle status or next
steps from raw task status strings. Raw task/request objects remain available for identity, timing,
failure, and source traceability.

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

### Staff presence and Claim acceptance

`PATCH /api/v1/workbench/staff/presence` accepts `online`, `available`, and a bounded
`lease_seconds` value (15-300). The server records `last_seen_at` and `expires_at`; an expired
lease is not claimable even when `online` and `available` are true. A successful staff login also
starts a five-minute online lease. `GET /api/v1/workbench/staff/online` returns only unexpired
records that are both online and available.

`POST /api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/accept` is the Claim acceptance
action for the current contract. Before the existing revision-checked, idempotent mutation runs,
the authenticated staff member must be authorised, online, available, and unexpired. The same
mutation writes the handoff assignment, `WorkingClaim.assignee_id`, the Claim revision, and its
idempotency result. Offline, unavailable, expired, already-claimed, and stale requests have
explicit structured outcomes. Presence is staff-only and is never included in claimant-safe
responses.

### `POST /api/v1/workbench/claims/{claim_id}/staff-actions`

Request:

```json
{
  "action_type": "coverage_review",
  "assigned_to": "stf_01J4Y9ADW2"
}
```

Response `201` returns the staff action and new claim revision.

This route is a legacy compatibility surface and is not rendered as a generic Workbench form. It
requires the exact current `work_item.create` action targeted at the Claim. `action_type` must be
one of the registry choices: `claimant_support`, `coverage_review`, `handoff_support`, or
`professional_review`. The registry supplies the immutable `requested_outcome`; the current Claim
projection supplies source references. Operator-supplied `requested_outcome` and `source_refs` are
rejected by the request schema. `assigned_to`, when supplied, remains limited to the primary owner
or an active coworker by the registered permission rule.

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
    "responsible_party": "claims_professional",
    "related_refs": ["act_01J4YB8D20"]
  }
}
```

The server requires the authenticated primary assignee and an exact `work_item.update` action for
this `action_id`. For completion, outcome, reason codes, source refs, state changes, responsible
party, and related refs must equal the registered fields projected in `payload_defaults`; only
projected input fields such as summaries and status may be supplied by the operator. Response `200`
returns the action, resulting claim revision, and customer update when created.

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
The route requires primary ownership plus an exact `signal.record_decision` action targeted at the
signal. Decision and reason values must come from that action's projected choices, and evidence
references must match its fixed payload defaults.

### Handoff Accept and Resolve

`POST /api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/accept` requires the exact current
`human.accept_handoff` action and accepts the queued handoff for the authenticated staff member or
an authorised `assignee_id`. The action is blocked when the effective Claim owner, taken from the
active handoff owner or Claim assignee, is another staff member.

After a handoff is accepted, both parties may continue using the persisted session message
history. A claimant message during an open handoff is routed to staff without an automatic Agent
reply. Claimants continue through the ordinary message route; there is no claimant command prefix.
Staff messages use
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
    "reason_codes": ["SUPPORT_NEED_MET"],
    "source_refs": ["msg_01J4Y7T1KC"]
  },
  "state_changes": [],
  "customer_update": {
    "summary": "Your report is ready to continue online.",
    "responsible_party": "claims_professional",
    "related_refs": ["hnd_01J4Y7XG2C"]
  }
}
```

Resolve requires an exact `human.resolve_handoff` action targeted at the accepted handoff. Result
outcome, reason codes, source refs, state changes, responsible party, and related refs are registered
server projections; the operator supplies only the projected summaries. Resolving a handoff MUST
record the staff result, state changes, claimant update, actor, timestamps, and resulting claim
revision.

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

### `POST /api/v1/workbench/demo/seed-validation`

Seeds the three Sprint 3 field-state validation paths: motor, home, and contents. The endpoint
is available only in development and test environments, requires an active staff account, and
uses the canonical scenarios `AT-14-field-states-motor`, `AT-15-field-states-home`, and
`AT-16-field-states-contents`. It creates new opaque Claim, Session, Message, and Evidence
identifiers for each request, assigns the current staff member, and provisions the synthetic
claimant account `claimant.one@example.invalid` when the normal local identity store does not
already contain it. The route uses the existing Claim, Session, Message, Evidence,
`StaffPresenceRecord`, and idempotency contracts; it does not add fields or replace the older
`seed-scenarios` queue.

The request has no body and requires an `Idempotency-Key`. The first accepted request persists all
three graphs, presence lease, and retry response atomically. Repeating the same key replays the
original response without creating records. A different key is rejected with
`409 DEMO_SEED_REQUIRES_EMPTY_QUEUE` when any Claim already exists. Persistence failure leaves no
partial Claim graph. The synthetic cross-role reference is explicitly `unofficial` with
`file_status=not_available`, and the endpoint never invents an object-storage key, checksum, or
file for it. The produced demonstration materials (`backend/demo_data/materials/`) are attached
to the Claim of their family as Evidence carrying their catalogued condition. Each material that
has a file is stored through the evidence storage adapter's `store_generated_content` before the
graph is persisted, and its record carries the returned `storage_key` and `upload_checksum`, so
the Workbench evidence content route serves the committed bytes. If evidence storage is
unavailable, the request returns `503 DEPENDENCY_UNAVAILABLE` with `retryable: true` and persists
nothing.

Response `200`:

```json
{
  "status": "seeded",
  "scenario_ids": [
    "AT-14-field-states-motor",
    "AT-15-field-states-home",
    "AT-16-field-states-contents"
  ],
  "claim_ids": [
    "clm_opaque_motor",
    "clm_opaque_home",
    "clm_opaque_contents"
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

The claimant message route now implements one minimal target slice: `claim.read` is executed
against the authenticated Claim, the same model receives the tool result, and the final
`conversation.answer`/`runtime.continue` response is persisted with a read-only Runtime trace.
This slice returns `decision: null` and keeps Claim revision unchanged. The remaining target
types and an independent `/internal/v1/agent/turns` route are still a migration boundary, not
an implemented public payload; they require coordinated backend models, persistence, consumers,
fixtures, generated OpenAPI, and contract tests.

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

Every response contains `retrieved_at`, the server-observed UTC time at which that retrieval result
was produced. It is present for `evidence_found`, `no_evidence`, `timeout`, and `unavailable`, and
is distinct from a document's ingestion time or a provider-supplied timestamp. An
`evidence_found` response contains exact `document_id`, `chunk_id`, `section_path`, source URI,
version, checksum, and source text for every result. `no_evidence` returns no results and an honest
scope limitation. `timeout` and `unavailable` return no results, include the shared connection and
structured-error projection described below, and remain retryable. Provider errors, traceback
content, credentials, endpoints, and object-store identifiers are not exposed. Missing
applicability fields fail request validation rather than broadening the search. The deterministic
knowledge retriever does not expose a numeric confidence value because the current contract has no
authoritative confidence semantics.

Response excerpt:

```json
{
  "status": "evidence_found",
  "retrieved_at": "2026-09-09T10:55:00Z",
  "connection_state": "configured_service",
  "errors": [],
  "results": [
    {
      "document_id": "nw-policy-motor-standard-mvp-2026-1",
      "chunk_id": "nw-policy-motor-standard-mvp-2026-1#MTR-EXC-01",
      "title": "Northwind Motor Standard Policy",
      "section_path": "MTR-EXC-01 - Excesses",
      "source_uri": "northwind://synthetic-policy/motor/MVP-2026.1",
      "version": "MVP-2026.1",
      "checksum": "a7e4d4782f90571c7a711823fe14b1d580e13a867613a9a833a33a1fdc1ad989",
      "text": "The base excess and any driver, age, use, or other additional excess come only from the matching policy schedule."
    }
  ],
  "limitations": []
}
```

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
  "connection_state": "using_fixture",
  "errors": [],
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

Status is `evidence_found`, `no_evidence`, `ambiguous`, `timeout`, or `unavailable`.

- `evidence_found` returns allow-listed facts with the `source` that supplied
  them, and persists a retrieval record against the claim.
- `ambiguous` returns the same facts plus explicit `uncertainty`. Each
  uncertainty becomes a staff-only professional-review signal. Ambiguity is
  reported as evidence for a person; it is never resolved here.
- `no_evidence` means the provider answered and holds no matching record.
- `timeout` means the provider exceeded the request budget. It reports
  `connection_state=degraded` and one retryable `errors[].code=timeout` item.
- `unavailable` means the provider could not answer. It reports
  `connection_state=unavailable` and one retryable `errors[].code=unavailable` item.
- If a knowledge, policy, or claim-history provider raises an unexpected adapter error or
  returns a malformed response, the API returns `502 DEPENDENCY_FAILED` with a bounded message
  and `retryable=false`; no retrieval evidence or provider payload is persisted or returned.
  Both failure states carry claimant-safe `limitations`, never carry `facts` or a
  `source`, and persist nothing, because an absent answer must not become a finding.

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
  "connection_state": "using_fixture",
  "errors": [],
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

### Shared data-query outcome projection

The knowledge, policy, and claim-history search responses expose the same operational fields so a
consumer does not infer provider state from an empty result:

- `connection_state` is `using_fixture`, `verified`, or `configured_service` for a usable selected
  adapter, `degraded` for a timed-out request, and `unavailable` when the selected adapter could not
  answer. Fixture state remains explicit and is never relabelled as a verified provider.
- `errors` is empty for `evidence_found`, `ambiguous`, and `no_evidence`. A timeout or unavailable
  response contains exactly one item with the bounded `code`, a safe `message`, and
  `retryable=true`.
- `no_evidence` means the selected adapter answered successfully but supplied no applicable
  evidence. It is not an error and does not imply a negative policy, coverage, or history finding.
- Evidence results must carry their exact retrieval `source` or knowledge citations. Timeout,
  unavailable, and no-evidence results cannot carry facts, citations, uncertainty, or a source.

The API never returns raw provider exceptions, tracebacks, connection strings, credentials,
endpoints, or provider-only payloads through `errors` or `limitations`.

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
to `ready` and writes registered extracted fields as `proposed`. The optional
`outcome` is `ready`, `failed`, or `retry`; `failed` moves the existing file to
the registered `failed` status without persisting a provider error payload, and
`retry` moves that same Evidence record back to `processing`. Both outcomes
use the same Claim revision and idempotency boundary. A failed or processing
Evidence item remains attention-required and cannot satisfy a Claim evidence
requirement; only `ready` Evidence is usable.

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

### `POST /internal/v1/claims/{claim_id}/external-tasks/{task_id}/reconcile`

Checks the provider-neutral status of one persisted `unknown_outcome` assessor request. The route
requires integration-service authentication, `Idempotency-Key`, and `If-Match`, and accepts no
request body. The client cannot supply a provider reference, routing state, consent, authority, or
settlement choice. Runtime resolves the existing task, its single sent request, the assessor
operation, the referenced consent and Northwind authority, and the current Claim before invoking
the installed adapter's status-check operation.

Response `200` returns the existing `AssessorRoutingResult` after the provider status path confirms
acceptance. The same `task_id`, `request_id`, and operation identity are retained. Reconciliation
adds the new provider reference, advances the task and operation from `unknown_outcome` to
`accepted`, records the pending assessment material and immutable task-to-evidence link, and writes
the routing result and claimant-safe next step to one new Claim revision. Those records are one
persistence transaction; a revision or identity conflict leaves all of them unchanged. An
identical replay returns the settled result without another status check, even though the first
settlement advanced the Claim revision.

If the status check remains inconclusive, the route returns `409 INVALID_STATE_TRANSITION` with
`retryable: true` and `details[].reason` `unknown_outcome`. The task and operation stay
`unknown_outcome`, and the existing refusal still prevents another assessor-routing request. An
unavailable status dependency returns `503 DEPENDENCY_UNAVAILABLE`; a malformed, access-denied, or
non-accepted status answer returns `502 DEPENDENCY_FAILED`. A missing task returns
`404 RESOURCE_NOT_FOUND`; a stale first settlement returns `409 REVISION_CONFLICT`. None of these
paths writes partial settlement state.

This endpoint implements accepted settlement only. A provider statement that the original request
was not submitted does not turn `unknown_outcome` into `retryable_failure` and cannot authorise a
retry. That outcome requires a separate durable reconciliation-record contract.

### `POST /internal/v1/claims/{claim_id}/external-tasks/{task_id}/result`

Receives the bounded result for one accepted assessor task through the configured assessor
adapter. The route requires integration-service authentication, an `Idempotency-Key` header, and
an `If-Match` header naming the current Working Claim revision; it accepts no request body. The task
must belong to the named Claim, use `P3-ASSESSOR`, have an accepted provider acknowledgement, and
match the assigned assessor record on the current Working Claim. An identical replay returns the
stored result even though the first receipt advanced the Claim revision.

Response `201`, or `200` when the task result already exists:

```json
{
  "result_id": "res_01J4YERESULT",
  "task_id": "tsk_01J4YETASK",
  "claim_id": "clm_01J4Y7Q2AW",
  "source": {
    "system": "controlled_assessment_fixture",
    "reference": "fixture-assessment/2d711642b726",
    "retrieved_at": "2026-08-11T05:00:00Z"
  },
  "summary": "The controlled assessment fixture returned a simulation-only vehicle damage report for Northwind review.",
  "verification": "review_required",
  "verified_at": "2026-08-11T05:00:01Z",
  "verified_against_revision": 5,
  "evidence_ids": ["evd_01J4YETASK"],
  "received_at": "2026-08-11T05:00:01Z"
}
```

The controlled fixture produces a JSON report marked `simulation_only`. Runtime stores its bytes
through the active Evidence storage profile, completes the task's existing `assessment_report`
Evidence record, links the Evidence to the immutable task, and verifies the result against that
link and the resulting Claim revision. The source timestamp records when the adapter says the
report was produced. `received_at` records when Northwind bound the report to Evidence, and
`verified_at` records the later verification operation.

The provider acknowledgement on the task remains separate from the returned result. Receipt does
not alter Claim facts, workflow state, coverage, repair authority, or the claimant-visible assessor
status. A controlled result is `review_required` until a separate authorised staff path promotes
any supported fact. Workbench reads can show the result summary, provenance, verification state,
checked revision, and Evidence lifecycle without exposing storage keys or raw provider payloads.

An unknown Claim or task returns `404`. A missing or stale Claim revision, a task that is not the
matching accepted assignment, an Evidence-origin conflict, or a changed replay returns `409`.
Malformed or incorrectly labelled adapter output returns non-retryable `502`. A temporary Evidence
storage outage returns retryable `503`; an unchanged retry resumes without creating a second
result, Evidence record, or Claim revision.

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
| Terminal disposition | `CLAIM_CREATED`, `ABANDONMENT_POLICY_APPLIED`, `AUTHORISED_CLOSURE` |
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
| `ACCOUNT_NOT_FOUND` | `404` | Customer or staff account is absent |
| `SESSION_NOT_FOUND` | `404` | Account session is absent or does not belong to the requested account |
| `INVALID_STATE_TRANSITION` | `400` | Requested transition is not allowed |
| `INVALID_TAG_FILTER` | `400` | Workbench tag filter is unknown, unpublished, or not exposed as filterable by the backend Registry |
| `REVISION_REQUIRED` | `409` | Required `If-Match` header absent |
| `REVISION_CONFLICT` | `409` | Claim changed since the client read it |
| `STAFF_NOT_AVAILABLE` | `409` | Staff presence is offline, unavailable, or its lease has expired |
| `STAFF_PRESENCE_UNAVAILABLE` | `503` | Staff presence could not be persisted; retry after the dependency recovers |
| `RESOURCE_CONFLICT` | `409` | A unique account or resource already exists |
| `SESSION_NOT_ACTIVE` | `409` | Session is expired or already revoked |
| `IDEMPOTENCY_CONFLICT` | `409` | Key was reused with a different request |
| `DEMO_SEED_REQUIRES_EMPTY_QUEUE` | `409` | Controlled demo seed requires an empty Claim queue |
| `DEMO_CLAIMANT_UNAVAILABLE` | `409` | Synthetic claimant identity is unavailable for a controlled demo seed |
| `VALIDATION_FAILED` | `422` | One or more requested validation scenarios failed |
| `CONFIGURATION_APPROVER_CONFLICT` | `403` | A high-impact configuration's sole author attempted publication |
| `PROVIDER_CONFIGURATION_INVALID` | `422` | Provider configuration is incomplete or structurally invalid |
| `PROVIDER_CONFIGURATION_UNAVAILABLE` | `422` | Provider configuration is unverified or outside deployment authority |
| `OPERATIONAL_CONFIGURATION_INVALID` | `422` | Operational cost, rate-limit, or alert configuration is incomplete or invalid |
| `SECRET_VALUE_FORBIDDEN` | `422` | Secret values must use protected references |
| `ACTIVE_SESSION_EXISTS` | `409` | A conflicting active session exists |
| `UNSUPPORTED_MEDIA_TYPE` | `415` | File type is not allowed |
| `UPLOAD_TOO_LARGE` | `413` | File exceeds configured size |
| `RATE_LIMITED` | `429` | Caller exceeded a limit |
| `DEPENDENCY_UNAVAILABLE` | `503` | Required service is unavailable |
| `PROJECTION_UNAVAILABLE` | `503` | Authoritative Claim facts conflict or cannot be placed in a published Workbench projection |
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
    "control_plane_release_set": "none",
    "control_plane_domains": "none",
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

`control_plane_release_set` identifies the active published Release Set by its opaque ID, or
`none` when the explicit development/bootstrap fallback is in use. `control_plane_domains` is a
comma-separated list of configuration domains loaded from that Release Set. These fields expose
which published boundary the process resolved without returning configuration values or secrets;
an `unavailable` value means the active Release Set could not be resolved safely.

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
