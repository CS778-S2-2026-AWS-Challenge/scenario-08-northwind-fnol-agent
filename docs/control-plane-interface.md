# First Control Plane Interface Contract

## Status and Purpose

This document defines the bounded information architecture and screen inventory for the
first Northwind Control Plane frontend deliverable. It is the interface input for issues
#250, #258, and #260; it does not claim that an Admin Console or Admin API is currently
implemented.

The first implementation slice covers navigation and honest capability status for
knowledge, model profiles, data runtime profiles, integrations, and publication history.
The final administrator roles, approval requirements, and publication transition
ownership remain dependent on issue #208. Until that contract is accepted, the role and
lifecycle descriptions below are provisional and must not be treated as approved
Northwind policy.

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

At the #240 baseline every screen is contract-only: there is no Admin Console or Admin
API on `main`. A later screen may be relabelled **Real** only when its consumer, API,
tests, and contract are implemented together.

| Route | Screen | Primary purpose | #240 baseline | First-release target | Dependency |
| --- | --- | --- | --- | --- | --- |
| `/admin` | Overview | Summarise active versions, draft work, validation failures, and unavailable capabilities | Planned | UI only | #250 shell; #258 data |
| `/admin/knowledge` | Knowledge sources | List source versions, metadata, ingestion state, and publication state | Planned | UI only | #211; #260 bounded view |
| `/admin/knowledge/:sourceId` | Knowledge source detail | Inspect safe metadata, parsing/chunk status, citation preview, validation, and version history | Planned | Unavailable | #211 |
| `/admin/models` | Model profiles | List provider-neutral endpoint type, capabilities, limits, secret-reference presence, and version state | Planned | UI only or Real for the selected #260 workflow | #204, #258, #260 |
| `/admin/models/:profileId` | Model profile detail | Read, edit, validate, and save a versioned model-profile draft | Planned | Candidate Real workflow | #204, #208, #258, #260 |
| `/admin/data-profiles` | Data runtime profiles | Show fixture, Cloudflare, MongoDB, and AWS profile status without implying mixed-provider fallback | Planned | UI only | #203, #212, #260 |
| `/admin/data-profiles/:profileId` | Data profile detail | Inspect capability, migration, deployment impact, validation, and version state | Planned | Unavailable | #203, #212 |
| `/admin/integrations` | Integrations | List bounded capability, latency, failure, and safe secret-reference status | Planned | UI only | #212, #260 |
| `/admin/integrations/:integrationId` | Integration detail | Inspect configuration metadata and run an authorised capability validation | Planned | Unavailable | #212 |
| `/admin/publications` | Publication history | Show version, actor, reason, validation evidence, effective time, previous version, and rollback target | Planned | UI only or Real when exposed by #258 | #208, #258 |
| `/admin/publications/:publicationId` | Publication detail | Inspect immutable publication and audit metadata; expose only authorised lifecycle actions | Planned | Unavailable | #208, #258, #215 |
| `/admin/agent-rules` | Agent rules | Future instructions, controlled rules, tool permissions, and feature settings | Planned | Planned | #213 |
| `/admin/evaluation` | Evaluation | Future scenario and version-linked evaluation results | Planned | Planned | #214 |
| `/admin/operations` | Operations | Future health, jobs, latency, error, token, and cost views | Planned | Planned | #214 |
| `/admin/access` | Access | Future role and permission administration | Planned | Planned | #208 and a confirmed identity contract |
| `/admin/audit` | Audit | Future restricted configuration audit search | Planned | Planned | #209, #214 |

Planned and unavailable screens remain navigable in the first shell so the boundary is
discoverable, but they must display this message or an equivalent explicit statement:

> Not implemented in this release. No configuration changes are available from this
> screen.

They must not show enabled save, validate, publish, withdraw, or rollback actions.

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

## Candidate First Real Workflow

The preferred #260 candidate is a provider-neutral model profile because the repository
already defines a model-gateway boundary in #204. This is a coordination recommendation,
not a schema decision. #258 and #260 owners must agree the first configuration type and
document it in the Admin API contract before implementation.

The smallest honest flow is:

```text
read current model-profile metadata and version
-> create or update a revision-checked draft
-> validate capability metadata and protected secret reference
-> save the draft
-> read its validation and publication state
```

This flow does not publish, roll back, contact a model endpoint directly from the
browser, or prove a production integration. If the backend selects a different first
configuration type, the same list/detail and state pattern applies and this document
must be updated with the agreed type.

## Provisional Publication Presentation

The interface follows the repository's current bounded lifecycle vocabulary:

```text
draft -> validate -> approve when required -> publish -> observe
      -> validation failed                     -> withdraw
                                                -> supersede
                                                -> roll back to an approved prior version
```

This diagram describes presentation needs only. #208 owns which roles may perform each
transition, which changes require approval, and whether withdrawal or rollback creates a
new immutable publication record. Until then, the UI must not enable those actions.

Publication and rollback views must retain version, actor, reason, validation evidence,
approver when required, effective time, previous version, rollback target, and result.
Rollback must never erase intervening history.

## Explicitly Unfinished First-Release Modules

The first release does not claim complete knowledge ingestion, provider switching,
integration connection testing, publication, rollback, Agent-rule management,
evaluation, operations, access management, or audit search. It must not use local-only
mock success messages to suggest those behaviours exist.

One configuration type may become **Real** through #258 and #260. All other types retain
their actual **UI only**, **Unavailable**, or **Planned** label until their API and tests
exist. A fixture capability is labelled `fixture`, never `configured` or `production`.

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
