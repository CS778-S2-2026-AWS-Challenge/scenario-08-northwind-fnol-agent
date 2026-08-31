# Claimant-to-Staff Messaging Journey

## Purpose

This document defines the repeatable claimant-to-staff message journey from claim intake through
handoff, staff reply, and claimant continuation. The shared claim, Workbench, handoff, and message
APIs remain authoritative; transient browser states do not create a second persisted message log.

## Message State Contract

| Message | Sender | Audience | Delivery states | Failure and retry | Staff draft |
| --- | --- | --- | --- | --- | --- |
| Claimant intake | Claimant | Shared claim conversation | `sending`, then persisted `delivered` | A known rejection is `rejected_before_delivery`; a lost response is `delivery_outcome_unknown`. Retain text and reuse the same claim, turn, and client-message idempotency keys on `retrying` so replay reconciles a committed message. | Agent response is a separate persisted message, never attributed to the claimant |
| Claimant continuation during handoff | Claimant | Assigned staff through the shared claim | `sending`, then persisted `delivered` | Keep the draft and retry with the same identifiers. Do not claim non-delivery when a network failure leaves the outcome unknown. | No draft is silently sent |
| Staff reply | Authenticated staff member assigned to the accepted handoff | Claimant | `sending`, then persisted `delivered` | A known rejection is `rejected_before_delivery`; a lost response is `delivery_outcome_unknown`. Keep the text and reuse the same staff-message idempotency key on `retrying`. | The current prototype offers a deterministic reply template, not Agent or AI generation. Template states remain internal until staff explicitly sends the composer text. |
| Staff resolution update | Authenticated staff member | Claimant | Persisted customer update after the handoff mutation succeeds | API error leaves the handoff open and permits a current-revision retry | Internal result and Agent material never become claimant-visible automatically |
| System or handoff status | System | Claimant-safe or staff-only projection according to visibility | Handoff notification is `delivered` or `queued_locally`; the durable handoff remains available in either case | A notification retry cannot duplicate the durable handoff | Not applicable |

`MessageRecord.actor` is the durable sender and `MessageRecord.visibility` is the durable audience
boundary. A successful message API response or same-key replay means the message is durably stored
in the in-app conversation and may be shown as `Delivered`; it does not mean email, SMS, or push
delivery. Browser-only `sending`, `rejected_before_delivery`, `delivery_outcome_unknown`, and
`retrying` items must never be returned as persisted history.

## Page and State Flow

The journey can be read as a simple conversation moving between two screens:

1. On the claimant website, the claimant starts a claim and sends a message.
2. While the message is being sent, the claimant sees `Sending` beside their message.
3. If sending succeeds, the message changes to `Delivered`. If it fails, the claimant keeps the
   text and sees a retry button instead of having to type it again.
4. When the claimant asks for a person, the saved claim and conversation are placed in the staff
   Workbench queue. The claim is not lost if only the notification fails.
5. On the employee website, a staff member opens that claim, reads the saved information, and
   accepts the handoff.
6. Staff may build a deterministic reply template from the claimant-safe next step. It is clearly
   marked as internal: staff can use it, change it, or reject it, but it is never sent automatically.
7. Staff review the final wording and click send. A failed reply stays visible and can be retried
   without creating two copies of the same message.
8. Back on the claimant website, the claimant refreshes or resumes the claim, reads the staff
   reply, and continues from the saved point without completing the form again.

## Repeatable Acceptance Check

### Preconditions

- Run the backend on `http://127.0.0.1:8000`, claimant client on port `8001`, and employee client on
  port `8002`.
- Use only synthetic fixture identities and start from an empty or documented demo queue.
- Keep browser developer tools available to simulate one failed request.

### Basic implementation-owner check

Follow the rows in order and use one test claim throughout. “Customer page” means the claimant
website on port `8001`; “employee page” means the Workbench on port `8002`.

| Step | Where and what to do | What you should see | Result / checker / date |
| --- | --- | --- | --- |
| 1 | Customer page: start a claim and send a message | The message briefly shows `Sending`, identifies the claimant as sender, and then shows `Delivered` | Automated component check passed, 2026-08-24 |
| 2 | Customer page: use browser developer tools to drop one response after the server accepts the message, then select retry | The original text remains visible as `Delivery outcome unknown`; retry uses the same safe request keys, discovers the saved result, and shows only one delivered message | Automated component check passed, 2026-08-25 |
| 3 | Customer page: ask for help from a staff member | The page confirms that the claim was handed to staff; the same claim appears in the employee queue with its saved details | Existing API and component checks passed, 2026-08-24 |
| 4 | Employee page: open the new claim, accept it, and open the customer conversation | Staff can see who sent each saved message, who can read it, and whether it was delivered | Existing API and Workbench checks passed, 2026-08-24 |
| 5 | Employee page: build a reply template; try use, edit, and reject | Each template state is shown. The UI does not claim AI generation, and nothing reaches the claimant until staff deliberately click the normal send button | Automated Workbench interaction check passed, 2026-08-24 |
| 6 | Employee page: drop one reply response after the server accepts it, then select retry | The reply remains visible as `Delivery outcome unknown`; retry uses the same safe request key, reconciles the saved result, and shows one `Delivered` copy | Automated Workbench interaction and API idempotency checks passed, 2026-08-25 |
| 7 | Customer page: refresh the page or reopen the saved claim | The staff reply appears and the claimant can continue from the saved claim without entering confirmed information again | Existing component check passed, 2026-08-24 |
| 8 | Employee page: resolve the handoff; then check the customer page again | The claimant sees a plain-language next step. Internal staff notes and Agent drafting details are not visible | Existing API and visibility checks passed, 2026-08-24 |

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

Run the focused checks while developing; CircleCI supplies the authoritative exact-head result:

```text
py -3.12 -m pytest tests/test_handoff_api.py tests/test_staff_actions_api.py tests/test_employee_workbench_static.py
npm test --prefix customer -- --run src/App.test.jsx src/EmployeeWorkbench.test.js
```

Focused checks are `customer/src/App.test.jsx`, `customer/src/EmployeeWorkbench.test.js`,
`tests/test_handoff_api.py`, `tests/test_staff_actions_api.py`, and
`tests/test_employee_workbench_static.py`.
