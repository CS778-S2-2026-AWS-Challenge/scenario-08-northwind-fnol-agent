# Claimant-to-Staff Messaging Journey

## Purpose

This document defines the repeatable claimant-to-staff message journey from claim intake through
handoff, staff reply, and claimant continuation. The shared claim, Workbench, handoff, and message
APIs remain authoritative; transient browser states do not create a second persisted message log.

## Message State Contract

| Message | Sender | Audience | Delivery states | Failure and retry | Agent suggestion |
|---|---|---|---|---|---|
| Claimant intake | Claimant | Shared claim conversation | `sending`, then persisted `delivered` | `failed_before_delivery`; retain text and reuse the same claim, turn, and client-message idempotency keys on `retrying` | Agent response is a separate persisted message, never attributed to the claimant |
| Claimant continuation during handoff | Claimant | Assigned or permitted staff through the shared claim | `sending`, then persisted `delivered` | `failed_before_delivery`; keep the draft and retry without creating a duplicate | No suggestion is silently sent |
| Staff reply | Authenticated staff member | Claimant | `sending`, then persisted `delivered` | `failed_before_delivery`; keep the text and reuse the same staff-message idempotency key on `retrying` | `not_requested`, `generating`, `suggested`, `accepted`, `edited`, `rejected`, or `failed`; every state remains internal until staff explicitly sends the composer text |
| Staff resolution update | Authenticated staff member | Claimant | Persisted customer update after the handoff mutation succeeds | API error leaves the handoff open and permits a current-revision retry | Internal result and Agent material never become claimant-visible automatically |
| System or handoff status | System | Claimant-safe or staff-only projection according to visibility | Handoff notification is `delivered` or `queued_locally`; the durable handoff remains available in either case | A notification retry cannot duplicate the durable handoff | Not applicable |

`MessageRecord.actor` is the durable sender and `MessageRecord.visibility` is the durable audience
boundary. A successful message API response means the message is durably stored and may be shown
as `Delivered`. Browser-only `sending`, `failed_before_delivery`, and `retrying` items must never be
returned as persisted history.

## Page and State Flow

1. The claimant starts or resumes a claim and sends an intake message.
2. The claimant client shows the pending sender, audience, and `Sending` state.
3. Success adds persisted claimant and Agent messages as `Delivered`. Failure retains the text,
   shows `Failed before delivery`, and offers a safe retry.
4. A support request creates a durable context-preserving handoff. Notification failure is shown as
   `queued_locally` without losing the Workbench queue item.
5. Staff open the same claim, review the communication and packet, and accept the handoff.
6. Staff may generate a controlled prototype suggestion. It is visibly internal, can be accepted
   for editing, edited, rejected, or fail, and cannot send itself.
7. Staff send the reviewed composer text. The Workbench shows `Sending`, `Delivered`, or
   `Failed before delivery`; retry reuses the original idempotency key.
8. The claimant refreshes or resumes, sees the persisted staff reply, and continues without
   re-entering confirmed facts. Resolving the handoff writes a separate claimant-safe next step.

## Repeatable Acceptance Check

### Preconditions

- Run the backend on `http://127.0.0.1:8000`, claimant client on port `8001`, and employee client on
  port `8002`.
- Use only synthetic fixture identities and start from an empty or documented demo queue.
- Keep browser developer tools available to simulate one failed request.

### Basic implementation-owner check

| Step | Action | Expected result | Result / checker / date |
|---|---|---|---|
| 1 | Send a claimant intake message | Pending item names claimant sender and staff audience; success becomes delivered | Automated component check passed, 2026-08-24 |
| 2 | Fail one claimant request, then retry | Text remains; failure is explicit; retry succeeds once with the same idempotency keys | Automated component check passed, 2026-08-24 |
| 3 | Request human support | Handoff carries saved context and appears in the Workbench | Existing API and component checks passed, 2026-08-24 |
| 4 | Accept the handoff and open customer chat | Persisted history identifies sender, claimant audience, and delivery | Existing API and Workbench checks passed, 2026-08-24 |
| 5 | Generate, use, edit, and reject a suggestion | State changes are visible and no suggestion sends itself | Automated Workbench interaction check passed, 2026-08-24 |
| 6 | Fail one staff reply, then retry | Failed bubble remains; retry uses the same key and produces one delivered message | Static state and API idempotency checks passed; manual failure simulation remains repeatable |
| 7 | Refresh or resume the claimant client | Staff reply appears and claimant can continue from current claim state | Existing component check passed, 2026-08-24 |
| 8 | Resolve the handoff | Claimant-safe continuation appears; internal reasoning stays staff-only | Existing API and visibility checks passed, 2026-08-24 |

### Independent repeat

A second team member repeats steps 1–8 against the same commit and records their name, date,
environment, result, and any differences below. Automated checks support but do not replace this
journey check.

- Commit: _Record here_
- Environment: _Record here_
- Implementation owner result: _Record here_
- Independent checker result: _Record here_
- Evidence (test output or screenshots): _Record here_

## Automated Checks

Run:

```text
./scripts/check.ps1 -SkipInstall
```

Focused checks are `customer/src/App.test.jsx`, `customer/src/EmployeeWorkbench.test.js`,
`tests/test_handoff_api.py`, `tests/test_staff_actions_api.py`, and
`tests/test_employee_workbench_static.py`.
