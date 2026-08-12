# Claimant Client

This React and Vite application is the claimant-facing Northwind FNOL client.

Install and start it from the repository root:

```powershell
npm ci --prefix customer
npm run dev --prefix customer
```

During local development, Vite proxies relative `/api` requests to the FastAPI backend at `http://127.0.0.1:8000`. Start the backend first using the command in the root `README.md`.

Run claimant checks with:

```powershell
npm run lint --prefix customer
npm test --prefix customer
npm run build --prefix customer
```

API paths and shared field names must follow `docs/api.md`. Claimant code must never render or depend on internal-only signals.
