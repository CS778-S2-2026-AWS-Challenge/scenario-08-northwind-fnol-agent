# Issue #1155: Workbench control inventory and verification

This record lists every Workbench control and route on one exact head, the result of exercising
each in a browser, the defects repaired with it, and the defects and questions routed to other
owners. It is Sprint 5 stage B evidence for #1155, #771, and #1066.

## Record summary

| Item | Value |
| --- | --- |
| Code head under test | The current PR head. `tests/browser/pr1170_workbench_inventory.cjs` runs in `p12-browser-evidence` on every head and writes the exact `PR_HEAD_SHA` into `pr1170-workbench-inventory-PASS.json` |
| First round | `main@eb51fc02`, 2026-10-01, independently re-verified by the #1140 owner on #1155 |
| Browser runs | The original full manual inventory was observed during development and the repair set was re-run manually at `f1e0d37b`. The current-head gate now reruns the Workbench in Playwright Chromium on every PR head, enumerates the committed inventory surfaces at 1440 and 390 px, and actively exercises presence renewal, own-vs-foreign revision notices, Take Claim, Claim decision, Staff Agent fail-closed behavior, tab scoping, the compact queue, and the phone-width Agent panel. The JSON artifact records the exact head |
| Date | 2026-10-02 |
| Data runtime | `DATA_RUNTIME_PROFILE=fixture`, `NORTHWIND_OBJECT_STORAGE_ADAPTER=fixture` |
| Agent runtime | `AGENT_RUNTIME_PROFILE=controlled`; no Staff Agent model is published |
| Identity | `NORTHWIND_IDENTITY_MODE=normal`, local SQLite staff store |
| Data | `POST /api/v1/workbench/demo/seed-scenarios`: AT-01, AT-02, AT-04, AT-05, AT-06, AT-10 |
| Accounts | Primary staff (`claims_professional`), second staff (`claims_professional`), operations (`operations`, no Workbench capability) |
| Viewports | 1440 x 900, 1024 x 768, and 390 x 844 |
| Evidence level | Integrated local runtime with fixture data and synthetic accounts; not production |

Injected failures are labelled as injected. A result that depends on Docker, a published model, or
another open issue is recorded as a limitation, not as a pass.

## Results at a glance

The source scan found 172 control definitions in `workbench/src`; a mapped list renders one
definition many times. The inventory groups them into 93 rows across 20 surfaces. The committed
classification below is reconciled with current `main`; the exact-head browser artifact records the
visible controls found on each exercised surface and the current-head mutation results.

| Result | Meaning | Rows |
| --- | --- | --- |
| `works` | Real route or API behaviour with honest feedback | 63 |
| `unreachable` | Present in code or projection but not reachable with the seeded data or current UI | 20 |
| `honest-unavailable` | Disabled or unavailable with a stated reason | 6 |
| `placeholder` | Visible control with no real effect | 3 |
| `defect` | Misleading behaviour that remains | 1 |

Rows marked `works` can still carry a routed finding in their observation, such as a raw staff ID
input or a duplicate accessible name.

## Repairs delivered with this record

Each repair has focused tests. `f1e0d37b` remains the manual repair baseline; the current PR head is also exercised automatically by `tests/browser/pr1170_workbench_inventory.cjs`, whose JSON artifact records the exact SHA.

| Finding | Repair | Commit | Tests | Browser evidence |
| --- | --- | --- | --- | --- |
| Own mutation raised "This Claim changed in another session" | Remember the revision returned by the staff member's own revision-checked mutation and suppress a notice at or below it; hold notices while that mutation is in flight | `33c4946d`, `f1e0d37b`, `6c132a3e` | `revision.test.js`; `WorkbenchPage.test.jsx` own-mutation, decision, Staff Agent, and in-flight cases | Manual baseline: AT-04 own send produced no notice and an out-of-band change produced a revision notice. Exact-head CI repeats the distinction with two Workbench pages: the current page's send is suppressed and the second page's send raises the external-change notice |
| Queue hidden at phone width; toggle label did not match | Compact layout shows the queue when no Claim is open; toggle name and `aria-expanded` follow the visible state and return to the queue | `1181774c` | `WorkbenchPage.test.jsx` phone-width case | 390 px: open Claim shows "Show Claim queue" (`aria-expanded=false`); toggle returns to `/workbench` with the queue visible |
| Header menu button hidden at every width with no action | Removed | `1181774c` | Not applicable | Not applicable |
| Collapsed rail controls had no accessible name | Explicit labels on Workbench, Claim conversations, Staff Agent | `105cc741` | `NavigationRail.test.jsx` | 1024 px: all four rail controls named |
| Unavailable composer collapsed to 40 px | Explicit grid placement for textarea and send button | `49ca5bd4` | Not applicable (layout) | 1024 px AT-02, sending unavailable: textarea 566 px wide |
| Staff Agent bubble could cover the end of content and messages | End space clears the bubble on layouts that show it | `18b31dc6` | Not applicable (layout) | 1024 px AT-04 Overview, Activity, Conversation scrolled to the end: no visible text intersects the bubble |
| Staff Agent panel did not take focus; Escape did nothing | Non-modal dialog: focus to message box, Tab contained, Escape closes Claim Scope (focus to its toggle) then the panel, focus returns to opener or bubble | `13447e9f`, `9ee2ae53` | `StaffAgent.test.jsx` dialog, bubble, embedded, and scope-Escape cases | 1024 px: Escape on a scope checkbox kept focus on the toggle; second Escape closed the panel and focused the rail button |
| Staff Agent sent and created a session with no available model | Readable reason from capabilities, applied independently of the session and Claim lists; a resumed session whose model is no longer published also fails closed | `13447e9f`, `9ee2ae53`, `6c132a3e` | `StaffAgent.test.jsx` unavailable, stale-model, reason, failed-list, and failed-capabilities cases | Manual baseline covered no-model and capabilities failure. Exact-head CI types into the unavailable composer, confirms Send stays disabled, and records that no Agent session/message POST occurred |
| Open Claim tabs leaked across staff accounts on one browser | Tabs stored per staff identity; former browser-wide record removed | `1b506b93` | `usePersistentTabs.test.jsx` privacy, identity switch, legacy cases | Primary account had four tabs; the operations account signed in next saw none |
| Staff Agent rail button did nothing at phone width | Open panel fills the content area; bubble stays hidden; no dragging | `823fa07b` | `StaffAgent.test.jsx` compact case | 390 px: panel 390 x 734, focus in message box, Escape returns focus to the rail button |
| Operations account told to "retry when the service is available" | Access denial explained without Retry | `80eaff92` | `WorkbenchPage.test.jsx` access-denied case | Operations account: "No Workbench access" without Retry |

`#1167` is now part of the PR's `main` base. The current Workbench renews the staff presence lease on session restore, every 120 seconds, window focus, and visibility return; it also wires `ownership.accept_claim`, Claim decision, and specific `STAFF_NOT_AVAILABLE` guidance. This PR does not own those implementations, but its exact-head browser gate exercises their Workbench-visible behavior.

## Findings routed to other owners

These remain routed findings after reconciling the inventory with current `main`. Items delivered by #1167 were removed from this table and are recorded above as current behavior.

| Finding | Evidence | Owner or follow-up |
| --- | --- | --- |
| Active pre-creation Claims, including urgent AT-04, are in no list | `WorkbenchPage.jsx` requests only `created_routed`, `incomplete_claims`, and unassigned `human_requests`; `view=urgent` returns AT-04 | Direction decided on #1155 by the #1140 owner: an `Active work` peer navigation item; implementation pending a separate issue |
| `work_item.create` is projected with no control | `onCreateAction` is passed to `ClaimWorkspace` but never used | Workbench owner under #771 |
| Invite coworker and Request transfer need a raw staff ID | Free-text "Staff ID to invite" and "Target staff ID"; `GET /workbench/staff/online` is unused | Workbench owner under #771 |
| Profile and notification settings write only to this browser | Save shows "Account-wide profile sync still requires backend support"; notification preferences affect nothing; display settings confirmation also says "Account sync still requires backend support" | Account settings owner (`46850f4d`); backend support under #769 |
| Staff composer offers attachments that cannot be sent | Attach control present; staff attachments are #1057 and #1058 | #1058 |
| Closing a Claim tab with Delete drops focus to `<body>` | Keyboard check on the open-claims tab list | Workbench owner under #771 |
| Four "Open" buttons in Supporting Claim context share one name | Accessible names are identical | Workbench owner under #771 |
| Signal titles show the internal ID | "Review Signal sig_at02_policy_cause" | Workbench owner under #771 |
| Realtime stream retries indefinitely after `403` | Operations account: about one `/realtime/events` request every 10 seconds | Workbench owner under #771 |
| MinIO image cannot be pulled | `minio/minio` and `minio/mc` on Docker Hub and `quay.io/minio/minio` refuse anonymous pulls; `docker compose up` fails on a new machine | Repository deployment owner; affects every new local environment |

## Open questions

| Question | Status |
| --- | --- |
| After a resolved handoff, `conversation.send_claimant_message` is no longer projected for the primary owner | Pending owner decision |
| Retention hold actions need a primary owner on a terminal Claim | Reachable only after #1167 lets staff take AT-10 |

## Control inventory

Each table lists the controls of one surface. "Source" names the API route, registered action,
client route, or client-local state behind the control.

### Sign-in

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Work email, Password | Signed out | Wrapped labels | `works` | Names come from wrapping `<label>` |
| Sign in | Signed out | `POST /api/v1/staff/auth/sessions` | `works` | Wrong credentials: "The email or password was not recognised." as an alert |

### Shell and navigation

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Workbench link | Signed in | Client route `/workbench` | `works` | Named in the collapsed rail after repair |
| Draft claims link and count | Signed in | Client route `/workbench/drafts`; count from `view_counts` | `works` | "0 Draft claims" |
| Claim conversations link | Signed in | Client route `/workbench/conversations` | `works` | Named after repair |
| Staff Agent button | Signed in | Opens the floating panel | `works` | Phone width repaired |
| Hide or Show Claim queue | Queue routes | Client-local; compact layout returns to the queue route | `works` | Name and `aria-expanded` match what is visible |
| Hide or Show conversation queue | Conversations routes | Client-local | `works` | Name and `aria-expanded` follow the state; hidden at 800 px and below by design |
| Refresh Workbench projection | Signed in | Reloads queue or conversations | `works` | One list request per click |
| Revision notice: Review the latest version, Dismiss | Another session changes the open Claim | Reloads detail | `works` | Out-of-band message by API raised "changed in another session (revision 10)"; Review reloaded and cleared it; not raised for the page's own mutation |
| Movement and decision notices: Dismiss | After a reopen or decision | Client-local | `unreachable` | No reopenable or decidable Claim in the seed |

### Account menu

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Account menu trigger | Signed in | Opens menu | `works` | Focus moves to the first item; arrow keys move; Escape returns focus |
| Profile, Account and Security, Notifications, Language and Display, Help and Feedback | Menu open | Client routes `/workbench/settings/*` | `works` | Items are named menu items |
| Sign out | Menu open | Confirmation, then `DELETE /api/v1/staff/auth/session` | `works` | Initial focus on Cancel; Claim tabs no longer leak to the next account |

### Claim queue

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Search claims | Queue available | `GET /workbench/claims?view=created_routed&search=` | `works` | URL keeps `search`; no-match state offers Clear filters |
| Filters | Queue available | Client-local disclosure | `works` | `aria-expanded` reflects state |
| Claim status, Claim priority, Staff tag | Filters open | Server filter metadata; list query parameters | `works` | Options come from `filter-metadata` |
| Clear filters | Filters applied or no match | Client route | `works` | Returns to unfiltered list |
| Claim card | Claims listed | Opens the Claim tab and route | `works` | Card shows reference, status, family, owner |
| Load more Claims | Next cursor present | Cursor pagination | `unreachable` | Seed has one created Claim |
| Refresh totals | Counts unavailable | Reloads counts | `unreachable` | Counts always available in the seed |
| Retry (list error) | List request failed | Reloads the list | `works` | Injected network failure: alert, "stale" marker, Retry recovers |
| Retry (metadata error) | Filter metadata failed | Reloads metadata | `works` | Access denial now shows no Retry |
| Queue view select | `onView` supplied | Server-published views | `unreachable` | Not supplied since #1143; see routed finding |

### Draft claims

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Draft queue and read-only detail | Incomplete Claims exist | `view=incomplete_claims`; read-only workspace | `unreachable` | Seed has no incomplete Claim; route-level tests from #1143 cover the read-only boundary |

### Claim tabs

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Claim tab | Claims opened | Client route; per-staff persisted state | `works` | ArrowRight moves focus and route; Delete closes the tab but focus falls to `<body>` |
| Close tab | Claims opened | Moves to a neighbour tab | `works` | Six tabs to five |
| Show all open claims and list items | Claims opened | Client-local list | `works` | `aria-expanded` true; picking an item routes to that Claim and closes the list |

### Claim workspace header and sections

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Record references | Claim open | Disclosure | `works` | Shows Claim and claimant references |
| Section tabs (8) | Claim open | Client routes `/workbench/claims/{id}/{section}` | `works` | Arrow keys move and route |
| Retry Claim, Refresh Claim | Detail failed or stale | Reloads detail | `works` | Injected AT-06 detail failure: "could not be opened"; Retry Claim loaded revision 3. Operations account sees "This Claim is not available" |
| Retry section | Section resource failed | Reloads that resource | `works` | Injected Evidence failure: "Showing saved records" notice; Retry restored three records |
| Retry external action context | External action recovery notice | Reloads external context | `unreachable` | No external task in the seed |

### Overview

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Review acceptance, Confirm Accept Claim | `human.accept_handoff` is primary | `POST .../handoffs/{id}/accept` with `If-Match` | `works` | AT-04 and AT-02: revision advanced, "Assigned to you" |
| Action details, Provide action details | Projected primary action | Disclosure and form | `works` | AT-10 now exposes `Review ownership` / `Take Claim`. Exact-head CI first forces unavailable presence and verifies the explicit failure, then restores availability and successfully assigns the Claim |
| Open work activity | Accepted handoff | Routes to Activity | `works` | AT-04 routed to `/activity` |
| Open (four) | Supporting Claim context | Routes to the matching section | `works` | Names are not unique; see routed finding |
| Source, gap, traceability, tag, and signal disclosures | Records present | Disclosures | `works` | Expanded; source, status, and freshness rendered |
| Show all gaps | More gaps than shown | Client-local | `unreachable` | No seeded Claim has more gaps than the summary shows |
| Refresh Claim | Projection stale | Reloads detail | `unreachable` | No stale projection occurred during the run |
| Review signals | Signals need review | Routes to Signals | `works` | AT-02 routed to `/signals` |

### Ownership actions

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Invite coworker | `ownership.invite_cowork` | `POST .../cowork-requests` | `works` | Revision 4 to 5; invitation visible in Activity; raw staff ID input |
| Request transfer | `ownership.request_transfer` | `POST .../transfer-requests` | `works` | Revision 5 to 6; raw staff ID input |
| Return to queue | `ownership.requeue` | `POST .../requeue` | `works` | AT-02 unassigned, revision 7 |
| Review cowork request | Second staff, pending invitation | `PATCH .../collaboration-requests/{id}` | `works` | Second staff became coworker; could message the claimant |
| Review transfer request | Second staff, pending transfer | `PATCH .../collaboration-requests/{id}` | `works` | Injected stale `If-Match: 2`: alert names revision 8 and keeps the selected decision; resubmission declined at revision 9 |

### Conversation

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Message to claimant, Send message | `conversation.send_claimant_message` | `POST .../messages` with readback | `works` | AT-04 and AT-05; no false revision notice |
| Unavailable notice | No send action | Projection | `honest-unavailable` | Composer keeps full width after repair |
| Use voice input, Cancel | Send available and supported | Browser speech recognition | `unreachable` | The automated browser has no microphone; component tests cover the states |
| Choose and Attach photos or files | Send available | Client-local preview | `placeholder` | Staff attachments cannot be sent; see routed finding |
| Take over conversation, Confirm take over | Queued handoff | `POST .../handoffs/{id}/accept` | `works` | #1167 renews presence during an active session. `STAFF_NOT_AVAILABLE` is now reported as a definite not-completed outcome rather than an unconfirmed side effect |

### Claim information

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| None | Not applicable | `GET .../fields` | `works` | Read-only fields with status and source |

### Evidence

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Evidence record disclosure | Evidence exists | `GET .../evidence` | `works` | Expanded; status, source, related fields, claimant note |
| View file | Completed evidence | `GET .../evidence/{id}/content-data` | `honest-unavailable` | Fixture storage has no bytes: "The evidence file is not available to view." |
| Open file link | Preview loaded | Browser-safe content URL | `unreachable` | Needs object storage (Docker) |

### Reference checks

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Policy and Claim history record disclosures | Retrievals exist | `GET .../retrievals` | `works` | AT-02: one policy and one history record with provenance |

### External services

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Capability disclosures | Capabilities projected | Claim detail `external_capabilities` | `works` | Purpose, required fields, disclosure, limitation rendered |
| Official information link | Capability has an official URL | External link with `rel="noreferrer"` | `works` | Opens in a new tab; external site not visited during the run |
| Request record disclosures, Review action, Confirm, Cancel | External requests exist | Registered external task actions | `unreachable` | No external request in the seed |

### Signals

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Signal disclosure | Signals exist | `GET .../signals` | `works` | Internal ID shown in title |
| Decision, Reason, Decision summary, Record decision | Primary owner with a projected decision | Signal decision action | `works` | Empty submit blocked by required fields; AT-02 signal recorded as Confirmed |
| No-decision notice | Non-owner | Projection | `honest-unavailable` | "No signal-decision action is projected for this signal." |

### Activity

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Review handoff context | Handoff present | Disclosure | `works` | Handoff packet rendered |
| Record resolution, Resolve handoff | Accepted handoff | `POST .../handoffs/{id}/resolve` | `works` | Required fields enforced; audit entries Handoff.Resolved and Customer Update.Recorded |
| Update action | Staff action exists | `PATCH .../staff-actions/{id}` | `unreachable` | No staff action can be created from the UI; see routed finding |
| Technical details | Audit entries | Disclosure | `works` | Expanded per audit entry |

### Claim decision and reopen

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Approve Claim, Reject Claim, explanation, confirmation | Primary owner, `claim.record_decision` available | `POST .../decisions` | `works` | Exact-head CI takes AT-10, continues review, exposes both decision controls, submits an approval with claimant-visible explanation, and waits for the authoritative `Claim approved` projection |
| Review reopen, Cancel, Reopen | `claim.reopen` available | `POST .../reopen` | `unreachable` | No abandoned or closed Claim in the seed |

### Conversations page

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Action needed, My conversations, Staff Agent tabs | Signed in | Client-local tabs over conversation lists | `works` | Arrow keys move between tabs |
| Conversation row | Conversations listed | Routes to `/workbench/conversations/{session}` | `works` | Opened AT-04 conversation |
| Take over, Confirm take over, Cancel | Unassigned human request | `POST .../handoffs/{id}/accept` | `works` | See presence routing |
| Search, Clear search, Previous, Next | Staff Agent sessions listed | Client-local over sessions | `unreachable` | No Staff Agent session can be created without a model |
| More open conversations menu | More open tabs than fit | Client-local menu | `unreachable` | Too few open conversations in the run |
| Open conversation tab, Close current conversation tab | Conversation opened | Client-local | `works` | Close returned to `/workbench/conversations` |
| Conversations (back) | Conversation opened | Client route to the list | `works` | Returned to `/workbench/conversations` |
| Open claim | Conversation opened | Routes to the Claim | `works` | Routed to `/workbench/claims/clm_fixture_at04/summary` |
| Refresh, Retry | Conversation detail stale or failed | Reloads | `unreachable` | No stale or failed conversation occurred during the run |

### Staff Agent

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Open Staff Agent bubble | Desktop, panel closed | Opens the panel | `works` | Hidden at phone width by design |
| Close Staff Agent | Panel open | Closes and returns focus | `works` | Escape also closes |
| Session, New session model, New | Panel open | `GET /workbench/agent/sessions`, capabilities | `works` | "No published model"; New shows "New conversation ready" |
| Claim Scope, Claim checkboxes, Done | Panel open | Client-local scope, up to five Claims | `works` | Two selected: "2 of 5", composer chip "2 Claims selected"; Escape closes the list and keeps focus on its toggle |
| Message Staff Agent, Send to Staff Agent | Panel open | `POST .../agent/sessions/{id}/messages` | `honest-unavailable` | No model published: notice shown, send disabled, no session created |
| Choose and Attach photos or files, Use voice input | Panel open | Client-local | `placeholder` | Attachments cannot be sent; send is blocked while attached |
| Copy, edit draft, Review action, Confirm and execute, Sources used | Agent answer with drafts | Registered draft execution | `unreachable` | Needs the `model_gateway` runtime |
| Dismiss Staff Agent error | After an Agent error | Client-local | `unreachable` | Sending is blocked before an error can occur in this environment |

### Account settings

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Settings navigation (5) | Settings route | Client routes | `works` | All five pages load |
| Settings Retry | Settings failed to load | Reloads settings | `unreachable` | Settings never failed during the run |
| Profile: avatar, name, email, phone, Save changes | Profile | Browser storage only | `defect` | Copy implies an account update; saved state stays in this browser; see routed finding |
| Security: Change password, Set up, Manage devices, Remove | Security | Identity provider not configured | `honest-unavailable` | Disabled with "no staff identity-provider endpoint is configured" |
| Notifications: three preferences, Save notifications | Notifications | Browser storage only | `placeholder` | No notification is ever sent |
| Language, time zone, date format, theme, Save display settings | Language and Display | Browser storage, applied immediately | `works` | Saved; confirmation includes development-process copy (see routed finding) |
| Usage guide, Contact administrator | Help and Feedback | No approved destination | `honest-unavailable` | Disabled with a reason |
| Feedback, Submit feedback | Help and Feedback | `POST /api/v1/staff/feedback` | `works` | "Thank you. Your feedback was submitted." |

## Mutation checks

| Mutation | Confirmation | Stale revision | Replay | Audit visible |
| --- | --- | --- | --- | --- |
| Accept handoff | Two-step | Covered by existing route tests | Round 1: after a `409`, the identical retry reused the idempotency key and succeeded once presence was restored | Activity |
| Resolve handoff | Form with required fields | Covered by existing route tests | Not exercised in the browser | Activity: Handoff.Resolved |
| Send claimant message | Send button | Covered by existing journey tests | Not exercised in the browser | Conversation timeline |
| Invite coworker, Request transfer | Expand, required reason | Not exercised in the browser | Not exercised in the browser | Activity |
| Decide collaboration request | Required decision | Injected stale `If-Match`: alert with current revision, input kept | Not exercised in the browser | Revision advanced |
| Return to queue | Required reason | Not exercised in the browser | Not exercised in the browser | Ownership became unassigned |
| Signal decision | Required decision, reason, summary | Not exercised in the browser on the final-head automation | Not exercised in the browser | Signal state Confirmed |
| Take Claim | Explicit confirmation | Route/component tests cover stale projection and ownership conflicts | Existing API/route tests cover idempotency; exact-head browser exercises unavailable then successful submission | Ownership readback shows the current staff member as primary owner |
| Claim decision | High-impact confirmation and claimant-visible explanation | Workbench tests cover stale revision and ambiguous readback | Workbench/API tests cover same-key retry and conflict behavior | Exact-head browser submits AT-10 approval and renders the authoritative decision summary |

## Excluded from the inventory

- Test files, test harnesses, and Storybook-style fixtures: none ship to staff.
- `ConfirmDialog` and `ReopenClaimDialog` internals are recorded with the action that opens them.

## Limitations

- Evidence bytes, MongoDB transactions, and MinIO were not exercised: the `local_mvp` stack needs
  MinIO, whose images could not be pulled on this machine.
- Staff Agent answers and draft execution need the `model_gateway` runtime and were not exercised.
- Presence renewal, Take Claim, Claim decisions, and `STAFF_NOT_AVAILABLE` handling are present in current `main` via #1167 and are covered by the exact-head browser gate. Retention-hold coverage remains limited to the projections and tests available in the seeded environment.
- A Workbench access policy that grants read without write could not be provisioned locally; the
  operations account covers the no-capability state, and the second staff account covers a
  non-owner with write capability.
- The Draft claims route was not reachable because the seed has no incomplete Claim.

## Reproduce the run

Start the fixture backend and the Workbench from the repository root, then seed the scenarios with
a signed-in staff token. For repeatable exact-head evidence, CI runs the browser inventory before
the other browser journeys so the demo seed starts from an empty queue.

`tests/browser/pr1170_workbench_inventory.cjs` writes `pr1170-workbench-inventory-PASS.json` plus screenshots under `browser-evidence/`. The JSON includes `head`, environment/profile fields, surface control snapshots, and mutation checks.

```powershell
$env:NORTHWIND_ENVIRONMENT = 'development'
$env:NORTHWIND_IDENTITY_MODE = 'normal'
$env:DATA_RUNTIME_PROFILE = 'fixture'
$env:NORTHWIND_OBJECT_STORAGE_ADAPTER = 'fixture'
$env:AGENT_RUNTIME_PROFILE = 'controlled'
$env:NORTHWIND_STAFF_BOOTSTRAP_EMAIL = 'YOUR-TEST-EMAIL'
$env:NORTHWIND_STAFF_BOOTSTRAP_PASSWORD = 'YOUR-TEST-PASSWORD'
py -3.12 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
npm run dev --prefix workbench -- --host 127.0.0.1 --port 5174
```

Additional synthetic accounts were created against the same local SQLite store with
`backend.services.admin_accounts.create_staff`.
