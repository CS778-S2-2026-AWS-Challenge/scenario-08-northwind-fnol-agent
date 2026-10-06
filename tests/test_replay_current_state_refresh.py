"""Q65 keeps attempt history immutable and refreshes only current Claim state."""

from typing import Any
from unittest.mock import Mock

import mongomock
import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.domain.model_gateway import ModelGatewayErrorCode
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import PersistenceRepository
from backend.services import messages
from tests.test_safety_handoff_survives_model_failure import ObservingGatewayFailure


def historical_fields(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {'current_claim', 'current_claim_revision'}
    }


@pytest.mark.parametrize('backend', ['fixture', 'mongodb'])
def test_replay_refreshes_current_state_without_reexecuting_any_turn_effect(
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository: PersistenceRepository = (
        FixtureRepository()
        if backend == 'fixture'
        else MongoDBRepository(mongomock.MongoClient(), 'q65_replay')
    )
    if backend == 'mongodb':
        monkeypatch.setattr(repository, '_atomic', lambda operation: operation(None))
        monkeypatch.setattr(repository, 'watch_realtime_events', lambda *_args: iter(()))
    spies = []
    for name in (
        'save_agent_turn',
        'save_message_recovery',
        'save_handoff_mutation',
        'append_audit_event',
        'freeze_message_response',
    ):
        spy = Mock(wraps=getattr(repository, name))
        monkeypatch.setattr(repository, name, spy)
        spies.append(spy)
    for name in ('reduce_turn', 'continue_granted_service_offers'):
        spy = Mock(wraps=getattr(messages, name))
        monkeypatch.setattr(messages, name, spy)
        spies.append(spy)
    gateway = ObservingGatewayFailure(repository, ModelGatewayErrorCode.TIMEOUT)
    app = create_app(
        Settings(
            business_seed_path='config/business-seed.json',
            environment='test',
            identity_mode=IdentityMode.DEVELOPER,
        ),
        repository=repository,
        agent_turn_provider=gateway,
    )
    owner = {'Authorization': 'Bearer synthetic-claimant'}
    with TestClient(app) as client:
        created = client.post(
            '/api/v1/claims',
            json={'incident_type': 'motor'},
            headers={**owner, 'Idempotency-Key': 'q65-create'},
        ).json()
        claim_id, session_id = created['claim']['claim_id'], created['session']['session_id']
        url = f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages'
        payload = {
            'client_message_id': 'q65-one-inbound',
            'content': {'type': 'text', 'text': 'A passenger is injured on Symonds Street.'},
        }
        failed_headers = {**owner, 'Idempotency-Key': 'zz-original-failed', 'If-Match': '1'}
        first = client.post(url, headers=failed_headers, json=payload)
        assert first.status_code == 200, first.text
        failed = first.json()
        assert failed['agent_message']['recovery'] is not None
        gateway.fail = False
        success_headers = {
            **owner,
            'Idempotency-Key': 'aa-successful-retry',
            'If-Match': str(failed['current_claim_revision']),
        }
        response = client.post(url, headers=success_headers, json=payload)
        assert response.status_code == 200, response.text
        success = response.json()
        assert success['agent_message']['recovery'] is None
        old_failure = repository.find_idempotency('cus_8f41a2c90d7e463b', url, 'zz-original-failed')
        old_success = repository.find_idempotency(
            'cus_8f41a2c90d7e463b', url, 'aa-successful-retry'
        )
        assert old_failure is not None and old_success is not None
        original_checkpoint = repository.find_message_checkpoint(
            claim_id, failed['claimant_message']['message_id'], 'cus_8f41a2c90d7e463b'
        )
        assert original_checkpoint is not None and original_checkpoint.revision_before_message == 1
        changed = client.patch(
            f'/api/v1/claims/{claim_id}/form',
            headers={**owner, 'If-Match': str(success['current_claim_revision'])},
            json={
                'updates': [
                    {
                        'field_code': 'incident.location',
                        'value': 'Queen Street',
                        'correction_reason': 'The claimant corrected the location.',
                    }
                ]
            },
        )
        assert changed.status_code == 200, changed.text
        current = client.get(f'/api/v1/claims/{claim_id}', headers=owner).json()
        counts = [spy.call_count for spy in spies]
        model_calls = gateway.calls
        for headers, original in (
            (failed_headers, failed),
            (success_headers, success),
            ({**success_headers, 'Idempotency-Key': 'mm-new-client-replay'}, success),
        ):
            replay = client.post(url, headers=headers, json=payload)
            assert replay.status_code == 200, replay.text
            replayed = replay.json()
            assert historical_fields(replayed) == historical_fields(original)
            assert replayed['current_claim_revision'] == current['revision']
            assert replayed['current_claim'] == current
            assert replayed['current_claim']['form']['incident.location']['value'] == 'Queen Street'
        assert gateway.calls == model_calls
        assert [spy.call_count for spy in spies] == counts
        assert (
            repository.find_idempotency('cus_8f41a2c90d7e463b', url, 'zz-original-failed')
            == old_failure
        )
        assert (
            repository.find_idempotency('cus_8f41a2c90d7e463b', url, 'aa-successful-retry')
            == old_success
        )
        assert len(repository.list_handoffs(claim_id, 'cus_8f41a2c90d7e463b')) == 1
