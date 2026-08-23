# Identity and Developer-Mode Contract

## Purpose

This document defines the provider-neutral identity boundary shared by claimant, staff,
administration, Agent, and integration surfaces. It is the Day 1 contract for Issue #238
and the implementation input for Issue #247.

It defines roles, scopes, principal metadata, synthetic developer identities, production
guards, and audit requirements. It does **not** select a production identity provider,
create an Admin API, or claim that production authentication is configured.

## Core Rules

1. Authentication and authorisation are server-side boundaries. A client-supplied role,
   customer identifier, staff identifier, scope, or developer flag never grants access.
2. Normal mode never falls back to a synthetic principal when identity verification is
   missing, unavailable, or misconfigured.
3. Developer mode is an explicit startup choice. Development or test environment names
   alone do not imply that synthetic authentication is enabled.
4. Synthetic principals are fixed development identities, not aliases for arbitrary
   production users. Their role and scopes are derived by the server from a registered
   synthetic credential profile.
5. Developer mode must fail startup outside an explicitly non-production environment.
6. Claimant, staff, administrator, Agent-service, and integration-service authority stay
   distinct. One credential cannot silently cross those role boundaries.
7. Every authenticated request exposes enough principal metadata for an audit record,
   without exposing the credential itself.

## Runtime Modes

Identity mode and deployment environment are separate concepts.

| Identity mode | Intended use | Synthetic credentials | Failure behaviour |
| --- | --- | --- | --- |
| `normal` | Any environment, including production | Rejected | Verify through the configured identity boundary; if that boundary is unavailable, fail closed |
| `developer` | Local development and automated tests only | Allowed for registered synthetic principals | Reject unknown credentials and unregistered roles; never broaden to anonymous access |

The implementation in #247 must expose an explicit `developer_mode` startup setting (or
an equivalently explicit identity-runtime setting). Its external environment-variable
name must be documented when implemented.

The following configuration combination is invalid and must fail before the application
serves requests:

```text
environment = production (or another production-class environment)
developer_mode = true
```

Likewise, a normal-mode deployment with no configured identity verifier must fail closed
for protected routes. It must not recover by accepting the repository's synthetic
claimant, staff, administrator, or integration credentials.

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
references, and provider-specific group structures stay inside the identity adapter.

`subject`, `actor_type`, `scopes`, `auth_source`, and `synthetic` are authoritative only
after server-side verification. Request bodies and browser state cannot override them.

## Roles and Minimum Scopes

The initial role-to-scope contract is intentionally narrow.

| Actor type | Minimum scopes | Primary boundary |
| --- | --- | --- |
| claimant | `claim:read:self`, `claim:write:self` | Own claimant-visible Claim State, sessions, messages, evidence, support requests, status |
| staff | `workbench:read`, `workbench:write` | Authorised internal claim/workbench projections and staff mutations |
| administrator | `admin:read`, `admin:write` | Separately contracted Control Plane configuration and audit surfaces |
| agent_service | `agent:execute` plus explicitly granted tool scopes | Claim-scoped orchestration only |
| integration_service | `tools:invoke` for an allow-listed integration operation | Narrow internal adapter routes |

Scopes are capabilities, not role aliases. A future staff principal may receive
`operations:read` without receiving administrator configuration authority. An
administrator does not automatically receive claimant or unrestricted production Claim
State editing authority.

The Admin API is not yet implemented. `admin:read` and `admin:write` define the identity
boundary that #209/#247 must preserve when that API is added; their presence here does
not make an Admin route current or production-ready.

## Client Entry-Point Boundaries

### Claimant client

- Accept only a claimant principal with self-scoped claim capabilities.
- Derive `customer_id` from the principal, never from a request body or browser field.
- Never expose staff/internal review material because a browser asks for a broader
  projection.

### Staff Workbench

- Accept only an authorised staff principal.
- Derive staff actor identity from the principal for assignment, decisions, handoff
  acceptance, write-back, and audit.
- A claimant or integration credential receives an access denial, not a downgraded
  claimant response from a Workbench route.

### Administration / Control Plane

- Accept only an administrator principal with the required Admin scope.
- Keep Admin routes separate from claimant and Workbench routes.
- Never return complete secret values or permit unrestricted direct Claim State editing.
- Until an Admin API exists, the absence of an Admin route is the correct behaviour; a
  synthetic admin principal does not create one implicitly.

## Synthetic Developer Principals

Developer mode provides a bounded replacement for a real identity provider during local
work and tests. It is not anonymous mode.

Each synthetic credential maps to exactly one registered principal profile, for example:

| Synthetic profile | Actor type | Example subject | Scope class |
| --- | --- | --- | --- |
| claimant fixture | claimant | `cus_demo` | claimant self-service only |
| staff fixture | staff | `stf_demo` | Workbench only |
| admin fixture | administrator | `adm_demo` | Admin only, once Admin routes exist |
| integration fixture | integration_service | `integration_fixture` | allow-listed internal tools only |

Requirements:

- credentials for different synthetic profiles must be pairwise distinct;
- an unknown bearer token is authentication failure, not a new synthetic user;
- a known token presented to another role boundary is access denied;
- the principal is marked `synthetic=true` and has a non-secret `auth_source` indicating
  developer mode;
- synthetic subjects and fixture data remain anonymous and must not resemble real
  customer credentials;
- production-class configuration rejects developer mode before serving requests.

Developer mode must not accept arbitrary `X-Role`, `X-User`, query-string, cookie, or
request-body values that manufacture a principal or add scopes.

## Authentication and Authorisation Order

For every protected request the server applies this order:

1. classify the route's required role/scope boundary;
2. obtain the presented credential through the configured authentication mechanism;
3. verify it using **normal** or explicit **developer** identity mode;
4. normalise the verified identity into the provider-neutral principal;
5. reject actor-type or scope mismatch before loading or mutating protected domain data;
6. enforce claim ownership/task authority at the application or repository boundary;
7. execute the operation using the principal subject as the actor/customer identity;
8. record the bounded audit result.

Authentication proves who the caller is. Scope and ownership checks still decide what
that caller may do. A valid staff credential therefore does not imply access to every
claim, and a valid claimant credential never substitutes a client-provided customer ID
for the principal subject.

## Failure Contract

| Condition | Result |
| --- | --- |
| Missing/invalid credential | `401 AUTHENTICATION_REQUIRED` |
| Valid credential for the wrong role/scope | `403 ACCESS_DENIED` |
| Valid claimant principal requesting another claimant's resource | `404` or `403` according to the current concealment contract; never return the other claim |
| Normal-mode identity verifier unavailable | Bounded authentication/dependency failure; no synthetic fallback |
| Developer mode requested in production-class environment | Startup/configuration failure before routes are served |
| Unknown synthetic credential in developer mode | `401 AUTHENTICATION_REQUIRED` |

Authentication failures must not echo token values, secret references, provider response
bodies, or unnecessary identity claims.

## Audit Contract

A successful or rejected protected request must be attributable without persisting the
credential itself. The audit boundary must be able to record at least:

```text
request_id
subject (when verified)
actor_type (when verified)
auth_source
synthetic
route or operation
required scope / authority boundary
outcome: authenticated | denied | failed
reason code
timestamp
```

Material domain writes continue to record their existing actor, reason, revision, source,
and outcome data. Identity audit augments that provenance; it does not replace claim
events or staff decision records.

Do not log bearer tokens, API keys, refresh tokens, complete provider claims, or raw
identity-provider responses by default.

## Current Implementation and Week 4 Gap

Current `main` already has useful prototype protections:

- claimant, staff, and integration synthetic tokens are pairwise distinct;
- claimant/staff/integration routes reject another synthetic role's credential;
- protected routes reject unknown or missing bearer tokens; and
- synthetic credentials are rejected when `NORTHWIND_ENVIRONMENT` is outside
  `development`/`test`.

Those behaviours remain valid evidence, but they are not yet the complete contract above.
The current implementation implicitly enables synthetic authentication whenever the
environment is `development` or `test`, has no administrator principal, and exposes no
scope/synthetic/auth-source metadata on `Principal`.

Issue #247 implements the next slice. It should introduce explicit developer-mode
selection, normalise the richer principal, add the administrator boundary needed by the
future Admin API, preserve the existing cross-role denial tests, add production startup
rejection, and make the synthetic marker available to audit without weakening current
claim ownership rules.

## Verification Inputs for #247 / #268

A repeatable implementation check should prove at least:

1. normal mode rejects all repository synthetic credentials;
2. developer mode accepts only registered synthetic profiles and preserves their fixed
   roles/scopes;
3. claimant, staff, admin, and integration credentials cannot cross role boundaries;
4. developer mode cannot start in production-class configuration;
5. no protected route trusts client-supplied identity/role/scope fields;
6. audit-visible principal metadata marks synthetic requests without storing the token;
7. existing claim ownership and claimant/internal projection tests remain green.

These checks establish an identity boundary. They do not constitute production IdP,
SSO, MFA, session-management, key-rotation, recovery, or compliance readiness.