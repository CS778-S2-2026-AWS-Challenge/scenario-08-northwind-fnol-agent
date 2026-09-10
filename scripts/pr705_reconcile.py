from pathlib import Path

path = Path('docs/api.md')
text = path.read_text(encoding='utf-8')

old = (
    'When a claimant resumes an existing working claim, the server starts a new interaction '
    'session using the current claim state and bounded resume context. A previously paused '
    'session MAY be closed when the new session is created.\n\n'
    'Only one active claimant session per claim is permitted.\n\n'
    'Messages MUST NOT be accepted for a closed session.'
)
new = (
    '`POST /api/v1/claims/{claim_id}/sessions/{session_id}/pause` is the explicit P17.1 '
    'interruption boundary. It requires the current Claim revision through `If-Match` plus an '
    '`Idempotency-Key`, atomically marks the current session `paused`, aligns that Session\'s '
    'recovery snapshot to the accepted Claim revision, clears the Claim\'s active-session '
    'pointer, stores bounded recovery context, and creates exactly one open Claim-scoped '
    'recovery Follow-up for the `resume_incomplete_claim` purpose. The accepted Claim revision '
    'is part of the idempotency fingerprint, so reusing the same key with a different '
    '`If-Match` value returns `409 IDEMPOTENCY_CONFLICT`. It does not create a second Claim '
    'State, send a follow-up, make an abandonment decision, or apply a retention transition.\n\n'
    'The recovery Follow-up persists purpose, source references, responsible party, channel, '
    'due time, status, attempt count, and a contact-permission condition. An authenticated '
    'claimant may receive a `pending` in-app recovery Follow-up; that record does not authorise '
    'email, SMS, or phone contact. An anonymous browser claimant has no durable authorised '
    'contact channel in P17.1, so the record is persisted as `blocked` with '
    '`contact_permission=not_authorised`, no channel, and no due time. P17.2 owns any later '
    'scheduling, delivery, attempt, or escalation policy.\n\n'
    'After that checkpoint, claimant Claim detail and Claim list projections may include '
    '`incomplete_context` containing the interruption time, last meaningful activity, bounded '
    'resume point, and the claimant-safe open Follow-up state. Pause is accepted only when the '
    'authoritative Claim is not `created` and `customer_next_step.can_resume=true`; terminal or '
    'explicitly non-resumable Claims return `409 INVALID_STATE_TRANSITION`. Claimant and '
    'Workbench projections use the same incomplete predicate: an eligible resumable '
    'non-terminal Claim, no authoritative active Session, a relevant paused recovery '
    'checkpoint, and an open recovery Follow-up. This applies to every resumable non-terminal '
    'workflow state, not only `collecting`. The persisted checkpoint also records the exact '
    'durable source reference for the latest qualifying claimant message or accepted claimant '
    'business action.\n\n'
    'When a claimant resumes an existing working claim, the server starts a new interaction '
    'session using the current Claim State and bounded resume context and atomically marks the '
    'open recovery Follow-up `resolved`. A later interruption of that resumed Session may create '
    'the next recovery Follow-up for the same purpose because only one open Claim+purpose record '
    'is allowed at a time.\n\n'
    'Only one active claimant session per claim is permitted.\n\n'
    'Messages MUST NOT be accepted for a closed or paused session.'
)
if old not in text:
    raise SystemExit('session lifecycle anchor not found')
text = text.replace(old, new, 1)

row = '| `POST` | `/claims/{claim_id}/sessions` | Start or resume a session |\n'
pause_row = (
    '| `POST` | `/claims/{claim_id}/sessions/{session_id}/pause` | Persist an interruption '
    'checkpoint and initial follow-up task; requires `If-Match` and `Idempotency-Key` |\n'
)
if row not in text:
    raise SystemExit('endpoint catalogue anchor not found')
text = text.replace(row, row + pause_row, 1)

old_incomplete = (
    '`incomplete_claims` contains Claims in the existing collecting/incomplete queue. It does not\n'
    'represent or infer a triage status.'
)
new_incomplete = (
    '`incomplete_claims` contains resumable non-terminal Claims with no authoritative active '
    'Session,\na relevant durable paused recovery checkpoint, and an open recovery Follow-up. '
    'It is an operational\noverlay rather than an active lifecycle queue and does not infer a '
    'triage status.'
)
if old_incomplete not in text:
    raise SystemExit('incomplete view anchor not found')
text = text.replace(old_incomplete, new_incomplete, 1)

path.write_text(text, encoding='utf-8')
