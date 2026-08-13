# Employee Workbench

This static page demonstrates the employee-facing workbench using the backend workbench API.

## Purpose

- Replicates the employee workbench experience from `prototype/employee-workbench-prototype.html`.
- Uses the stable backend workbench API at `/api/v1/workbench/claims`.
- Separates staff-only internal fields from customer-visible information.

## Local use

Run the single-origin demonstration server from the repository root:

```powershell
./scripts/start-demo.ps1
```

Open `http://127.0.0.1:8765/employee/`. The page uses the same-origin workbench API under
`/api/v1/workbench/claims`.

## Staff credentials

- `Authorization: Bearer synthetic-staff`

The page is hard-coded for the local prototype staff token.

## Notes

- The workbench data is read-only; the AI assistant and customer-chat replies are local prototype interactions until their respective live services are connected.
- It derives internal flags from `signals`, assignment from open `handoffs`, and notes from
	persisted internal messages and `staff_actions`.
- It does not expose claimant-only private data.
