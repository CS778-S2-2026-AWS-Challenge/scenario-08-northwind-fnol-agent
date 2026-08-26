# Claimant Client

This React and Vite application is the claimant-facing Northwind FNOL client.

Install it from the repository root:

```powershell
npm ci --prefix customer
```

For the local synthetic demo, start the backend with explicit developer identity mode first, then
start Vite with the local claimant credential explicitly configured:

```powershell
$env:VITE_NORTHWIND_CLAIMANT_TOKEN='synthetic-claimant'
npm run dev --prefix customer
```

Vite proxies relative `/api` requests to the FastAPI backend at `http://127.0.0.1:8000`. The client
has no built-in claimant-token fallback: if `VITE_NORTHWIND_CLAIMANT_TOKEN` is omitted, it does not
manufacture a synthetic identity. Providing the browser token also does not switch the backend into
developer mode; the server must already be explicitly configured for that local/test mode.

The repository synthetic token is fixture-only and is not a production authentication path.

Run claimant checks with:

```powershell
npm run lint --prefix customer
npm test --prefix customer
npm run build --prefix customer
```

API paths and shared field names must follow `docs/api.md`. Claimant code must never render or depend on internal-only signals.
