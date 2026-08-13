# Employee Workbench

This static page demonstrates the employee-facing workbench using the backend workbench API.

## Purpose

- Replicates the employee workbench experience from `prototype/employee-workbench-prototype.html`.
- Uses the stable backend workbench API at `/api/v1/workbench/claims`.
- Separates staff-only internal fields from customer-visible information.

## Local use

1. Start the backend from the repository root:

```bash
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

2. Serve the employee page from the `employee/` folder:

```bash
cd employee
python -m http.server 8002
```

3. Open `http://127.0.0.1:8002` in your browser.

## Staff credentials

- `Authorization: Bearer synthetic-staff`

The page is hard-coded for the local prototype staff token.

## Notes

- Claim browsing uses the shared staff projection. Staff actions, action completion, authorised
  claim-state changes, claimant-safe updates, and review-signal decisions use the live workbench
  mutation API with revision and idempotency guards.
- The AI assistant and free-form customer-chat replies remain local prototype interactions until
  their respective live services are connected. Claimant-safe updates submitted while completing
  a staff action are persisted through the backend.
- It derives internal flags from `signals`, assignment from open `handoffs`, and notes from
	persisted internal messages and `staff_actions`.
- It does not expose claimant-only private data.
