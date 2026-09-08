# First Control Plane Interface Contract

## Status and Purpose

This document defines the bounded information architecture and screen inventory for the
Northwind Control Plane frontend and its backend projection boundary. The implemented Admin
Console and Admin API use this inventory together with `docs/control-plane-governance.md`.

## Boundary

- The Control Plane is a system-administration surface, separate from the claimant
  application and Staff Workbench in routes, identity, permissions, and API access.
- A future browser implementation calls only an authenticated Admin API. It never
  connects directly to a database, object store, vector index, model endpoint, or secret
  manager.
- The Control Plane manages versioned configuration and knowledge. It does not provide
  unrestricted editing of production Claim State or a back door into Workbench actions.
- Secret values and raw provider payloads are never displayed. Screens may show only
  protected secret references, safe capability metadata, and bounded connection results.
- Fixture, configured, degraded, unavailable, and pending-confirmation capabilities stay
  distinguishable. Fixture success is not evidence of a production integration.
- The first frontend should be an independently served Admin Console rather than a route
  added to `employee/index.html`. Its exact directory and build setup are owned by #250.

## Roles and Provisional Permissions

The final role names and approval policy are owned by #208. The interface needs these
capability boundaries without assuming that one person receives every capability.

| Capability | Minimum interface responsibility |
| --- | --- |
| System administration | Inspect configuration and capability status; create or update an authorised draft |
| Knowledge management | Manage knowledge source metadata, ingestion, retrieval tests, and candidate versions |
| Publication approval | Approve and publish only configuration types allowed by the final approval policy |
| Restricted audit | Inspect actor, action, reason, target, result, and time without secret or customer-data disclosure |
| Claims operations | No Control Plane configuration authority; use the separate Staff Workbench |

Unauthenticated users and users without the required administration scope receive an
access-denied screen. Hiding a navigation item is not an authorisation control; the Admin
API must independently reject the request without changing active state.

## Navigation and Screen Inventory

Implementation status uses the following exact labels:

- **Real**: connected to the Admin API and backed by tested server-side behaviour.
- **UI only**: usable navigation or presentation with no persisted management action.
- **Unavailable**: visible dependency or capability is not configured or implemented.
- **Planned**: outside the first implementation slice; no working behaviour is implied.

The following routes are connected to the authenticated Admin API. A route is **Real** only for
the actions stated in this table; an adjacent operation not listed here remains unavailable.

| Route | Screen | Server-backed behaviour | Status |
| --- | --- | --- | --- |
| `/admin` | Overview | Navigate to the authenticated Control Plane resource areas | Real |
| `/admin/configurations` | Configurations | Filter, create drafts, edit, validate, record an independent decision, publish, withdraw, and roll back using server-projected actions | Real |
| `/admin/releases` | Release Sets | Create, validate, publish, and roll back complete version-pinned Runtime releases | Real |
| `/admin/runtime` | Runtime Snapshot | Resolve the active Release Set for an explicit environment and runtime profile | Real |
| `/admin/knowledge` | Knowledge | Create source versions, ingest, validate, run retrieval checks, publish, withdraw, and inspect safe metadata | Real |
| `/admin/evaluations` | Evaluations | Filter and create immutable version-linked evaluation evidence | Real |
| `/admin/operations` | Operations | Filter durable operations and inspect model usage, estimated cost, rate-limit state, and configured alerts | Real |
| `/admin/integrations` | Integrations | Inspect registered capabilities, run bounded health checks, and read persisted health history | Real |
| `/admin/audit` | Audit | Filter restricted cross-resource audit projections | Real |
| `/admin/customers` | Customers | Create, read, revision-check updates, and revoke active sessions through the claimant identity repository | Real |
| `/admin/staff` | Staff | Create, read, revision-check updates, manage registered roles, and revoke active sessions through the staff identity repository | Real |

Model, data-profile, Agent-rule, feature, and access records use the common configuration screen
and their closed backend schemas. Account credential creation and session revocation stay inside
the authenticated identity API boundary; the console never receives password hashes, token hashes,
or bearer credentials. It does not edit Claim State or contact a provider business operation.

## Shared Screen States

Every implemented route defines and exposes the states that apply to it:

| State | Required presentation |
| --- | --- |
| Loading | Named operation and non-blocking progress indication |
| Empty | Explain that no records exist; do not present absence as an error |
| Error | Safe error summary, request identifier when available, and an applicable retry |
| Unauthorised | Access-denied heading with no restricted record or navigation leakage |
| Unavailable | Bounded cause and required dependency or follow-up action |
| Stale revision | Preserve user input and offer a safe refresh of current metadata |
| Validation failed | Show bounded field or capability evidence; do not enable publication |
| Validated | Identify the validated draft version and evidence metadata |
| Published | Identify the immutable active version and effective time |
| Withdrawn or superseded | Preserve version history and distinguish it from the active version |
| Rollback available | Identify the permitted target without implying that rollback has occurred |

Loading, error, validation, and status announcements must be programmatically exposed.
All navigation and actions must work with a keyboard and have visible focus.

## Configuration List and Detail Pattern

Knowledge, models, data profiles, and integrations use one predictable pattern:

1. A list shows name, type, safe capability summary, active version, draft version,
   validation status, publication state, and last safe update metadata.
2. A detail header identifies the configuration type, identifier, current active version,
   implementation label, and unavailable dependency when applicable.
3. Read-only active configuration is visually separate from an editable draft.
4. Editing uses an explicit revision boundary and preserves input after a stale-revision
   or validation error.
5. Validation reports bounded evidence without returning credentials or raw provider
   payloads.
6. Saving a draft does not imply validation, approval, or publication.
7. Publication history remains visible after withdrawal, supersession, or rollback.

## Implemented configuration workflow

The console uses one backend-owned workflow for model, data-profile, Agent-rule, feature,
Integration, access, and other registered configuration domains:

```text
read current projection and allowed actions
-> create or update a revision-checked draft
-> validate the exact revision
-> record an independent decision when the backend requires one
-> publish, withdraw, or roll back through the projected action
-> reload the authoritative server projection
```

The browser never contacts a model endpoint, object store, provider, or secret manager directly.

## Provisional Publication Presentation

The interface follows the repository's current bounded lifecycle vocabulary:

```text
draft -> validate -> approve when required -> publish -> observe
      -> validation failed                     -> withdraw
                                                -> supersede
                                                -> roll back to an approved prior version
```

The authenticated Admin API enforces which roles may perform each transition, records approval
decisions, and preserves immutable publication history. The console renders only the action codes
and availability projected by that API, requires confirmation when the projection says so, sends
the projected revision in `If-Match`, and reloads server state after the mutation.

Publication and rollback views must retain version, actor, reason, validation evidence,
approver when required, effective time, previous version, rollback target, and result.
Rollback must never erase intervening history.

## Current implementation boundary

The current Admin Console provides real API-backed workflows for configuration and knowledge
lifecycle actions, Release Sets, Runtime Snapshot resolution, evaluation evidence, operation
metrics, Integration health, restricted audit search, and customer/staff account creation,
revision-checked updates, and active-session revocation. The
backend derives every visible action from persisted state, revision, approval evidence, and the
authenticated principal. Consequential actions require explicit confirmation in the console and
are revalidated by the mutation endpoint.

The Operations view reads persisted model-call records and the active published operational
configuration. It distinguishes reported from unreported usage, configured from partial or
unconfigured cost, and clear from limited or unconfigured rate-limit state. Cost remains an
estimate, and incomplete usage or price data remains visible rather than being treated as zero.
Production provider secret-manager verification remains deployment-specific; the interface must
not imply that it is available.

Each capability retains its actual **Real**, **UI only**, **Unavailable**, or **Planned** label
based on the API and UI evidence that exists. A fixture capability is labelled `fixture`, never
`configured` or `production`.

## Repeatable Acceptance Checks

The implementation owner records the exact commit and command results. A non-author can
repeat the #240 document acceptance from the repository root:

```powershell
git diff --check
rg -n '^\| `/admin' docs/control-plane-interface.md
rg -n '\*\*(Real|UI only|Unavailable|Planned)\*\*' docs/control-plane-interface.md
rg -n 'Knowledge sources|Model profiles|Data runtime profiles|Integrations|Publication history' docs/control-plane-interface.md
rg -n 'database|object store|vector index|model endpoint|secret manager' docs/control-plane-interface.md
rg -n 'production Claim State' docs/control-plane-interface.md
```

Expected results:

- `git diff --check` exits zero.
- The route command lists the bounded Admin Console screens.
- The status command finds the four implementation-status definitions and honest status
  rules.
- The domain command finds all five required interface areas.
- The boundary commands find both the provider-access prohibition and Claim State
  administration prohibition.

Before review is requested, record the focused checks above and confirm that the configured
CircleCI documentation and pull-request policy checks pass against the exact pull-request head.

### #240 implementation record

- Date: 2026-08-26 (Pacific/Auckland)
- Branch: `docs/issue-240-control-plane-interface`
- Synchronized base: `origin/main@3a2c172821092318b23858f6be05b3d9b91d9e4b`.
- `git diff --check`: passed.
- The five `rg` acceptance commands above: passed; 16 bounded Admin routes and all five
  required interface areas were found.
- `pwsh -NoProfile -Command 'Set-Alias python /private/tmp/pr303-venv/bin/python; &
  ./scripts/check.ps1'`: passed using an isolated Python virtual environment. Result: PASS.
- Complete gate result: Ruff format and lint passed; mypy passed for 129 source files;
  466 backend tests passed with 90.03% coverage; 21 repository-policy tests passed;
  15 GitHub-automation tests passed; 31 customer tests passed; and the customer production
  build passed.

## Dependencies and Follow-up Ownership

- #208 owns final roles, transition authority, and approval policy.
- #250 owns the separate Admin Console shell, identity states, navigation, and accessible
  loading, empty, error, and unavailable presentation.
- #258 owns the authenticated versioned Admin API slice and safe audit metadata.
- #260 owns the first real read-edit-validate-save frontend workflow.
- #211-#215 retain the broader knowledge, provider, rule, operations, publication,
  rollback, and end-to-end acceptance scope.
