# API Documentation

## Status

This document describes the API implemented on 10 August 2026. It is a temporary shell, not the target FNOL contract. Any incompatible change must update the API documentation and all consumers in the same pull request.

Local backend default: `http://127.0.0.1:8000`

## Endpoints

### `GET /health`

Returns a process-level health response.

Response `200`:

```json
{
  "status": "ok"
}
```

The endpoint currently does not verify storage, model, retrieval, or downstream services.

### `POST /api/claims/message`

Accepts one string and returns a fixed acknowledgement plus the same string.

Request:

```json
{
  "message": "Rear-ended at traffic lights"
}
```

Response `200`:

```json
{
  "reply": "I received your claim.",
  "received_message": "Rear-ended at traffic lights"
}
```

If `message` is omitted, FastAPI returns `422`. An empty string is currently accepted and returns `200`.

## Known Contract Gaps

- no API version prefix;
- no customer, claim, or session identifier;
- no authentication or authorisation;
- no structured form, claim state, agent action, evidence, or next step;
- no idempotency, persistence, pagination, concurrency control, or event stream;
- no documented error envelope or request correlation identifier;
- no upload, claim creation, history, policy, handoff, or workbench endpoints;
- no generated OpenAPI artefact committed or contract test;
- no configurable frontend base URL.

## Contract Change Rule

Before adding product features, define requests, successful responses, error responses, visibility, idempotency, and state transitions. The implementation, consumer, automated contract tests, and this documentation must change together.
