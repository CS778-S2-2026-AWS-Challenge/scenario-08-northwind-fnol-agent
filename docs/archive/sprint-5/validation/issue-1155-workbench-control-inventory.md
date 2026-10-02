# Issue #1155: Workbench control inventory and verification

This record lists every Workbench control and route on one exact head, the result of exercising
each in a browser, the defects repaired with it, and the defects and questions routed to other
owners. It is Sprint 5 stage B evidence for #1155, #771, and #1066.

## Record summary

| Item | Value |
| --- | --- |
| Code head under test | `943366f8`. Its `workbench/` and `backend/` trees are identical to `ae2e65bd` (`git diff ae2e65bd 943366f8 -- workbench backend` is empty). Later commits on the branch change only this record, its run file, and `docs/README.md` |
| First round | `main@eb51fc02`, 2026-10-01, independently re-verified by the #1140 owner on #1155 |
| Browser run | One manual run on `943366f8`, 2026-10-02 02:59:09 to 03:19:35 UTC, in the Chromium browser built into the Claude desktop app, with both servers started from a clean working tree at that commit. Each block records its start and finish from the page clock, which matched the backend HTTP `Date` header at the start and the finish. The run file was committed after the run finished. Observed values are in the [browser run record](issue-1155-workbench-browser-run-943366f8.json). Earlier runs, including the one on `ae2e65bd` whose finish time was not taken from a clock, are superseded |
| Date | 2026-10-02 |
| Data runtime | `DATA_RUNTIME_PROFILE=fixture`, `NORTHWIND_OBJECT_STORAGE_ADAPTER=fixture` |
| Agent runtime | `AGENT_RUNTIME_PROFILE=controlled`; no Staff Agent model is published |
| Identity | `NORTHWIND_IDENTITY_MODE=normal`, local SQLite staff store |
| Data | `POST /api/v1/workbench/demo/seed-scenarios`: AT-01, AT-02, AT-04, AT-05, AT-06, AT-10. Phase A used the first seed; phase B restarted the backend, reseeded, and rejected AT-10; phase C covered remaining clicks on the phase B data |
| Accounts | Primary staff (`claims_professional`), second staff (`claims_professional`), operations (`operations`, no Workbench capability) |
| Viewports | 1440 x 900, 1024 x 768, and 390 x 844 |
| Evidence level | Integrated local runtime with fixture data and synthetic accounts; not production |

Injected failures are labelled as injected. A result that depends on Docker, a published model, or
another open issue is recorded as a limitation, not as a pass.

## Results at a glance

The source scan found 172 control definitions in `workbench/src`; a mapped list renders one
definition many times. The inventory groups them into 94 rows across 20 surfaces. Every row was exercised on
`943366f8` unless its result is `unreachable`, which states why. Where a row names several controls, each
was clicked or submitted in the run.

| Result | Meaning | Rows |
| --- | --- | --- |
| `works` | Real route or API behaviour with honest feedback | 65 |
| `unreachable` | Present in code or projection but not reachable with the seeded data or current UI | 19 |
| `honest-unavailable` | Disabled or unavailable with a stated reason | 6 |
| `placeholder` | Visible control with no real effect | 3 |
| `defect` | Misleading behaviour that remains | 1 |

Rows marked `works` can still carry a routed finding in their observation, such as a raw staff ID
input or a duplicate accessible name.

## Repairs delivered with this record

Each repair has focused tests. The browser evidence column comes from the `943366f8` run.

| Finding | Repair | Commit | Tests | Browser evidence |
| --- | --- | --- | --- | --- |
| Own mutation raised "This Claim changed in another session" | Remember the revision produced by the staff member's own revision-checked mutation, including Claim decisions and Staff Agent execution, and hold notices while that mutation is in flight | `33c4946d`, `f1e0d37b`, `6c132a3e` | `revision.test.js`; `WorkbenchPage.test.jsx` own-mutation, decision, Staff Agent, and in-flight cases | AT-04 own send: no notice in 25 polls at 200 ms; out-of-band change raised revision 6 and Review cleared it; Take Claim, AT-10 approval and rejection, collaboration decisions, Return to queue, and a Conversations reply raised no notice |
| Queue hidden at phone width; toggle label did not match | Compact layout shows the queue when no Claim is open; toggle name and `aria-expanded` follow the visible state and return to the queue | `1181774c` | `WorkbenchPage.test.jsx` phone-width case | 390 px: an open Claim shows "Show Claim queue" (`aria-expanded=false`); the toggle returned to `/workbench` with the queue visible in 13 of 14 attempts. The first attempt from AT-04 Overview stayed on the Claim; see open questions |
| Header menu button hidden at every width with no action | Removed | `1181774c` | Not applicable | Not applicable |
| Collapsed rail controls had no accessible name | Explicit labels on Workbench, Claim conversations, Staff Agent | `105cc741` | `NavigationRail.test.jsx` | 1024 px: rail text hidden (`display: none`) and all five rail controls named |
| Unavailable composer collapsed to 40 px | Explicit grid placement for textarea and send button | `49ca5bd4` | Not applicable (layout) | 1024 px AT-06, sending unavailable: textarea 567 px wide |
| Staff Agent bubble could cover the end of content and messages | End space clears the bubble on layouts that show it | `18b31dc6` | Not applicable (layout) | 1024 px AT-04 Overview, Activity, Conversation scrolled to the end: no rendered text intersects the bubble (one visually hidden `.sr-only` node does) |
| Staff Agent panel did not take focus; Escape did nothing | Non-modal dialog: focus to message box, Tab contained, Escape closes Claim Scope (focus to its toggle) then the panel, focus returns to opener or bubble | `13447e9f`, `9ee2ae53` | `StaffAgent.test.jsx` dialog, bubble, embedded, and scope-Escape cases | 1440 px: rail opener put focus in the message box; Escape on a scope checkbox kept focus on the toggle; a second Escape closed the panel and focused the rail button; Done returned focus to the toggle; with the bubble focused before opening, Close returned focus to it |
| Staff Agent sent and created a session with no available model | Readable reason from capabilities, applied independently of the session and Claim lists; a session whose model is no longer published also fails closed | `13447e9f`, `9ee2ae53`, `6c132a3e` | `StaffAgent.test.jsx` unavailable, stale-model, reason, failed-list, and failed-capabilities cases | 1440 px: notice and disabled send with no published model; injected capabilities failure: "could not be checked" with send disabled. The stale-model case is covered by tests only |
| Open Claim tabs leaked across staff accounts on one browser | Tabs stored per staff identity; former browser-wide record removed | `1b506b93` | `usePersistentTabs.test.jsx` privacy, identity switch, legacy cases | The primary account had six tabs; the second and operations accounts signed in next saw none, and each account has its own storage key |
| Staff Agent rail button did nothing at phone width | Open panel fills the content area; bubble stays hidden; no dragging | `823fa07b` | `StaffAgent.test.jsx` compact case | 390 px: panel 390 x 734, focus in message box, Escape returns focus to the rail button |
| Operations account told to "retry when the service is available" | Access denial explained without Retry | `80eaff92` | `WorkbenchPage.test.jsx` access-denied case | Operations account: "No Workbench access" without Retry |

Issue #1167 is part of this PR's base and owns presence renewal, Take Claim, and Claim decisions. On `943366f8`, sign-in renewed presence to revision 4, Take over and handoff acceptance succeeded, and Take Claim assigned AT-10 at revision 9 in both phases. Phase A approved it at revision 10; phase B rejected it at revision 10.

## Findings routed to other owners

These findings are confirmed on `943366f8` unless the evidence says otherwise. Items delivered by #1167 are no longer listed.

| Finding | Evidence | Owner or follow-up |
| --- | --- | --- |
| Active pre-creation Claims, including urgent AT-04, are in no list | `WorkbenchPage.jsx` requests only `created_routed`, `incomplete_claims`, and unassigned `human_requests`; `view=urgent` returns AT-04 | Direction decided on #1155 by the #1140 owner: an `Active work` peer navigation item; implementation pending a separate issue |
| `work_item.create` is projected with no control | `onCreateAction` is passed to `ClaimWorkspace` but never used | Workbench owner under #771 |
| Invite coworker and Request transfer need a raw staff ID | Free-text "Staff ID to invite" and "Target staff ID"; `GET /workbench/staff/online` is unused | Workbench owner under #771 |
| Profile and notification settings write only to this browser | Save shows "Account-wide profile sync still requires backend support"; notification preferences affect nothing; display settings confirmation also says "Account sync still requires backend support" | Account settings owner (`46850f4d`); backend support under #769 |
| Staff composer offers attachments that cannot be sent | Attach control present; staff attachments are #1057 and #1058 | #1058 |
| Closing a Claim tab with Delete drops focus to `<body>` | Keyboard check on the open-claims tab list | Workbench owner under #771 |
| Focus drops to `<body>` after a collaboration decision or a Claim decision | The control that opened the form or confirmation is removed once the decision is recorded (AT-02 cowork acceptance; AT-10 rejection) | Workbench owner under #771; Claim decision controls came from #1167 |
| Four "Open" buttons in Supporting Claim context share one name | Accessible names are identical | Workbench owner under #771 |
| Signal titles show the internal ID | "Review Signal sig_at02_policy_cause" | Workbench owner under #771 |
| Realtime stream retries indefinitely after `403` | Operations account: about one `/realtime/events` request every 10 seconds (development run; not re-measured in this run) | Workbench owner under #771 |
| MinIO image cannot be pulled | `minio/minio` and `minio/mc` on Docker Hub and `quay.io/minio/minio` refuse anonymous pulls; `docker compose up` fails on a new machine | Repository deployment owner; affects every new local environment |
| The backend cannot start on Windows without `tzdata` | `backend/domain/temporal_resolution.py:22` calls `ZoneInfo('Pacific/Auckland')` at import; `tzdata` is not a declared dependency, so startup fails with `ZoneInfoNotFoundError` on Windows | Backend owner under #769 |
| A full page load of `/workbench` without a trailing slash shows the Vite base-path notice | The dev server base is `/workbench/`; in-app navigation is unaffected | Workbench owner under #771 |

## Open questions

| Question | Status |
| --- | --- |
| After a resolved handoff, `conversation.send_claimant_message` is no longer projected for the primary owner | Pending owner decision |
| Retention hold actions need a primary owner on a terminal Claim | Answered by the projection code: holds are offered only on abandoned or closed Claims. AT-10, owned and then approved (phase A) or rejected (phase B), projects none, and the seed has no abandoned or closed Claim |
| At 390 px the first queue toggle from AT-04 Overview stayed on the Claim | Seen once in this run and once in the earlier run on `ae2e65bd`; not reproduced in 12 later attempts, including two after the same viewport switch. Cause not identified; pending a reproduction outside the emulated viewport |

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
| Workbench link | Signed in | Client route `/workbench` | `works` | Clicked from Conversations: `/workbench`; named in the collapsed rail after repair |
| Draft claims link and count | Signed in | Client route `/workbench/drafts`; count from `view_counts` | `works` | "0 Draft claims"; clicked: `/workbench/drafts` |
| Claim conversations link | Signed in | Client route `/workbench/conversations` | `works` | Clicked: `/workbench/conversations`; named after repair |
| Staff Agent button | Signed in | Opens the floating panel | `works` | Phone width repaired |
| Hide or Show Claim queue | Queue routes | Client-local; compact layout returns to the queue route | `works` | 1440 px: hid and showed the queue with matching name and `aria-expanded`; 390 px: see repairs |
| Hide or Show conversation queue | Conversations routes | Client-local | `works` | Name and `aria-expanded` follow the state; hidden at 800 px and below by design |
| Refresh Workbench projection | Signed in | Reloads queue or conversations | `works` | One `view=created_routed` list request per click |
| Revision notice: Review the latest version, Dismiss | Another session changes the open Claim | Reloads detail | `works` | Out-of-band messages raised revision 6 on AT-04 and revision 9 on AT-02; Review reloaded and cleared one, Dismiss cleared the other; not raised for the page's own mutations |
| Decision notice and its Dismiss | After a Claim decision | Client-local | `works` | Phase A: "Claim NW-AT10-001 was approved and the authoritative projection is now shown at revision 10."; phase B: the same with "was rejected". Dismiss Claim decision notice cleared it both times |
| Movement notice: Dismiss | After a reopen | Client-local | `unreachable` | No abandoned or closed Claim in the seed |

### Account menu

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Account menu trigger | Signed in | Opens menu | `works` | Focus moves to the first item; arrow keys move; Escape returns focus |
| Profile, Account and Security, Notifications, Language and Display, Help and Feedback | Menu open | Client routes `/workbench/settings/*` | `works` | Items are named menu items; Notifications and Profile routed to their pages |
| Sign out | Menu open | Confirmation, then `DELETE /api/v1/staff/auth/session` | `works` | Initial focus on Cancel; the next account sees no Claim tabs |

### Claim queue

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Search claims | Queue available | `GET /workbench/claims?view=created_routed&search=` | `works` | URL keeps `search`; no-match state offers Clear filters |
| Filters | Queue available | Client-local disclosure | `works` | `aria-expanded` reflects state |
| Claim status, Claim priority, Staff tag | Filters open | Server filter metadata; list query parameters | `works` | Options come from `filter-metadata`; Claim status "Collecting" requested `workflow_state=collecting` and kept it in the URL |
| Clear filters | Filters applied or no match | Client route | `works` | Cleared the search no-match state and the status filter |
| Claim card | Claims listed | Opens the Claim tab and route | `works` | Clicked AT-10 card opened `/workbench/claims/clm_fixture_at10` |
| Load more Claims | Next cursor present | Cursor pagination | `unreachable` | Seed has one created Claim |
| Refresh totals | Counts unavailable | Reloads counts | `unreachable` | Counts always available in the seed |
| Retry (list error) | List request failed | Reloads the list | `works` | Injected network failure: alert, "stale" marker, Retry recovers |
| Retry (metadata error) | Filter metadata failed | Reloads metadata | `works` | Injected failure of every metadata request (the client retries once): "Claim queue unavailable" with Retry; Retry loaded the queue. Access denial shows no Retry |
| Queue view select | `onView` supplied | Server-published views | `unreachable` | Not supplied since #1143; see routed finding |

### Draft claims

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Draft queue and read-only detail | Incomplete Claims exist | `view=incomplete_claims`; read-only workspace | `unreachable` | Seed has no incomplete Claim; route-level tests from #1143 cover the read-only boundary |

### Claim tabs

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Claim tab | Claims opened | Client route; per-staff persisted state | `works` | ArrowRight moved focus and route to AT-06; Delete closed the tab but focus fell to `<body>` |
| Close tab | Claims opened | Moves to a neighbour tab | `works` | The close button took two tabs to one |
| Show all open claims and list items | Claims opened | Client-local list | `works` | `aria-expanded` true with six items; picking one routed to AT-01 and closed the list |

### Claim workspace header and sections

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Record references | Claim open | Disclosure | `works` | Shows Claim and claimant references |
| Section tabs (8) | Claim open | Client routes `/workbench/claims/{id}/{section}` | `works` | ArrowRight moved from Overview to Conversation and routed |
| Retry Claim | Detail failed | Reloads detail | `works` | Injected detail failure: "could not be opened"; Retry Claim loaded revision 3 |
| Retry section | Section resource failed | Reloads that resource | `works` | Injected Evidence failure showed the unavailable state; Retry section loaded three records |
| Retry external action context | External action recovery notice | Reloads external context | `unreachable` | No external task in the seed |

### Overview

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Review acceptance, Confirm Accept Claim | `human.accept_handoff` is primary | `POST .../handoffs/{id}/accept` with `If-Match` | `works` | AT-04 (both seeds, revision 3 to 4) and AT-02: "Assigned to you" |
| Review ownership, Take Claim | `ownership.accept_claim` is primary | `POST .../claims/{id}/accept` (#1167) | `works` | AT-10, both phases: confirmation "Take ownership of this Claim?" with initial focus on Cancel; Take Claim assigned the Claim at revision 9 |
| Open work activity | Accepted handoff | Routes to Activity | `works` | AT-02 routed to `/activity` |
| Open (four) | Supporting Claim context | Routes to the matching section | `works` | The second Open routed AT-02 to `/evidence`; names are not unique, see routed finding |
| Source, gap, traceability, tag, and signal disclosures | Records present | Disclosures | `works` | AT-02 Overview: 25 disclosures opened by click, including 18 source and 2 gap records |
| Show all gaps | More gaps than shown | Client-local | `unreachable` | No seeded Claim has more gaps than the summary shows |
| Refresh Claim | Projection stale | Reloads detail | `unreachable` | No stale projection occurred during the run |
| Review signals | Signals need review | Routes to Signals | `works` | AT-02 routed to `/signals` |

### Ownership actions

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Invite coworker | `ownership.invite_cowork` | `POST .../cowork-requests` | `works` | AT-02: revision 6 to 7; raw staff ID input |
| Request transfer | `ownership.request_transfer` | `POST .../transfer-requests` | `works` | AT-02: revision 7 to 8; raw staff ID input |
| Return to queue | `ownership.requeue` | `POST .../requeue` | `works` | AT-02: submit disabled until a reason is entered; unassigned at revision 12 |
| Review cowork request | Second staff, pending invitation | `PATCH .../collaboration-requests/{id}` | `works` | Second staff accepted at revision 9 to 10 with no confirmation step; focus then fell to `<body>` (routed) |
| Review transfer request | Second staff, pending transfer | `PATCH .../collaboration-requests/{id}` | `works` | Injected stale `If-Match: 2`: `409`, revision stayed 10 and Decline stayed selected; resubmission declined the transfer at revision 11. The message text was not captured |

### Conversation

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Message to claimant, Send message | `conversation.send_claimant_message` | `POST .../messages` with readback | `works` | AT-04 and AT-05; no false revision notice |
| Unavailable notice | No send action | Projection | `honest-unavailable` | AT-06 at 1024 px: "Staff messaging not available yet"; composer 567 px wide |
| Use voice input, Cancel | Send available and supported | Browser speech recognition | `unreachable` | The automated browser has no microphone; component tests cover the states |
| Choose and Attach photos or files | Send available | Client-local preview | `placeholder` | Staff attachments cannot be sent; see routed finding |
| Take over conversation, Confirm take over | Queued handoff | `POST .../handoffs/{id}/accept` | `works` | AT-05 taken over from Conversations; presence renewed by #1167 |

### Claim information

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| None | Not applicable | `GET .../fields` | `works` | AT-10: four fields with status and source |

### Evidence

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Evidence record disclosure | Evidence exists | `GET .../evidence` | `works` | AT-02: three evidence records opened by click |
| View file | Completed evidence | `GET .../evidence/{id}/content-data` | `honest-unavailable` | Fixture storage has no bytes: "The evidence file is not available to view." |
| Open file link | Preview loaded | Browser-safe content URL | `unreachable` | Needs object storage (Docker) |

### Reference checks

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Policy and Claim history record disclosures | Retrievals exist | `GET .../retrievals` | `works` | AT-02: policy `POL-MVP-HOME-2048` and Claim history `HIST-MVP-2024-017` opened by click |

### External services

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Capability disclosures | Capabilities projected | Claim detail `external_capabilities` | `works` | AT-02: two capability disclosures opened by click |
| Official information link | Capability has an official URL | External link | `works` | `target="_blank"`, `rel="noreferrer"`; the external site was not visited |
| Request record disclosures, Review action, Confirm, Cancel | External requests exist | Registered external task actions | `unreachable` | No external request in the seed |

### Signals

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Signal disclosure | Signals exist | `GET .../signals` | `works` | AT-02: two signals opened by click; internal ID shown in title |
| Decision, Reason, Decision summary, Record decision | Primary owner with a projected decision | Signal decision action | `works` | AT-02 `sig_at02_policy_cause` recorded as Confirmed |
| No-decision notice | Non-owner or coworker | Projection | `honest-unavailable` | Second staff (coworker): "No signal-decision action is projected for this signal." for both AT-02 signals |

### Activity

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Review handoff context | Accepted handoff | Disclosure | `works` | AT-04 Activity after acceptance: opened, showing reason, priority, and incident |
| Record resolution, Resolve handoff | Accepted handoff | `POST .../handoffs/{id}/resolve` | `works` | AT-04: empty submit blocked; resolved at revision 7 with a Handoff.Resolved audit entry |
| Update action | Staff action exists | `PATCH .../staff-actions/{id}` | `unreachable` | No staff action can be created from the UI; see routed finding |
| Technical details | Audit entries | Disclosure | `works` | AT-02 Activity: seven disclosures opened by click |

### Claim decision and reopen

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Approve Claim, Reject Claim, explanation, confirmation | Primary owner, `claim.record_decision` available | `POST .../decisions` (#1167) | `works` | AT-10 after Continue review: both controls shown. Phase A: Approve opened a confirmation with initial focus on Cancel and an optional explanation; approved at revision 10. Phase B: Reject opened a confirmation with initial focus on Cancel; an empty explanation was refused with "Enter a public rejection explanation."; rejected at revision 10. Afterwards the Overview shows "Claim rejected", no decision controls remain, and focus is on `<body>` (routed) |
| Review reopen, Cancel, Reopen | `claim.reopen` available | `POST .../reopen` | `unreachable` | No abandoned or closed Claim in the seed |

### Conversations page

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Action needed, My conversations, Staff Agent tabs | Signed in | Client-local tabs over conversation lists | `works` | ArrowRight moved to My conversations |
| Conversation row | Conversations listed | Routes to `/workbench/conversations/{session}` | `works` | Opened the AT-05 conversation |
| Take over, Confirm take over | Unassigned human request | `POST .../handoffs/{id}/accept` | `works` | AT-05 taken over; a reply was delivered with no false notice |
| Search, Clear search, Previous, Next | Staff Agent sessions listed | Client-local over sessions | `unreachable` | No Staff Agent session can be created without a model |
| More open conversations menu | More open tabs than fit | Client-local menu | `unreachable` | Too few open conversations in the run |
| Open conversation tab, Close current conversation tab | Conversation opened | Client-local | `works` | Close returned to `/workbench/conversations` |
| Conversations (back) | Compact layout, conversation opened | Client route to the list | `works` | Hidden at 1440 px by design; at 390 px it returned to `/workbench/conversations` |
| Open claim | Conversation opened | Routes to the Claim | `works` | Routed to `/workbench/claims/clm_fixture_at05/summary` |
| Refresh, Retry | Conversation detail stale or failed | Reloads | `unreachable` | No stale or failed conversation occurred during the run |

### Staff Agent

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Open Staff Agent bubble | Desktop, panel closed | Opens the panel | `works` | Focus moved to the message box; hidden at phone width by design |
| Close Staff Agent | Panel open | Closes and returns focus | `works` | Returned focus to the bubble when the bubble had focus before opening; Escape also closes |
| Session, New session model, New | Panel open | `GET /workbench/agent/sessions`, capabilities | `works` | "No published model"; New shows "New conversation ready" |
| Claim Scope, Claim checkboxes, Done | Panel open | Client-local scope, up to five Claims | `works` | Two selected: "2 of 5"; Escape and Done close the list and keep focus on its toggle |
| Message Staff Agent, Send to Staff Agent | Panel open | `POST .../agent/sessions/{id}/messages` | `honest-unavailable` | No model published: notice shown, send disabled, no session created |
| Choose and Attach photos or files, Use voice input | Panel open | Client-local | `placeholder` | Attachments cannot be sent; send is blocked while attached |
| Copy, edit draft, Review action, Confirm and execute, Sources used | Agent answer with drafts | Registered draft execution | `unreachable` | Needs the `model_gateway` runtime |
| Dismiss Staff Agent error | After an Agent error | Client-local | `unreachable` | Sending is blocked before an error can occur in this environment |

### Account settings

| Control | Appears when | Behaviour and source | Result | Observation |
| --- | --- | --- | --- | --- |
| Settings navigation (5) | Settings route | Client routes | `works` | All five links routed |
| Settings Retry | Settings failed to load | Reloads settings | `unreachable` | Settings never failed during the run |
| Profile: avatar, name, email, phone, Save changes | Profile | Browser storage only | `defect` | Copy implies an account update; saved state stays in this browser; see routed finding |
| Security: Change password, Set up, Manage devices, Remove | Security | Identity provider not configured | `honest-unavailable` | Disabled with "no staff identity-provider endpoint is configured" |
| Notifications: three preferences, Save notifications | Notifications | Browser storage only | `placeholder` | No notification is ever sent |
| Language, time zone, date format, theme, Save display settings | Language and Display | Browser storage, applied immediately | `works` | Time zone changed to UTC and saved; confirmation includes development-process copy (see routed finding) |
| Usage guide, Contact administrator | Help and Feedback | No approved destination | `honest-unavailable` | Disabled with a reason |
| Feedback, Submit feedback | Help and Feedback | `POST /api/v1/staff/feedback` | `works` | "Thank you. Your feedback was submitted." |

## Mutation checks

| Mutation | Confirmation | Stale revision | Replay | Audit visible |
| --- | --- | --- | --- | --- |
| Accept handoff | Two-step | Covered by existing route tests | Covered by existing route tests | Activity |
| Resolve handoff | Form with required fields | Covered by existing route tests | Not exercised in the browser | Activity: Handoff.Resolved |
| Send claimant message | Send button | Covered by existing journey tests | Not exercised in the browser | Conversation timeline |
| Invite coworker, Request transfer | Expand, required reason | Not exercised in the browser | Not exercised in the browser | Activity |
| Decide collaboration request | Required decision, no confirmation step | Injected stale `If-Match`: `409`, revision unchanged, selection kept | Not exercised in the browser | Revision advanced |
| Return to queue | Required reason | Not exercised in the browser | Not exercised in the browser | Ownership became unassigned |
| Signal decision | Required decision, reason, summary | Not exercised in the browser | Not exercised in the browser | Signal state Confirmed |
| Take Claim | Explicit confirmation | Route and component tests cover stale projection and ownership conflicts | API and route tests cover idempotency | Browser on `943366f8`: AT-10 assigned to the current staff member at revision 9 in both phases |
| Claim decision | High-impact confirmation with optional claimant-visible explanation | Workbench tests cover stale revision and ambiguous readback | Workbench and API tests cover same-key retry and conflict | Browser on `943366f8`: AT-10 approval (phase A) and rejection (phase B) at revision 10; empty rejection explanation refused |

## Excluded from the inventory

- Test files, test harnesses, and Storybook-style fixtures: none ship to staff.
- `ConfirmDialog` and `ReopenClaimDialog` internals are recorded with the action that opens them.

## Limitations

- Evidence bytes, MongoDB transactions, and MinIO were not exercised: the `local_mvp` stack needs
  MinIO, whose images could not be pulled on this machine.
- Staff Agent answers and draft execution need the `model_gateway` runtime and were not exercised.
- Presence renewal, Take Claim, and Claim decisions come from #1167 and were exercised on `943366f8`.
  Retention holds are projected only for abandoned or closed Claims, which the seed does not contain.
- A Workbench access policy that grants read without write could not be provisioned locally; the
  operations account covers the no-capability state, and the second staff account covers a
  non-owner with write capability.
- The Draft claims route was not reachable because the seed has no incomplete Claim.

## Reproduce the run

Start the fixture backend and the Workbench from the repository root, open `/workbench/` with a
trailing slash, sign in, and seed the scenarios with the signed-in staff token. On Windows, install
`tzdata` first (see routed findings).

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
