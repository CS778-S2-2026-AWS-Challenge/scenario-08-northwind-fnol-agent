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
| Staff reply | Primary Claim owner, or staff member/coworker authorised by an accepted handoff | Claimant | `sending`, then persisted `delivered` | A known rejection is `rejected_before_delivery`; a lost response is `delivery_outcome_unknown`. Keep the text and reuse the same staff-message idempotency key on `retrying`. | The current prototype offers a deterministic reply template, not Agent or AI generation. Template states remain internal until staff explicitly sends the composer text. |
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
5. On the employee website, a staff member opens that claim and accepts either the queued handoff
   or an unassigned completed Claim. For direct Claim acceptance, a fresh executable message action
   opens the existing customer conversation; acceptance does not invent a handoff or Session.
6. Staff may build a deterministic reply template from the claimant-safe next step. It is clearly
   marked as internal: staff can use it, change it, or reject it, but it is never sent automatically.
7. Staff review the final wording and click send. A failed reply stays visible and can be retried
   without creating two copies of the same message.
8. Back on the claimant website, the claimant opens **Messages with Northwind** from that Claim,
   reads the staff reply, and continues from the saved point without completing the form again.
   This is a Claim-focused conversation view: it keeps the selected Claim identity, shared message
   history, realtime state, and reply composer while hiding other Claims and unrelated intake
   workspace controls. Its stable Claim message route restores the same focused view after refresh.

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

### P12.3 interruption and recovery check

Use the same Claim and claimant session from the handoff journey. This check is specifically for
projection freshness and must be run with separate claimant and Workbench browser contexts.

| Step | Where and what to do | What you should see |
| --- | --- | --- |
| 1 | Claimant: request staff assistance and keep the Claim open | The claimant sees the authoritative waiting/queued handoff state and claimant-safe next step |
| 2 | Interrupt the claimant realtime transport without refreshing the page | A live-update reconnecting/stale status is announced; the existing Claim projection remains visible but is explicitly described as potentially out of date |
| 3 | Workbench: accept the same handoff and progress it while the claimant transport remains interrupted | Workbench continues from the same Claim/handoff and shows the server-projected staff reason, gaps, ownership, claimability, and actions |
| 4 | Restore claimant realtime connectivity | A replacement subscription is established first; opening it does not clear the claimant stale status |
| 5 | Allow the claimant authoritative Claim and current-session message refetch to complete | The same Claim/session now shows the accepted/in-progress handoff, current claimant-safe next step, and any permitted staff message; only then does the stale status clear |
| 6 | Repeat recovery with `resync_required` or `INVALID_EVENT_CURSOR` | The stale cursor is discarded, the replacement stream is opened before the authoritative snapshot, and no claimant business command is replayed |
| 7 | Workbench: resolve the handoff | The claimant receives the resolved/next-step projection through the same Claim/session continuity; no second intake or unlinked session is created |

Component coverage in `customer/src/App.test.jsx` verifies the transport warning and the
replacement-stream-before-snapshot recovery boundary, including the rule that the warning remains
until both the active Claim and current-session message readback succeed. That component evidence
supports, but does not replace, the separate browser run recorded below.

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
py -3.12 -m pytest tests/test_handoff_api.py tests/test_staff_actions_api.py tests/test_workbench_api.py
npm test --prefix customer -- --run src/EmployeeWorkbench.test.js
npm test --prefix workbench
```

Current focused checks are `customer/src/EmployeeWorkbench.test.js`,
`tests/test_handoff_api.py`, `tests/test_staff_actions_api.py`, and
`tests/test_workbench_api.py`. The componentised Workbench suite is run from `workbench/`.
The former broad claimant application suite is preserved under
`archive/frontend-heavy-tests/customer/` and is not a current CI target.
