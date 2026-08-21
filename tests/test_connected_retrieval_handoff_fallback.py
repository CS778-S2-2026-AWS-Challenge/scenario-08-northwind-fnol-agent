import json

from fastapi.testclient import TestClient

from backend.adapters.handoff_dispatch import (
    HandoffDispatchUnavailable,
    MockHandoffDispatchAdapter,
)
from backend.adapters.policy_history import (
    MockPolicyHistoryAdapter,
    RetrievalUnavailable,
)
from backend.app import create_app
from backend.core.config import Settings
from backend.repositories.fixture import FixtureRepository

CLAIMANT_AUTH = {'Authorization': 'Bearer synthetic-claimant'}
STAFF_AUTH = {'Authorization': 'Bearer synthetic-staff'}
INTEGRATION_AUTH = {'Authorization': 'Bearer synthetic-integration'}
INCIDENT_DESCRIPTION = (
    'My parked car was hit at low speed and I want help '
    'continuing the report.'
)


def test_retrieval_and_dispatch_outages_fail_closed_without_losing_handoff_context() -> (
    None
):
    repository = FixtureRepository()
    retrieval = MockPolicyHistoryAdapter()
    dispatch = MockHandoffDispatchAdapter()
    app = create_app(
        Settings(),
        repository,
        policy_history_adapter=retrieval,
        handoff_dispatch_adapter=dispatch,
    )

    with TestClient(app) as client:
        created = client.post(
            '/api/v1/claims',
            headers={**CLAIMANT_AUTH, 'Idempotency-Key': 'connected-fallback-claim'},
            json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
        )
        assert created.status_code == 201, created.text
        claim_id = created.json()['claim']['claim_id']

        context = client.patch(
            f'/api/v1/claims/{claim_id}/form',
            headers={**CLAIMANT_AUTH, 'If-Match': '1'},
            json={
                'updates': [
                    {
                        'field_code': 'incident.description',
                        'value': INCIDENT_DESCRIPTION,
                        'status': 'confirmed',
                    }
                ]
            },
        )
        assert context.status_code == 200, context.text
        assert context.json()['revision'] == 2

        retrieval.set_outage(
            RetrievalUnavailable(
                code='PROVIDER_TIMEOUT',
                detail='The policy provider did not respond within the request budget.',
            )
        )
        lookup = client.post(
            '/internal/v1/policy/search',
            headers=INTEGRATION_AUTH,
            json={'claim_id': claim_id, 'policy_reference': 'synthetic-policy-101'},
        )

        dispatch.set_outage(
            HandoffDispatchUnavailable(
                code='DISPATCH_UNAVAILABLE',
                detail='The staff queue service refused the connection.',
            )
        )
        support_headers = {
            **CLAIMANT_AUTH,
            'Idempotency-Key': 'connected-fallback-support',
            'If-Match': '2',
        }
        support_payload = {
            'reason': 'I want a person to continue this report.',
            'support_need': 'human_requested',
            'preferred_channel': 'phone',
        }
        degraded = client.post(
            f'/api/v1/claims/{claim_id}/support-requests',
            headers=support_headers,
            json=support_payload,
        )
        workbench = client.get(
            f'/api/v1/workbench/claims/{claim_id}', headers=STAFF_AUTH
        )
        claimant = client.get(f'/api/v1/claims/{claim_id}', headers=CLAIMANT_AUTH)

        replay = client.post(
            f'/api/v1/claims/{claim_id}/support-requests',
            headers=support_headers,
            json=support_payload,
        )

        dispatch.set_outage(None)
        recovered = client.post(
            f'/api/v1/claims/{claim_id}/support-requests',
            headers=support_headers,
            json=support_payload,
        )
        readiness = client.get('/health/ready')

    assert lookup.status_code == 200
    assert lookup.json()['status'] == 'unavailable'
    assert lookup.json()['facts'] is None
    assert lookup.json()['source'] is None
    assert lookup.json()['limitations'] == [
        'The policy provider did not respond within the request budget.'
    ]
    assert repository.list_retrieval_records(claim_id, 'cus_demo') == []
    assert repository.list_review_signals(claim_id, 'cus_demo') == []

    assert degraded.status_code == 201
    degraded_body = degraded.json()
    assert degraded_body['delivery']['state'] == 'queued_locally'
    assert degraded_body['revision'] == 3
    handoff_id = degraded_body['handoff']['handoff_id']

    assert workbench.status_code == 200
    detail = workbench.json()
    assert len(detail['handoffs']) == 1
    handoff = detail['handoffs'][0]
    assert handoff['handoff_id'] == handoff_id
    assert handoff['status'] == 'queued'
    assert handoff['support_need'] == 'human_requested'
    assert handoff['packet']['incident_summary'] == INCIDENT_DESCRIPTION
    assert handoff['packet']['form_snapshot']['incident.description']['value'] == (
        INCIDENT_DESCRIPTION
    )
    assert (
        handoff['packet']['form_snapshot']['incident.description']['source'] == 'claimant'
    )

    assert claimant.status_code == 200
    claimant_text = json.dumps(claimant.json()).lower()
    assert 'provider_timeout' not in claimant_text
    assert 'policy provider did not respond' not in claimant_text
    assert 'fixture_policy_administration' not in claimant_text

    assert replay.status_code == 201
    assert replay.json() == degraded_body

    assert recovered.status_code == 201
    recovered_body = recovered.json()
    assert recovered_body['delivery']['state'] == 'delivered'
    assert recovered_body['handoff']['handoff_id'] == handoff_id
    assert recovered_body['revision'] == 3

    handoffs = repository.list_handoffs(claim_id, 'cus_demo')
    stored_claim = repository.get_claim(claim_id, 'cus_demo')
    assert len(handoffs) == 1
    assert handoffs[0].handoff_id == handoff_id
    assert stored_claim is not None
    assert stored_claim.revision == 3

    assert readiness.status_code == 200
    assert readiness.json()['checks']['policy'] == 'unavailable'
    assert readiness.json()['checks']['handoff_dispatch'] == 'using_fixture'
