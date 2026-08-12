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

- The page is read-only and illustrates stable workbench API integration.
- It shows internal-only fields such as `internal_flags`, `assigned_to`, and staff notes.
- It does not expose claimant-only private data.
