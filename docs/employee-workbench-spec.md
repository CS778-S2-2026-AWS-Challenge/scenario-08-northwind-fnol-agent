# Employee Workbench Frontend Specification

## Goal

Provide a staff-facing workbench experience that uses the same shared backend claim state as the claimant client, while preserving internal-only visibility boundaries.

## Scope

- A separate static employee frontend under `employee/`.
- Integration with backend endpoints defined in `docs/api.md` for workbench access:
  - `GET /api/v1/workbench/claims`
  - `GET /api/v1/workbench/claims/{claim_id}`
- Staff authentication via a dedicated token separate from claimant credentials.
- Read-only claim browsing for this prototype.

## UI Requirements

- Display a queue filter and claim list from `/workbench/claims`.
- Show selected claim details with internal metadata:
  - `customer_reference`
  - `workflow_state`
  - `assigned_to`
  - `internal_flags`
  - `internal_notes`
  - `customer_next_step`
- Clearly label the interface as staff-only.
- Do not render internal-only fields in claimant views.

## Backend Integration

### Workbench API

The employee frontend must use the workbench API exposed by the backend.

- `GET /api/v1/workbench/claims`: list authorised workbench claims.
- `GET /api/v1/workbench/claims/{claim_id}`: fetch claim detail for the selected workbench claim.

### Auth

The staff frontend uses a separate staff bearer token for authorization.

- Local development staff token: `synthetic-staff`
- Claimant token remains `synthetic-claimant`
- The backend must enforce staff-only access for `/api/v1/workbench/*`

## Development Notes

- This prototype is intentionally static and portable.
- The page assumes the backend is available at `http://127.0.0.1:8000`.
- The workbench integration is a read-only proof of concept. Future work can add write actions, customer chat handoff, and staff assignments.
