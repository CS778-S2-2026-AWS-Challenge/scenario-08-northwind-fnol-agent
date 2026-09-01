# Admin Console

This independently served static frontend provides the administration shell over the authenticated Admin API. It is separate from claimant and Staff Workbench routes and contains no direct provider or storage access.

## Local use

Start the backend in explicit developer identity mode, then serve this directory:

```powershell
cd admin
py -3.12 -m http.server 8003
```

Open `http://127.0.0.1:8003`. The page ships no credential. For a local developer-mode walkthrough, explicitly set the registered synthetic administrator credential in the browser console:

```js
localStorage.setItem('northwind.adminToken', 'synthetic-admin')
```

The token cannot enable developer mode or cross the claimant and Staff Workbench access boundaries. The console calls only `/internal/v1/admin`; modules without an implemented Admin API capability show an honest empty or unavailable state and no management controls.

Repeat the console-to-API access-boundary check from the repository root:

```powershell
py -3.12 -m pytest tests/test_admin_console_contract.py
```
