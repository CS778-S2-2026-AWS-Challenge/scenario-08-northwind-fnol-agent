from datetime import timedelta
from typing import cast

import pytest
from fastapi.testclient import TestClient

from backend.adapters.claims_service import (
    AdapterIdempotencyConflict,
    ClaimCreationOutcome,
    ClaimsServiceAdapter,
    MockAssessorServiceAdapter,
    MockClaimsServiceAdapter,
)
from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.domain.models import (
    AgentAction,
    AgentAuthority,
    AgentDecisionRecord,
    AuthorityOutcome,
    ClaimCreationStatus,
    CreateExternalClaimRequest,
    CustomerNextStep,
    ExternalClaimResult,
    IntegrationSource,
    ResponsibleParty,
    RouteAssessorRequest,
)
from backend.repositories.fixture import FixtureRepository
from backend.services.support import now_utc

INTEGRATION_AUTH = {'Authorization': 'Bearer synthetic-integration'}


def create_working_claim(client: TestClient, key: str = 'working-claim') -> dict[str, object]:
    response = client.post(
        '/api/v1/claims',
        headers={
            'Authorization': 'Bearer synthetic-claimant',
            'Idempotency-Key': key,
        },
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert response.status_code == 201
    return cast(dict[str, object], response.json())


def save_authorisation(
    repository: FixtureRepository,
    *,
    claim_id: str,
    customer_id: str,
    session_id: str,
    decision_id: str,
    revision: int,
    action: AgentAction,
    reason_code: str,
    outcome: AuthorityOutcome = AuthorityOutcome.AUTHORISED,
) -> None:
    timestamp = now_utc()
    repository.save_agent_decision(
        AgentDecisionRecord(
            decision_id=decision_id,
            claim_id=claim_id,
            session_id=session_id,
            trigger_message_id=f'msg_{decision_id}',
            action=action,
            reason_codes=[reason_code],
            customer_reason='A deterministic rule authorised this fixture action.',
            customer_response='The authorised integration action can continue.',
            customer_next_step=CustomerNextStep(
                status='authorised',
                summary='The authorised integration action can continue.',
                responsible_party=ResponsibleParty.NORTHWIND,
            ),
            authority=AgentAuthority(
                proposed_by='fixture_rule',
                validated_by='deterministic_rule_engine',
                outcome=outcome,
            ),
            resulting_revision=revision,
            created_at=timestamp,
        ),
        customer_id,
    )


def creation_payload(
    claim_id: str,
    revision: int,
    decision_id: str,
    *,
    route: str = 'standard_motor_intake',
) -> dict[str, object]:
    return {
        'working_claim_id': claim_id,
        'claim_revision': revision,
        'authorised_decision_id': decision_id,
        'confirmed_form': {},
        'evidence_refs': [],
        'pending_evidence': [],
        'route': route,
    }


def test_claim_creation_returns_complete_result_and_deduplicates_by_working_claim(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    created = create_working_claim(client)
    claim = created['claim']
    session = created['session']
    assert isinstance(claim, dict)
    assert isinstance(session, dict)
    claim_id = str(claim['claim_id'])
    decision_id = 'dec_create_authorised'
    save_authorisation(
        repository,
        claim_id=claim_id,
        customer_id='cus_demo',
        session_id=str(session['session_id']),
        decision_id=decision_id,
        revision=1,
        action=AgentAction.CREATE_CLAIM,
        reason_code='CLAIM_CREATION_AUTHORISED',
    )
    payload = creation_payload(claim_id, 1, decision_id)

    first = client.post('/internal/v1/claims/create', headers=INTEGRATION_AUTH, json=payload)
    replay = client.post('/internal/v1/claims/create', headers=INTEGRATION_AUTH, json=payload)
    claimant_view = client.get(
        f'/api/v1/claims/{claim_id}',
        headers={'Authorization': 'Bearer synthetic-claimant'},
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json() == first.json()
    body = first.json()
    assert body['claim_number'].startswith('NWF-')
    assert body['creation_status'] == 'created'
    assert body['route'] == 'standard_motor_intake'
    assert body['next_step'] == 'Claims intake review'
    assert body['expected_by'] is not None
    assert body['created_at'] is not None
    assert repository.claim_count == 1
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    assert stored.revision == 2
    assert stored.claim_state.workflow_state.value == 'created'
    assert claimant_view.status_code == 200
    assert claimant_view.json()['external_claim'] == body
    assert 'external_claim_fingerprint' not in claimant_view.json()
    assert 'assessor_routing' not in claimant_view.json()


def test_claim_creation_rejects_claimant_auth_stale_state_and_unauthorised_decision(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    created = create_working_claim(client, 'guarded-claim')
    claim = created['claim']
    session = created['session']
    assert isinstance(claim, dict)
    assert isinstance(session, dict)
    claim_id = str(claim['claim_id'])
    decision_id = 'dec_review_only'
    save_authorisation(
        repository,
        claim_id=claim_id,
        customer_id='cus_demo',
        session_id=str(session['session_id']),
        decision_id=decision_id,
        revision=1,
        action=AgentAction.CREATE_CLAIM,
        reason_code='CLAIM_CREATION_AUTHORISED',
        outcome=AuthorityOutcome.REVIEW_REQUIRED,
    )
    payload = creation_payload(claim_id, 1, decision_id)

    claimant_auth = client.post(
        '/internal/v1/claims/create',
        headers={'Authorization': 'Bearer synthetic-claimant'},
        json=payload,
    )
    unauthorised = client.post(
        '/internal/v1/claims/create',
        headers=INTEGRATION_AUTH,
        json=payload,
    )
    stale = client.post(
        '/internal/v1/claims/create',
        headers=INTEGRATION_AUTH,
        json={**payload, 'claim_revision': 2},
    )

    assert claimant_auth.status_code == 403
    assert claimant_auth.json()['error']['code'] == 'ACCESS_DENIED'
    assert unauthorised.status_code == 409
    assert unauthorised.json()['error']['code'] == 'INVALID_STATE_TRANSITION'
    assert stale.status_code == 409
    assert stale.json()['error']['code'] == 'REVISION_CONFLICT'
    assert repository.get_claim_internal(claim_id).external_claim is None  # type: ignore[union-attr]


def test_claim_creation_rejects_authorisation_from_an_older_revision(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    created = create_working_claim(client, 'old-authorisation')
    claim = created['claim']
    session = created['session']
    assert isinstance(claim, dict)
    assert isinstance(session, dict)
    claim_id = str(claim['claim_id'])
    decision_id = 'dec_old_create_authorisation'
    save_authorisation(
        repository,
        claim_id=claim_id,
        customer_id='cus_demo',
        session_id=str(session['session_id']),
        decision_id=decision_id,
        revision=1,
        action=AgentAction.CREATE_CLAIM,
        reason_code='CLAIM_CREATION_AUTHORISED',
    )
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    repository.save_claim(stored.model_copy(update={'revision': 2}), expected_revision=1)

    response = client.post(
        '/internal/v1/claims/create',
        headers=INTEGRATION_AUTH,
        json=creation_payload(claim_id, 2, decision_id),
    )

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'INVALID_STATE_TRANSITION'
    updated = repository.get_claim_internal(claim_id)
    assert updated is not None
    assert updated.external_claim is None


def test_internal_creation_requires_authentication_and_known_claim(client: TestClient) -> None:
    payload = creation_payload('clm_missing', 1, 'dec_missing')

    missing_auth = client.post('/internal/v1/claims/create', json=payload)
    unknown_claim = client.post(
        '/internal/v1/claims/create',
        headers=INTEGRATION_AUTH,
        json=payload,
    )

    assert missing_auth.status_code == 401
    assert unknown_claim.status_code == 404


def test_claim_creation_rejects_changed_replay_and_unknown_provider_fields(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    created = create_working_claim(client, 'creation-conflict')
    claim = created['claim']
    session = created['session']
    assert isinstance(claim, dict)
    assert isinstance(session, dict)
    claim_id = str(claim['claim_id'])
    decision_id = 'dec_creation_conflict'
    save_authorisation(
        repository,
        claim_id=claim_id,
        customer_id='cus_demo',
        session_id=str(session['session_id']),
        decision_id=decision_id,
        revision=1,
        action=AgentAction.CREATE_CLAIM,
        reason_code='CLAIM_CREATION_AUTHORISED',
    )
    payload = creation_payload(claim_id, 1, decision_id)
    first = client.post('/internal/v1/claims/create', headers=INTEGRATION_AUTH, json=payload)
    changed = client.post(
        '/internal/v1/claims/create',
        headers=INTEGRATION_AUTH,
        json={**payload, 'route': 'different_route'},
    )
    provider_specific = client.post(
        '/internal/v1/claims/create',
        headers=INTEGRATION_AUTH,
        json={**payload, 'dynamodb_table': 'must-not-cross-boundary'},
    )

    assert first.status_code == 201
    assert changed.status_code == 409
    assert changed.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert provider_specific.status_code == 422
    assert provider_specific.json()['error']['code'] == 'VALIDATION_ERROR'


def test_assessor_routing_requires_explicit_authorisation_and_is_idempotent(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    created = create_working_claim(client, 'routed-claim')
    claim = created['claim']
    session = created['session']
    assert isinstance(claim, dict)
    assert isinstance(session, dict)
    claim_id = str(claim['claim_id'])
    session_id = str(session['session_id'])
    create_decision = 'dec_create_for_route'
    save_authorisation(
        repository,
        claim_id=claim_id,
        customer_id='cus_demo',
        session_id=session_id,
        decision_id=create_decision,
        revision=1,
        action=AgentAction.CREATE_CLAIM,
        reason_code='CLAIM_CREATION_AUTHORISED',
    )
    creation = client.post(
        '/internal/v1/claims/create',
        headers=INTEGRATION_AUTH,
        json=creation_payload(claim_id, 1, create_decision),
    ).json()
    route_decision = 'dec_assessor_rule'
    save_authorisation(
        repository,
        claim_id=claim_id,
        customer_id='cus_demo',
        session_id=session_id,
        decision_id=route_decision,
        revision=2,
        action=AgentAction.PROCEED,
        reason_code='ASSESSOR_RULE_AUTHORISED',
    )
    route_payload = {
        'claim_id': claim_id,
        'external_claim_id': creation['external_claim_id'],
        'authorisation_ref': route_decision,
        'requested_action': 'vehicle_damage_assessment',
        'location': {'region': 'Auckland'},
    }

    first = client.post(
        '/internal/v1/assessors/route',
        headers=INTEGRATION_AUTH,
        json=route_payload,
    )
    replay = client.post(
        '/internal/v1/assessors/route',
        headers=INTEGRATION_AUTH,
        json=route_payload,
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json() == first.json()
    body = first.json()
    assert body['routing_status'] == 'assigned'
    assert body['assessor_reference'].startswith('asr_fixture_')
    assert body['queue_reference'].startswith('QUE-AUC-')
    assert body['next_step']
    assert body['expected_by'] is not None
    assert body['limitations']
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    assert stored.revision == 3
    assert stored.customer_next_step.status == 'assessor_assigned'


def test_assessor_routing_is_not_authorised_by_severity_alone(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    created = create_working_claim(client, 'severity-only')
    claim = created['claim']
    session = created['session']
    assert isinstance(claim, dict)
    assert isinstance(session, dict)
    claim_id = str(claim['claim_id'])
    session_id = str(session['session_id'])
    create_decision = 'dec_create_severity'
    save_authorisation(
        repository,
        claim_id=claim_id,
        customer_id='cus_demo',
        session_id=session_id,
        decision_id=create_decision,
        revision=1,
        action=AgentAction.CREATE_CLAIM,
        reason_code='CLAIM_CREATION_AUTHORISED',
    )
    creation = client.post(
        '/internal/v1/claims/create',
        headers=INTEGRATION_AUTH,
        json=creation_payload(claim_id, 1, create_decision),
    ).json()
    severity_decision = 'dec_severity_only'
    save_authorisation(
        repository,
        claim_id=claim_id,
        customer_id='cus_demo',
        session_id=session_id,
        decision_id=severity_decision,
        revision=2,
        action=AgentAction.PROCEED,
        reason_code='COMPLEX_EVENT_REVIEW',
    )

    response = client.post(
        '/internal/v1/assessors/route',
        headers=INTEGRATION_AUTH,
        json={
            'claim_id': claim_id,
            'external_claim_id': creation['external_claim_id'],
            'authorisation_ref': severity_decision,
            'requested_action': 'vehicle_damage_assessment',
            'location': {'region': 'Auckland'},
        },
    )

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'INVALID_STATE_TRANSITION'


class PendingClaimsAdapter(ClaimsServiceAdapter):
    def create_claim(
        self,
        command: CreateExternalClaimRequest,
        request_fingerprint: str,
    ) -> ClaimCreationOutcome:
        del command, request_fingerprint
        timestamp = now_utc()
        return ClaimCreationOutcome(
            result=ExternalClaimResult(
                creation_status=ClaimCreationStatus.PENDING,
                route='provider_neutral_pending',
                next_step='Wait for the claims service confirmation.',
                source=IntegrationSource.CONFIGURED_SERVICE,
                expected_by=timestamp + timedelta(hours=2),
                created_at=timestamp,
            ),
            replayed=False,
        )


def test_app_accepts_replaceable_claims_adapter_without_public_schema_changes() -> None:
    repository = FixtureRepository()
    settings = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)
    app = create_app(
        settings,
        repository=repository,
        claims_service_adapter=PendingClaimsAdapter(),
    )
    with TestClient(app) as client:
        created = create_working_claim(client, 'replaceable-adapter')
        claim = created['claim']
        session = created['session']
        assert isinstance(claim, dict)
        assert isinstance(session, dict)
        claim_id = str(claim['claim_id'])
        decision_id = 'dec_pending_adapter'
        save_authorisation(
            repository,
            claim_id=claim_id,
            customer_id='cus_demo',
            session_id=str(session['session_id']),
            decision_id=decision_id,
            revision=1,
            action=AgentAction.CREATE_CLAIM,
            reason_code='CLAIM_CREATION_AUTHORISED',
        )
        response = client.post(
            '/internal/v1/claims/create',
            headers=INTEGRATION_AUTH,
            json=creation_payload(claim_id, 1, decision_id),
        )

    assert response.status_code == 201
    assert response.json()['creation_status'] == 'pending'
    assert response.json()['external_claim_id'] is None
    assert response.json()['claim_number'] is None
    assert response.json()['source'] == 'configured_service'
