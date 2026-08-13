# Employee Workbench Frontend

A single-page staff workbench UI for reviewing FNOL claims.

## Overview

`employee/index.html` is a self-contained HTML/JS frontend for Northwind Insurance staff. It connects to the **live backend API** at `/api/v1/workbench/claims` and renders the rich `WorkbenchClaimDetail` projection.

## API contract

The frontend reads from `WorkbenchClaimDetail` as returned by `GET /api/v1/workbench/claims/{claim_id}`. Key fields used:

| Frontend use | Backend field |
|---|---|
| Claim queue list | `WorkbenchClaimItem.workflow_state`, `.customer_next_step` |
| Claim info | `detail.claim_id`, `.customer_reference`, `.channel`, `.locale`, `.incident_type`, `.route`, `.active_session_id`, `.created_at`, `.updated_at` |
| Claim state | `detail.claim_state.workflow_state`, `.fraud_signal` |
| Assigned-to | `detail.handoffs[].assigned_to` (sourced from persisted handoff records) |
| Sessions | `detail.sessions[].session_id`, `.summary` |
| Handoffs | `detail.handoffs[].handoff_id`, `.queue`, `.assigned_to` |
| Messages | `detail.messages[].actor`, `.visibility`, `.content` |
| Evidence | `detail.evidence[].kind`, `.status` |
| Decisions | `detail.decisions[].action`, `.customer_reason` |
| Signals | `detail.signals[].code`, `.status` |
| Staff actions | `detail.staff_actions[].action_type`, `.note` |

> **Note**: The frontend does **not** use `detail.internal_notes`, `detail.internal_flags`, or `detail.assigned_to` as top-level fields — those do not exist on the rich `WorkbenchClaimDetail` model. Assignment is read from `handoffs[].assigned_to` instead.

## Running locally

Serve the backend (see root `README.md`), then open `employee/index.html` in a browser pointed at the backend. The frontend uses a hardcoded `staff_demo` token; update the `STAFF_TOKEN` constant for a real deployment.

## Customer-chat vs backend functionality

- **Live backend**: `/api/v1/workbench/claims` list and detail endpoints (see `backend/api/workbench.py`)
- **Local-only (AI/customer-chat)**: The `customer/` directory contains the customer-facing FNOL intake chat, which may include AI agent interactions that only run with valid AWS/OpenAI credentials configured locally.
