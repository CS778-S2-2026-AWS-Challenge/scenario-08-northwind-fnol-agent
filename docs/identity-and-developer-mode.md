# Identity and Developer-Mode Contract

## Purpose

This document defines the provider-neutral identity boundary shared by claimant, staff,
administration, Agent, and integration surfaces. It is the Day 1 contract for Issue #238
and the implementation input for Issue #247.

It defines roles, scopes, principal metadata, synthetic developer identities, production
guards, resource-authorisation boundaries, migration requirements, and audit metadata. It
does **not** select a production identity provider, create an Admin API, implement staff
entitlement policy, implement complete operation-specific integration authorisation, or
claim that production authentication is configured.

## Core Rules

1. Authentication and authorisation are server-side boundaries. A client-supplied role,
   customer identifier, staff identifier, scope, assignment, tool permission, or developer
   flag never grants access.
2. Normal mode never falls back to a synthetic principal when identity verification is
   missing, unavailable, or misconfigured.
3. Developer mode is an explicit startup choice. Development or test environment names
   alone do not imply that synthetic authentication is enabled.
4. Synthetic principals are fixed development identities, not aliases for arbitrary
   production users. Their role and scopes are derived by the server from a registered
   synthetic credential profile.
5. Developer mode is valid only in explicitly allow-listed non-production environments.
   Under the current environment contract that allow-list is `development` and `test`;
   every other environment value rejects developer mode until it is deliberately
   classified.
6. Claimant, staff, administrator, Agent-service, and integration-service authority stay
   distinct. One credential cannot silently cross those actor boundaries.
7. Role and scope are necessary but not sufficient for protected domain access. Claim
   ownership, staff task/queue authority, integration operation allow-lists, and other
   resource checks remain separate server-side decisions.
8. Every verified identity exposes enough non-secret principal metadata for an audit
   record. This requirement does not imply that access-audit persistence is already
   implemented.
9. Model output, browser state, retrieved content, provider payloads, and tool results
   cannot manufacture a principal or expand its authority.

## Runtime Modes

Identity mode and deployment environment are separate concepts.

| Identity mode | Intended use | Synthetic credentials | Failure behaviour |
| --- | --- | --- | --- |
| `normal` | Any environment, including production | Rejected | Verify through the configured identity boundary; if that boundary is unavailable, fail closed |
| `developer` | Explicit local development and automated-test runs only | Allowed for registered synthetic principals | Reject unknown credentials and unregistered roles; never broaden to anonymous access |

The implementation in #247 must expose an explicit `developer_mode` startup setting, or
an equivalently explicit identity-runtime enum. The default must be normal/fail-closed;
`environment=development` or `environment=test` must not silently enable synthetic
authentication.

Under the current environment vocabulary, the only valid combinations with developer
mode enabled are:

```text
environment = development
or
environment = test

developer_mode = true
```

Any other environment value with `developer_mode=true` is a startup/configuration error.
This is intentionally an allow-list rather than a guessed list of strings such as
`production`, `prod`, `stage`, or `staging`: an unknown deployment class must fail safe
until explicitly classified.

Likewise, a normal-mode deployment with no configured identity verifier must fail closed
for protected routes. It must not recover by accepting repository synthetic claimant,
staff, administrator, or integration credentials. Health endpoints may remain available
for diagnosis. If readiness later includes identity capability, it must report the
missing verifier honestly rather than imply protected requests are usable.

### Implemented Local Staff Sessions

The current normal-mode local runtime has a separate persistent staff account and session adapter.
It stores staff accounts and revocable session hashes in a dedicated SQLite database, distinct
from claimant accounts and claimant sessions. The staff login route returns an opaque token once;
the server resolves it to a provider-neutral `staff` principal with the Workbench scopes.

Initial local provisioning is explicit through the paired
`NORTHWIND_STAFF_BOOTSTRAP_EMAIL`/`NORTHWIND_STAFF_BOOTSTRAP_PASSWORD` settings. The account is
created only when that email is absent, and only the salted scrypt password hash is persisted.
The bootstrap secret should be removed from the process environment after provisioning.

Developer mode instead provides one isolated fixture staff account and still accepts the bounded
synthetic compatibility token for existing tests. Neither path is a claim that enterprise staff
identity is complete. An approved production IdP, SSO/MFA, recovery, account lifecycle,
organisation/role provisioning, and per-Claim entitlement policy remain separate work.

## Principal Contract

The application-level principal is provider-neutral. A verified token, session, mTLS
identity, or future provider adapter is normalised before route or service logic sees it.

A principal carries at least:

```text
subject             stable provider-neutral actor/customer identifier
actor_type          claimant | staff | administrator | agent_service | integration_service
scopes              server-derived set of permitted capabilities
auth_source         configured verifier/profile identifier
synthetic            true only for an explicit developer-mode identity
```

Provider token claims, SDK objects, bearer-token values, refresh tokens, secret
references, provider-specific group structures, and raw entitlement payloads stay inside
the identity adapter.

`subject`, `actor_type`, `scopes`, `auth_source`, and `synthetic` are authoritative only
after server-side verification. Request bodies, query strings, browser state, headers
such as `X-Role` or `X-User`, and model/tool output cannot override them.

The principal is intentionally not a copy of every resource entitlement. Assignment,
queue membership, claim access, integration operation permission, and other changing
resource policy may be resolved by a separate authorisation service or repository lookup.
Those checks consume the verified principal; they are not supplied by the client.

## Roles and Minimum Scopes

The initial role-to-scope contract is intentionally narrow.

| Actor type | Minimum scopes | Primary boundary |
| --- | --- | --- |
| claimant | `claim:read:self`, `claim:write:self` | Own claimant-visible Claim State, sessions, messages, evidence, support requests, status |
| staff | `workbench:read`, `workbench:write` | Authorised internal claim/workbench projections and staff mutations |
| administrator | `admin:read`, `admin:write` | Separately contracted Control Plane configuration and audit surfaces |
| agent_service | `agent:execute` plus explicitly granted tool capabilities | Claim-scoped orchestration only when an external service boundary exists |
| integration_service | `tools:invoke` plus an allow-listed operation/purpose | Narrow internal adapter routes |

Scopes are capabilities, not role aliases and not wildcard resource grants. A future
staff principal may receive `operations:read` without receiving administrator
configuration authority. An administrator does not automatically receive claimant or
unrestricted production Claim State editing authority.

The Admin API is not yet implemented. `admin:read` and `admin:write` define the identity
boundary that #209/#247/#258 must preserve when Admin routes are added; their presence
here does not make an Admin route current or production-ready.

### Base scope is not operation authority

`tools:invoke` means that a verified integration service belongs to the class of callers
that may invoke internal tools. It does **not** authorise every `/internal/v1/*`
operation. The server must also verify that the identity profile or controlled policy
allows the requested operation and purpose. A credential intended for policy lookup,
for example, must not gain claim-creation or evidence-processing authority merely because
both routes share the same base scope.

This is a target authorisation boundary, not an expansion of #247 into a complete
operation-specific integration policy. #247 must establish the integration principal and
its server-derived base scope, preserve any narrower route/domain checks that already
exist, and avoid broadening access. Full operation/purpose least privilege remains a
separate policy slice unless deliberately added with its own acceptance evidence.

Similarly, `workbench:read` does not mean that every staff identity may read every claim,
and `workbench:write` does not mean that every staff identity may mutate every staff work
item.

## Identity Boundary Versus Resource Authorisation

Authentication answers **who** the caller is. Actor type and scope answer the caller's
coarse capability class. Resource authorisation answers **which specific data or task**
the caller may access right now.

### Claimant resources

- `customer_id` is derived from the verified claimant principal.
- Claim reads, sessions, messages, evidence, and mutations remain scoped to that customer.
- Another claimant's identifier in a URL or payload never changes the principal's owner
  boundary.
- Existing concealment behaviour may return `404` rather than reveal that another
  customer's claim exists.

### Staff resources

Staff access must combine the verified staff principal with an explicit staff-access
policy. Depending on the approved workflow, that policy may permit a queue, an unassigned
work pool, an assigned handoff/action, or another documented task class. It must not be
implemented as the assumption that every staff identity can read and mutate every claim.

Read and write authority may differ. For example, a staff member may be permitted to see
an unassigned queue item before accepting it, while resolution of an assigned handoff
must respect its owner. The application must define and test those distinctions rather
than relying on `actor_type == 'staff'` alone.

### Administration resources

Administrator authority is configuration/control-plane authority. It does not provide a
back door to claimant Claim State or unrestricted staff work. Any exceptional operations
access must have a separately named role/scope/purpose and audit rule.

### Integration resources

Integration services use operation- and purpose-limited authority in addition to the
base integration role/scope. Business-state preconditions such as an authorised
`CREATE_CLAIM` decision remain required, but they do not replace caller authorisation.
A valid domain command and a permitted caller are independent checks and both must pass.

The current Week-4 identity slice does not claim that this complete operation/purpose
policy is implemented. Until that policy exists, existing internal route and deterministic
domain guards remain authoritative and #247 must not weaken them or describe the base
`tools:invoke` scope as unrestricted tool authority.

## Client Entry-Point Boundaries

### Claimant client

- Accept only a claimant principal with self-scoped claim capabilities.
- Derive `customer_id` from the principal, never from a request body or browser field.
- Never expose staff/internal review material because a browser asks for a broader
  projection.
- A browser-supplied synthetic token must never switch the server into developer mode.

### Staff Workbench

- Accept only an authorised staff principal with the required Workbench scope and
  resource/task authority.
- Derive staff actor identity from the principal for assignment, decisions, handoff
  acceptance, write-back, and audit.
- A claimant, administrator, or integration credential receives an access denial rather
  than a downgraded response from a Workbench route.

### Administration / Control Plane

- Accept only an administrator principal with the required Admin scope.
- Keep Admin routes separate from claimant and Workbench routes.
- Never return complete secret values or permit unrestricted direct Claim State editing.
- Until an Admin API exists, the absence of an Admin route is the correct behaviour; a
  synthetic admin principal does not create one implicitly.

## Agent-Service Boundary

The provider-neutral actor taxonomy reserves `agent_service` for a future external Agent
service boundary. The current application does not expose the in-process
`AgentTurnProvider`/`ControlledAgent` as a bearer-authenticated network service.

Therefore #247 must **not** invent a synthetic Agent bearer token merely to make the role
table symmetrical. In the current composition, orchestration executes inside the
application under already-authorised claim context and deterministic authority checks.
Model output is not a principal and cannot gain `agent:execute`, tool access, or Claim
State authority from its own response.

If the Agent is later deployed behind a remote service boundary, that service requires a
verified service identity, `agent:execute`, claim/task-bound context, an explicit tool
allow-list, and the same deterministic action authority. Externalising the transport must
not increase what the Agent is allowed to decide or access.

## Synthetic Developer Principals

Developer mode provides a bounded replacement for a real identity provider during local
work and tests. It is not anonymous mode.

Each synthetic credential maps to exactly one registered principal profile, for example:

| Synthetic profile | Actor type | Example subject | Scope class |
| --- | --- | --- | --- |
| claimant fixture | claimant | `cus_demo` | claimant self-service only |
| staff fixture | staff | `stf_demo` | Workbench base scopes; resource policy still applies |
| admin fixture | administrator | `adm_demo` | Admin only, once Admin routes exist |
| integration fixture | integration_service | `integration_fixture` | `tools:invoke` base scope; operation/purpose policy remains separate |

There is intentionally no synthetic Agent-service credential in the current in-process
runtime.

Requirements:

- credentials for different synthetic profiles must be pairwise distinct;
- an unknown bearer token is authentication failure, not a new synthetic user;
- a known token presented to another actor boundary is access denied;
- the principal is marked `synthetic=true` and has a non-secret `auth_source` indicating
  developer mode;
- synthetic base scopes come from the registered server profile; any operation/purpose
  permissions that are already implemented also remain server-derived, but #247 does not
  invent a complete operation-specific integration policy merely to populate the profile;
- synthetic subjects and fixture data remain anonymous and must not resemble real
  customer credentials; and
- any environment outside the explicit `development`/`test` developer-mode allow-list
  rejects developer mode before serving requests.

Developer mode must not accept arbitrary `X-Role`, `X-User`, scope, query-string, cookie,
or request-body values that manufacture a principal or add authority.

## Developer-Mode Migration Contract

Moving from the current implicit prototype authentication to explicit developer mode is a
security migration, not a flag rename. #247 and its consumers must preserve these rules:

1. the server default is normal/fail-closed identity mode;
2. test fixtures that use synthetic credentials explicitly construct developer-mode
   settings rather than receiving synthetic access because `Settings()` defaults to a
   development environment;
3. local demo/start instructions explicitly enable developer mode; the environment name
   alone is insufficient;
4. `.env.example` documents the explicit identity-mode variable and all implemented
   synthetic profiles needed by the local demo, without suggesting they are production
   credentials;
5. claimant and staff clients may use synthetic credentials only as explicit local-demo
   configuration; a hard-coded or fallback browser token does not enable developer mode
   and must not be presented as a production authentication path;
6. normal-mode clients must obtain identity from the configured real verifier/session
   boundary when one exists, rather than silently falling back to a repository synthetic
   value; and
7. existing cross-role, ownership, projection, demo-endpoint, and deprecated-route tests
   remain green after the migration.

The current customer client has a synthetic claimant fallback, the static Employee
Workbench contains a synthetic staff token, and the shared test fixtures construct
`Settings()` while using synthetic credentials. These are explicit migration inputs for
Issue #247 is not evidence that developer mode should remain implicitly enabled.

## Authentication and Authorisation Order

For every protected request the server applies this order:

1. classify the route's required actor/scope boundary;
2. obtain the presented credential through the configured authentication mechanism;
3. verify it using **normal** or explicit **developer** identity mode;
4. normalise the verified identity into the provider-neutral principal;
5. reject actor-type or base-scope mismatch before loading or mutating protected domain
   data;
6. enforce resource ownership, staff task/queue authority, integration operation purpose,
   or another applicable resource policy;
7. enforce domain-state and deterministic action-authority preconditions;
8. execute the operation using the verified principal subject as the actor/customer
   identity; and
9. expose the bounded audit metadata/result without credential material.

Authentication proves who the caller is. Scope, resource policy, and domain authority
remain separate decisions. Passing one layer never skips a later layer.

## Failure Contract

| Condition | Result |
| --- | --- |
| Missing/invalid credential | `401 AUTHENTICATION_REQUIRED` |
| Valid credential for the wrong actor/base scope | `403 ACCESS_DENIED` |
| Valid actor/base scope but disallowed staff resource or integration operation | `403 ACCESS_DENIED` or the documented concealment response; no protected data/action |
| Valid claimant principal requesting another claimant's resource | `404` or `403` according to the current concealment contract; never return the other claim |
| Normal-mode identity verifier unavailable | Bounded authentication/dependency failure; no synthetic fallback |
| `developer_mode=true` outside `development`/`test` | Startup/configuration failure before routes are served |
| Unknown synthetic credential in developer mode | `401 AUTHENTICATION_REQUIRED` |

Authentication and authorisation failures must not echo token values, secret references,
provider response bodies, raw entitlement documents, or unnecessary identity claims.

## Audit Contract

A successful or rejected protected request must be attributable without persisting the
credential itself. The identity boundary must make available at least:

```text
request_id
subject (only when verified)
actor_type (only when verified)
auth_source
synthetic
route or operation
required scope / authority boundary
resource/purpose class when applicable
outcome: authenticated | denied | failed
reason code
timestamp
```

The existing request-ID middleware can supply request correlation, but current `main`
does not yet persist a complete identity access-audit event for every protected request.
The richer principal in #247 must make the required metadata available; later audit
persistence/verification must not be falsely inferred from that model change alone.

Unknown credentials must never be stored as a pseudo-subject merely to make a failed
request attributable. Material domain writes continue to record their existing actor,
reason, revision, source, and outcome data. Identity access audit augments that
provenance; it does not replace claim events, integration evidence, or staff decision
records.

Do not log bearer tokens, API keys, refresh tokens, complete provider claims, raw
identity-provider responses, or unnecessary entitlement details by default.

## Current Implementation and Week 4 Gap

Current `main` already has useful prototype protections:

- claimant, staff, and integration synthetic tokens are pairwise distinct;
- claimant/staff/integration routes reject another synthetic role's credential;
- protected routes reject unknown or missing bearer tokens;
- claimant services derive customer ownership from `principal.subject` rather than a
  request-body customer identifier;
- the deprecated claimant route remains authenticated;
- local demo reset/seed routes require staff authentication as well as a development/test
  environment; and
- synthetic credentials are rejected when `NORTHWIND_ENVIRONMENT` is outside
  `development`/`test`.

Those behaviours remain valid evidence, but they are not the complete target contract.
The current gaps are explicit:

- synthetic authentication is implicitly enabled whenever the environment is
  `development` or `test`; there is no explicit identity mode;
- `Principal` exposes only `subject` and `actor_type`; scopes, `auth_source`, and the
  synthetic marker do not exist;
- there is no administrator principal or Admin route boundary;
- staff Workbench read access currently checks the staff actor type and can enumerate
  internal claims; a complete queue/assignment/task authorisation policy is not yet
  implemented uniformly across reads and writes;
- the single integration synthetic credential currently protects the integration actor
  boundary but does not provide operation-specific least privilege across all internal
  tool routes;
- the in-process Agent is not an authenticated service principal and should not be
  presented as one;
- the customer client, static Employee Workbench, `.env.example`, and shared test fixtures
  still reflect the implicit synthetic-authentication prototype and require deliberate
  migration; and
- request IDs exist, but complete identity access-audit persistence is not implemented.

Issue #247 implements the next bounded slice. It should introduce explicit developer-mode
selection, normalise the richer claimant/staff/admin/integration principals, add the
administrator guard needed by the future Admin API, preserve existing cross-role and
claimant-ownership behaviour, add the production/non-production startup guard, and make
the synthetic/auth-source metadata available for audit.

For integration-service identity specifically, #247 establishes the fixed synthetic
principal and its base scope, preserves existing caller/domain checks, and must not turn
`tools:invoke` into wildcard operation authority. It does not need to complete the future
operation/purpose policy in order to satisfy the bounded Day-2 identity slice.

Issue #247 must not be described as completing production identity, staff entitlement policy,
operation-specific integration authorisation, or persisted access audit unless those
capabilities and their tests are deliberately added to that issue's scope. The contract
exists so those boundaries cannot be accidentally erased while the first implementation
slice is delivered.

## Verification Inputs for #247 / #268

A repeatable implementation check should prove at least:

1. normal mode rejects all repository synthetic credentials even when the deployment
   environment is `development` or `test`;
2. developer mode accepts only registered synthetic profiles and preserves their fixed
   actor types, scopes, auth source, and synthetic marker;
3. claimant, staff, admin, and integration credentials cannot cross actor boundaries;
4. `developer_mode=true` starts only under the explicit `development`/`test` allow-list
   and fails for every other environment value;
5. no protected route trusts client-supplied identity, role, scope, assignment, operation
   permission, or developer-mode fields;
6. audit-visible principal metadata marks synthetic requests without storing the token;
7. claimant ownership and claimant/internal projection regressions remain green;
8. staff Workbench tests do not treat role authentication as proof of a future complete
   assignment/task authorisation policy;
9. integration tests preserve existing domain-action/caller checks and prove the base
   integration scope is not treated as evidence that complete operation-specific policy
   has been implemented; and
10. local demo and automated tests opt into developer mode explicitly rather than relying
    on the environment name.

These checks establish the first explicit identity boundary. They do not constitute a
production IdP, SSO, MFA, session management, staff entitlement system, operation-level
service mesh, key rotation, recovery, access-audit store, or compliance readiness.
