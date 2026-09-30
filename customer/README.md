# Claimant Client

This React and Vite application is the claimant-facing Northwind FNOL client. Vite proxies
relative `/api` requests to the FastAPI backend. The client has no built-in claimant-token
fallback and never manufactures a synthetic identity; a claimant session always comes from the
backend's own login/session routes.

`VITE_NORTHWIND_WORKBENCH_URL` controls the login page's Employee access link. If it is omitted,
the client uses the deployment-safe same-origin path `/workbench/`; `scripts/start-dev.ps1` sets
the local URL automatically from its `-WorkbenchPort` value.

Run claimant checks with:

```powershell
npm run lint --prefix customer
npm test --prefix customer
npm run build --prefix customer
```

API paths and shared field names must follow `docs/api.md`. Claimant code must never render or depend on internal-only signals.
