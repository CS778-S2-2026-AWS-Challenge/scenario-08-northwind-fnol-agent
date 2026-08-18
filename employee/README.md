# Employee Workbench

This static page provides the employee-facing workbench over the backend workbench API.

## Purpose

- Replicates the employee workbench experience from `prototype/employee-workbench-prototype.html`.
- Uses the stable backend workbench API at `/api/v1/workbench/claims`.
- Separates staff-only internal fields from customer-visible information.
- Shows structured facts and provenance, evidence, session continuity, persisted communication,
  internal signals, and the complete handoff packet.
- Lets authorised staff accept a queued handoff and resolve it with a persisted claimant-visible
  update.
- Lets authorised staff create and complete audited staff actions, optionally update workflow
  state with a claimant-safe summary, and record decisions on internal review signals.

## Local use

1. Start the backend from the repository root:

```bash
py -3.12 -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

2. Serve the employee page from the `employee/` folder:

```bash
cd employee
py -3.12 -m http.server 8002
```

3. Open `http://127.0.0.1:8002` in your browser.

## Staff credentials

- `Authorization: Bearer synthetic-staff`

The page is hard-coded for the local prototype staff token.

## Notes

- The customer communication view is persisted conversation history. Staff messages can be sent
  while an accepted handoff remains open; resolving the handoff is a separate lifecycle action.
- The floating AI assistant remains a local, non-authoritative prototype interaction. It cannot
  change claim state.
- The page derives internal flags from `signals` and assignment from open `handoffs`.
- All write-back requests carry an idempotency key and the currently displayed claim revision;
  the queue and detail are reloaded after each successful mutation.
- The queue is never populated automatically. For a local walkthrough, staff must explicitly use
  **Load demo handoff queue** while the queue is empty. The action is available only in development
  and test environments and loads the bounded AT-02, AT-04, and AT-05 demo set.
- It does not expose claimant-only private data.
