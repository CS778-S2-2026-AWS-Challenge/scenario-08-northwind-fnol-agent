from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend.api import claims as claims_api
from backend.api import evidence as evidence_api
from backend.api import handoffs as handoffs_api
from backend.api import integrations as integrations_api
from backend.api import workbench as workbench_api
from backend.core.errors import ApiError
from backend.domain.models import HandoffStatus
from backend.repositories.fixture import FixtureRepository
from backend.repositories.handoff_guard import (
    HandoffPersistenceConflict,
    HandoffPersistenceGuard,
    ResettableHandoffPersistenceGuard,
    guarded_handoff_repository,
)
from backend.repositories.protocols import IdempotencyRecord, RevisionConflict
from backend.services.demo_reset import reset_demo_components


def create_claim_and_handoff(
    client: TestClient,
    auth_headers: dict[str, str],
    *,
    key_prefix: str,
) -> tuple[str, str]:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': f'{key_prefix}-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert created.status_code == 201
    claim_id = created.json()['claim']['claim_id']

    requested = client.post(
        f'/api/v1/claims/{claim_id}/support-requests',
        headers={
            **auth_headers,
            'Idempotency-Key': f'{key_prefix}-support',
            'If-Match': '1',
        },
        json={
            'reason': 'I want a person to continue this synthetic claim.',
            'support_need': 'human_requested',
            'preferred_channel': 'phone',
        },
    )
    assert requested.status_code == 201
    assert requested.json()['revision'] == 2
    return claim_id, requested.json()['handoff']['handoff_id']


def accept_handoff(
    client: TestClient,
    staff_auth_headers: dict[str, str],
    claim_id: str,
    handoff_id: str,
    *,
    key: str,
    revision: int = 2,
) -> dict[str, Any]:
    response = client.post(
        f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/accept',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': key,
            'If-Match': str(revision),
        },
        json={},
    )
    assert response.status_code == 200
    return cast(dict[str, Any], response.json())


def handoff_retry(
    claim_id: str,
    handoff_id: str,
    *,
    actor_id: str = 'stf_demo',
    key: str = 'handoff-guard-write',
) -> IdempotencyRecord:
    return IdempotencyRecord(
        actor_id=actor_id,
        route=f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}',
        key=key,
        request_fingerprint=key,
        claim_id=claim_id,
        session_id='',
        handoff_id=handoff_id,
    )


def test_handoff_owner_status_and_writeback_follow_one_claim_revision(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, handoff_id = create_claim_and_handoff(
        client,
        auth_headers,
        key_prefix='handoff-lifecycle',
    )

    accepted = accept_handoff(
        client,
        staff_auth_headers,
        claim_id,
        handoff_id,
        key='handoff-lifecycle-accept',
    )
    assert accepted['revision'] == 3
    assert accepted['handoff']['status'] == 'accepted'
    assert accepted['handoff']['assigned_to'] == 'stf_demo'

    message = client.post(
        f'/api/v1/workbench/claims/{claim_id}/messages',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'handoff-lifecycle-message',
            'If-Match': '3',
        },
        json={'content': {'type': 'text', 'text': 'I am continuing from the saved context.'}},
    )
    assert message.status_code == 200
    assert message.json()['claim_revision'] == 4

    in_progress = repository.get_handoff(claim_id, handoff_id, 'cus_demo')
    assert in_progress is not None
    assert in_progress.status is HandoffStatus.IN_PROGRESS
    assert in_progress.assigned_to == 'stf_demo'
    assert in_progress.accepted_at is not None

    resolved = client.post(
        f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/resolve',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'handoff-lifecycle-resolve',
            'If-Match': '4',
        },
        json={
            'result': {
                'outcome': 'support_completed',
                'summary': 'The synthetic support request was completed.',
                'reason_codes': ['SUPPORT_NEED_MET'],
                'source_refs': in_progress.packet.source_refs,
            },
            'state_changes': [],
            'customer_update': {
                'summary': 'A staff member completed the support step and your claim can continue.',
                'responsible_party': 'claims_professional',
                'related_refs': [handoff_id],
            },
        },
    )
    assert resolved.status_code == 200
    body = resolved.json()
    assert body['revision'] == 5
    assert body['handoff']['status'] == 'resolved'
    assert body['handoff']['assigned_to'] == 'stf_demo'
    assert body['staff_action']['assigned_to'] == 'stf_demo'
    assert body['staff_action']['completed_by'] == 'stf_demo'
    assert body['customer_update']['created_by'] == 'stf_demo'

    stored_claim = repository.get_claim_internal(claim_id)
    stored_handoff = repository.get_handoff(claim_id, handoff_id, 'cus_demo')
    assert stored_claim is not None
    assert stored_handoff is not None
    assert stored_claim.revision == 5
    assert stored_handoff.status is HandoffStatus.RESOLVED
    assert stored_handoff.assigned_to == 'stf_demo'
    assert stored_handoff.resolved_at is not None


def test_staff_message_requires_handoff_owner_and_same_session_reply_reference(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, handoff_id = create_claim_and_handoff(
        client, auth_headers, key_prefix='staff-message-authority'
    )
    accept_handoff(
        client,
        staff_auth_headers,
        claim_id,
        handoff_id,
        key='staff-message-authority-accept',
    )
    handoff = repository.get_handoff(claim_id, handoff_id, 'cus_demo')
    assert handoff is not None
    repository.save_handoff(handoff.model_copy(update={'assigned_to': 'stf_other'}), 'cus_demo')

    wrong_assignee = client.post(
        f'/api/v1/workbench/claims/{claim_id}/messages',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'staff-message-wrong-assignee',
            'If-Match': '3',
        },
        json={'content': {'type': 'text', 'text': 'This must not be sent.'}},
    )
    assert wrong_assignee.status_code == 403
    assert wrong_assignee.json()['error']['code'] == 'ACCESS_DENIED'

    repository.save_handoff(handoff, 'cus_demo')
    other_claim = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'reply-reference-other-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    ).json()
    other_claim_id = other_claim['claim']['claim_id']
    other_session_id = other_claim['session']['session_id']
    other_turn = client.post(
        f'/api/v1/claims/{other_claim_id}/sessions/{other_session_id}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': 'reply-reference-other-message',
            'If-Match': '1',
        },
        json={
            'client_message_id': 'reply-reference-other-message',
            'content': {'type': 'text', 'text': 'A separate synthetic claim.'},
            'evidence_refs': [],
        },
    ).json()

    cross_claim_reply = client.post(
        f'/api/v1/workbench/claims/{claim_id}/messages',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'staff-message-cross-claim-reply',
            'If-Match': '3',
        },
        json={
            'content': {'type': 'text', 'text': 'This reference must be rejected.'},
            'in_reply_to': other_turn['claimant_message']['message_id'],
        },
    )
    assert cross_claim_reply.status_code == 422
    assert cross_claim_reply.json()['error']['code'] == 'VALIDATION_ERROR'


def test_repeated_support_request_reuses_owned_handoff_without_conflict(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, handoff_id = create_claim_and_handoff(
        client,
        auth_headers,
        key_prefix='handoff-repeat',
    )
    accepted = accept_handoff(
        client,
        staff_auth_headers,
        claim_id,
        handoff_id,
        key='handoff-repeat-accept',
    )
    assert accepted['revision'] == 3

    repeated = client.post(
        f'/api/v1/claims/{claim_id}/support-requests',
        headers={
            **auth_headers,
            'Idempotency-Key': 'handoff-repeat-second-request',
            'If-Match': '3',
        },
        json={
            'reason': 'I still need the same person to continue this claim.',
            'support_need': 'human_requested',
            'preferred_channel': 'phone',
        },
    )
    assert repeated.status_code == 201
    assert repeated.json()['revision'] == 3
    assert repeated.json()['handoff']['handoff_id'] == handoff_id

    handoffs = repository.list_handoffs(claim_id, 'cus_demo')
    assert len(handoffs) == 1
    assert handoffs[0].assigned_to == 'stf_demo'
    assert handoffs[0].status is HandoffStatus.ACCEPTED


def test_persistence_guard_rejects_owner_bypass_and_non_owner_write(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, handoff_id = create_claim_and_handoff(
        client,
        auth_headers,
        key_prefix='handoff-guard',
    )
    accept_handoff(
        client,
        staff_auth_headers,
        claim_id,
        handoff_id,
        key='handoff-guard-accept',
    )

    stored_claim = repository.get_claim_internal(claim_id)
    stored_handoff = repository.get_handoff(claim_id, handoff_id, 'cus_demo')
    assert stored_claim is not None
    assert stored_handoff is not None
    assert stored_claim.revision == 3
    assert stored_handoff.assigned_to == 'stf_demo'

    guarded = guarded_handoff_repository(repository)
    with pytest.raises(HandoffPersistenceConflict):
        guarded.save_handoff(
            stored_handoff.model_copy(update={'assigned_to': 'stf_other'}),
            'cus_demo',
        )

    continued = stored_handoff.model_copy(update={'status': HandoffStatus.IN_PROGRESS})
    next_claim = stored_claim.model_copy(update={'revision': stored_claim.revision + 1})
    other_staff_write = handoff_retry(
        claim_id,
        handoff_id,
        actor_id='stf_other',
        key='other-staff-write',
    )
    with pytest.raises(HandoffPersistenceConflict):
        guarded.save_staff_mutation(
            next_claim,
            stored_claim.revision,
            other_staff_write,
            handoff=continued,
        )

    unchanged_claim = repository.get_claim_internal(claim_id)
    unchanged_handoff = repository.get_handoff(claim_id, handoff_id, 'cus_demo')
    assert unchanged_claim is not None
    assert unchanged_handoff is not None
    assert unchanged_claim.revision == 3
    assert unchanged_handoff.status is HandoffStatus.ACCEPTED
    assert unchanged_handoff.assigned_to == 'stf_demo'


def test_guard_preserves_parent_revision_as_the_first_concurrency_check(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, handoff_id = create_claim_and_handoff(
        client,
        auth_headers,
        key_prefix='handoff-revision',
    )
    claim = repository.get_claim_internal(claim_id)
    handoff = repository.get_handoff(claim_id, handoff_id, 'cus_demo')
    assert claim is not None
    assert handoff is not None
    guarded = guarded_handoff_repository(repository)
    accepted = handoff.model_copy(
        update={
            'status': HandoffStatus.ACCEPTED,
            'assigned_to': 'stf_demo',
            'accepted_at': handoff.created_at,
        }
    )
    next_claim = claim.model_copy(update={'revision': claim.revision + 1})
    retry = handoff_retry(claim_id, handoff_id)

    with pytest.raises(RevisionConflict) as stale:
        guarded.save_staff_mutation(next_claim, claim.revision - 1, retry, handoff=accepted)
    assert stale.value.current_revision == claim.revision

    with pytest.raises(KeyError):
        guarded.save_staff_mutation(
            next_claim.model_copy(update={'claim_id': 'clm_missing'}),
            claim.revision,
            retry,
            handoff=accepted,
        )

    with pytest.raises(KeyError):
        guarded.save_staff_mutation(
            next_claim.model_copy(update={'customer_id': 'cus_other'}),
            claim.revision,
            retry,
            handoff=accepted,
        )

    with pytest.raises(HandoffPersistenceConflict):
        guarded.save_staff_mutation(
            claim,
            claim.revision,
            retry,
            handoff=accepted,
        )


def test_guard_rejects_invalid_handoff_creation_records(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, handoff_id = create_claim_and_handoff(
        client,
        auth_headers,
        key_prefix='handoff-create-guard',
    )
    claim = repository.get_claim_internal(claim_id)
    stored = repository.get_handoff(claim_id, handoff_id, 'cus_demo')
    assert claim is not None
    assert stored is not None
    guarded = guarded_handoff_repository(repository)
    next_claim = claim.model_copy(update={'revision': claim.revision + 1})
    fresh = stored.model_copy(update={'handoff_id': 'hnd_fresh'})

    with pytest.raises(HandoffPersistenceConflict):
        guarded.save_handoff_mutation(
            next_claim,
            claim.revision,
            fresh,
            handoff_retry(claim_id, 'hnd_wrong'),
        )

    with pytest.raises(HandoffPersistenceConflict):
        guarded.save_handoff_mutation(
            next_claim,
            claim.revision,
            fresh.model_copy(update={'assigned_to': 'stf_demo'}),
            handoff_retry(claim_id, 'hnd_fresh'),
        )

    with pytest.raises(HandoffPersistenceConflict):
        guarded.save_handoff_mutation(
            next_claim,
            claim.revision,
            fresh.model_copy(update={'status': HandoffStatus.ACCEPTED}),
            handoff_retry(claim_id, 'hnd_fresh'),
        )

    with pytest.raises(HandoffPersistenceConflict):
        guarded.save_handoff_mutation(
            next_claim,
            claim.revision,
            stored,
            handoff_retry(claim_id, handoff_id),
        )


def test_guard_rejects_invalid_staff_lifecycle_mutations(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, handoff_id = create_claim_and_handoff(
        client,
        auth_headers,
        key_prefix='handoff-state-guard',
    )
    claim = repository.get_claim_internal(claim_id)
    queued = repository.get_handoff(claim_id, handoff_id, 'cus_demo')
    assert claim is not None
    assert queued is not None
    guarded = guarded_handoff_repository(repository)
    next_claim = claim.model_copy(update={'revision': claim.revision + 1})
    retry = handoff_retry(claim_id, handoff_id)

    with pytest.raises(HandoffPersistenceConflict):
        guarded.save_staff_mutation(
            next_claim,
            claim.revision,
            handoff_retry(claim_id, 'hnd_wrong'),
            handoff=queued,
        )

    missing = queued.model_copy(update={'handoff_id': 'hnd_missing'})
    with pytest.raises(HandoffPersistenceConflict):
        guarded.save_staff_mutation(
            next_claim,
            claim.revision,
            handoff_retry(claim_id, 'hnd_missing'),
            handoff=missing,
        )

    with pytest.raises(HandoffPersistenceConflict):
        guarded.save_staff_mutation(
            next_claim,
            claim.revision,
            retry,
            handoff=queued.model_copy(update={'reason': 'A rewritten reason is not allowed.'}),
        )

    with pytest.raises(HandoffPersistenceConflict):
        guarded.save_staff_mutation(
            next_claim,
            claim.revision,
            retry,
            handoff=queued.model_copy(
                update={
                    'status': HandoffStatus.RESOLVED,
                    'assigned_to': 'stf_demo',
                    'accepted_at': queued.created_at,
                    'resolved_at': queued.created_at,
                }
            ),
        )

    with pytest.raises(HandoffPersistenceConflict):
        guarded.save_staff_mutation(
            next_claim,
            claim.revision,
            retry,
            handoff=queued.model_copy(
                update={
                    'status': HandoffStatus.ACCEPTED,
                    'accepted_at': queued.created_at,
                }
            ),
        )

    with pytest.raises(HandoffPersistenceConflict):
        guarded.save_staff_mutation(
            next_claim,
            claim.revision,
            retry,
            handoff=queued.model_copy(
                update={
                    'status': HandoffStatus.ACCEPTED,
                    'assigned_to': 'stf_demo',
                }
            ),
        )


def test_guard_preserves_acceptance_resolution_and_terminal_state(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, handoff_id = create_claim_and_handoff(
        client,
        auth_headers,
        key_prefix='handoff-terminal-guard',
    )
    accept_handoff(
        client,
        staff_auth_headers,
        claim_id,
        handoff_id,
        key='handoff-terminal-accept',
    )
    claim = repository.get_claim_internal(claim_id)
    accepted = repository.get_handoff(claim_id, handoff_id, 'cus_demo')
    assert claim is not None
    assert accepted is not None
    assert accepted.accepted_at is not None
    guarded = guarded_handoff_repository(repository)
    next_claim = claim.model_copy(update={'revision': claim.revision + 1})
    retry = handoff_retry(claim_id, handoff_id)

    with pytest.raises(HandoffPersistenceConflict):
        guarded.save_staff_mutation(
            next_claim,
            claim.revision,
            retry,
            handoff=accepted.model_copy(update={'assigned_to': 'stf_other'}),
        )

    with pytest.raises(HandoffPersistenceConflict):
        guarded.save_staff_mutation(
            next_claim,
            claim.revision,
            retry,
            handoff=accepted.model_copy(
                update={
                    'status': HandoffStatus.IN_PROGRESS,
                    'accepted_at': None,
                }
            ),
        )

    with pytest.raises(HandoffPersistenceConflict):
        guarded.save_staff_mutation(
            next_claim,
            claim.revision,
            retry,
            handoff=accepted.model_copy(
                update={
                    'status': HandoffStatus.RESOLVED,
                    'resolved_at': None,
                }
            ),
        )

    guarded.save_handoff(accepted, 'cus_demo')
    assert guarded_handoff_repository(guarded) is guarded
    assert guarded.get_claim_internal(claim_id) == claim


def test_guard_rejects_invalid_payload_and_terminal_rewrite(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, handoff_id = create_claim_and_handoff(
        client,
        auth_headers,
        key_prefix='handoff-terminal-rewrite',
    )
    accept_handoff(
        client,
        staff_auth_headers,
        claim_id,
        handoff_id,
        key='handoff-terminal-rewrite-accept',
    )
    accepted_handoff = repository.get_handoff(claim_id, handoff_id, 'cus_demo')
    assert accepted_handoff is not None
    resolved = client.post(
        f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/resolve',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'handoff-terminal-rewrite-resolve',
            'If-Match': '3',
        },
        json={
            'result': {
                'outcome': 'support_completed',
                'summary': 'Resolve the synthetic handoff.',
                'reason_codes': ['SUPPORT_NEED_MET'],
                'source_refs': accepted_handoff.packet.source_refs,
            },
            'state_changes': [],
            'customer_update': {
                'summary': 'The support step is complete.',
                'responsible_party': 'claims_professional',
                'related_refs': [handoff_id],
            },
        },
    )
    assert resolved.status_code == 200
    claim = repository.get_claim_internal(claim_id)
    terminal = repository.get_handoff(claim_id, handoff_id, 'cus_demo')
    assert claim is not None
    assert terminal is not None
    assert terminal.resolved_at is not None
    guarded = guarded_handoff_repository(repository)
    next_claim = claim.model_copy(update={'revision': claim.revision + 1})
    retry = handoff_retry(claim_id, handoff_id)

    with pytest.raises(HandoffPersistenceConflict):
        guarded.save_staff_mutation(
            next_claim,
            claim.revision,
            retry,
            handoff='not-a-handoff',
        )

    with pytest.raises(HandoffPersistenceConflict):
        guarded.save_staff_mutation(
            next_claim,
            claim.revision,
            retry,
            handoff=terminal.model_copy(update={'status': HandoffStatus.IN_PROGRESS}),
        )

    with pytest.raises(HandoffPersistenceConflict):
        guarded.save_staff_mutation(
            next_claim,
            claim.revision,
            retry,
            handoff=terminal.model_copy(update={'resolved_at': terminal.accepted_at}),
        )


def application_repository(app: FastAPI) -> Any:
    """The repository object every router, service, and adapter consumes."""
    return app.state.claim_repository


def router_repository(app: FastAPI, repository_for: Any) -> Any:
    request = Request({'type': 'http', 'app': app, 'headers': []})
    return repository_for(request)


def test_every_router_receives_the_guarded_application_repository(app: FastAPI) -> None:
    guarded = application_repository(app)

    assert isinstance(guarded, HandoffPersistenceGuard)
    for repository_for in (
        claims_api.repository_for,
        evidence_api.repository_for,
        handoffs_api.repository_for,
        integrations_api.repository_for,
        workbench_api.repository_for,
    ):
        assert router_repository(app, repository_for) is guarded


def test_application_repository_rejects_an_unguarded_handoff_overwrite(
    app: FastAPI,
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
) -> None:
    claim_id, handoff_id = create_claim_and_handoff(client, auth_headers, key_prefix='bypass')
    accept_handoff(client, staff_auth_headers, claim_id, handoff_id, key='bypass-accept')

    guarded = application_repository(app)
    claim = guarded.get_claim_internal(claim_id)
    assert claim is not None
    accepted = guarded.get_handoff(claim_id, handoff_id, claim.customer_id)
    assert accepted is not None
    assert accepted.assigned_to is not None

    # A consumer holding the application repository cannot take ownership with a
    # direct write, and cannot skip the revision-checked mutation boundary.
    with pytest.raises(HandoffPersistenceConflict):
        guarded.save_handoff(
            accepted.model_copy(update={'assigned_to': 'stf_other'}),
            claim.customer_id,
        )

    with pytest.raises(HandoffPersistenceConflict):
        guarded.save_staff_mutation(
            claim.model_copy(update={'revision': claim.revision + 1}),
            claim.revision,
            handoff_retry(claim_id, handoff_id, actor_id='stf_other', key='bypass-write'),
            handoff=accepted.model_copy(update={'status': HandoffStatus.RESOLVED}),
        )

    stored = guarded.get_handoff(claim_id, handoff_id, claim.customer_id)
    assert stored == accepted
    assert guarded.get_claim_internal(claim_id) == claim


def test_guarding_preserves_the_controlled_demo_reset_opt_in() -> None:
    repository = FixtureRepository()
    guarded = guarded_handoff_repository(repository)

    assert isinstance(guarded, ResettableHandoffPersistenceGuard)
    assert reset_demo_components({'repository': guarded}) == repository.reset_demo_state()


def test_guarding_keeps_demo_reset_closed_for_a_repository_without_it() -> None:
    class ResetlessRepository:
        pass

    guarded = guarded_handoff_repository(cast(Any, ResetlessRepository()))

    assert not isinstance(guarded, ResettableHandoffPersistenceGuard)
    with pytest.raises(ApiError) as unavailable:
        reset_demo_components({'repository': guarded})
    assert unavailable.value.code == 'DEMO_RESET_UNAVAILABLE'
