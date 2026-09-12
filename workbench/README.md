# Northwind Claims Workbench

This React/Vite application is the componentised staff client. It replaces the legacy static
implementation under `employee/` progressively; the legacy files remain only until every required
capability has been migrated and verified.

## Local run

Install dependencies:

```powershell
npm ci --prefix workbench
```

For normal-mode local staff authentication, configure a persistent staff identity store and one
initial claims-professional account before starting the backend:

```powershell
$env:NORTHWIND_IDENTITY_MODE='normal'
$env:NORTHWIND_STAFF_IDENTITY_DB_PATH='.northwind-staff-identity.sqlite3'
$env:NORTHWIND_STAFF_BOOTSTRAP_EMAIL='claims@example.test'
$env:NORTHWIND_STAFF_BOOTSTRAP_PASSWORD='<a strong local password>'
$env:NORTHWIND_STAFF_BOOTSTRAP_DISPLAY_NAME='Claims Professional'
py -3.12 -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

The bootstrap values only create the account when the email is absent. Remove the password from
the process environment after provisioning; the database stores a salted scrypt hash, not the
plaintext password.

Start the client:

```powershell
npm run dev --prefix workbench
```

Open `http://127.0.0.1:5174/workbench/` (or the port printed by Vite). The client proxies `/api`
to `http://127.0.0.1:8000`. Supported deep links include `/workbench/claims/{claim_id}`,
`/workbench/conversations/{session_id}`, and `/workbench/agent/sessions/{session_id}`.

In explicit developer identity mode, the isolated fixture staff account is:

```text
staff.one@example.invalid
northwind-demo-staff
```

It is available only in development and test and is not a deployment credential.

## Current migration boundary

- The new client uses real staff login/session routes and never embeds the synthetic bearer token.
- Queue and Claim detail tags are rendered only from the backend Staff Tag Registry projection;
  the client uses backend tag codes for filtering and never activates a tag itself.
- The queue uses the backend cursor and bounded page size rather than slicing a local database
  mirror.
- Opening a Claim never accepts or changes it. Handoff acceptance and resolution remain explicit,
  revision-checked actions with separate internal results and claimant-safe updates.
- Claim tabs persist locally without opening duplicate contexts for one Claim.
- Claim details use overview, conversation, dynamic-field, evidence, reference, signal, and
  activity sections with progressive disclosure. Evidence file bytes are read only after an
  explicit staff request.
- Signal decisions and staff actions use the audited backend APIs. The client does not turn an
  Agent proposal or a risk signal into a business decision.
- Completed, abandoned, and closed queues come from server-published filter metadata and remain
  reachable when no active Claims exist. Terminal list/detail views retain their authoritative
  disposition context. Only the exact current `claim.reopen` action can return an abandoned or
  closed Claim to its server-projected active queue; the client reloads the Claim projection and
  reports the returned queue and revision.
- Staff Agent sessions are private to the authenticated staff identity and persist independently
  of Claim tabs. Every question explicitly attaches zero to five Claims; the client never infers
  scope from the current page. The Agent can use selected Claim context and authorised knowledge
  to provide advice and editable drafts, but it cannot execute a business action.
- Staff Agent turns require the configured model-gateway runtime. In controlled mode the API
  returns `503 DEPENDENCY_UNAVAILABLE` rather than fabricating an answer.

The legacy `employee/index.html` is now a redirect/deprecation shell. The accompanying
`employee/app.js` and `employee/styles.css` remain only as migration inventory until the final
acceptance checklist moves them to the external archive. Do not add new product functionality to
any legacy file.
