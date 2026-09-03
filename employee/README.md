# Legacy Employee Workbench Inventory

The supported employee-facing application is the componentised React/Vite Workbench in
`/workbench/`. `employee/index.html` is only a compatibility notice and does not load the
legacy implementation. The adjacent `app.js` and `styles.css` files are retained temporarily
as migration inventory while the final feature parity review is completed.

## Purpose

- The React Workbench uses the stable backend API at `/api/v1/workbench/claims`.
- Staff-only fields, provenance, evidence, sessions, conversations, signals, handoffs and
  audited actions are rendered by the Workbench modules under `workbench/src/`.
- The legacy files are not a second supported product surface and must not receive new features.

## Local use

1. Start the backend in explicit local developer identity mode:

```powershell
$env:NORTHWIND_ENVIRONMENT='development'
$env:NORTHWIND_IDENTITY_MODE='developer'
py -3.12 -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

1. Start the supported Workbench application:

```powershell
cd ..\workbench
npm ci
npm run dev -- --host 127.0.0.1 --port 5174
```

1. Open `http://127.0.0.1:5174/workbench/` in your browser.

## Staff credentials

Use the staff sign-in form in the Workbench. Claimant credentials and staff credentials are
separate identity boundaries; no token should be injected through the browser console.

## Notes

- The migration inventory is read-only documentation. New Workbench changes belong in
  `workbench/src/` and its tests.
- After feature parity is confirmed, move these legacy files to the repository-external archive
  and remove them from the repository.
