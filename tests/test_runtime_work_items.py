from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.domain.models import (
    ActorReference,
    ActorType,
    Channel,
    ClaimState,
    CustomerNextStep,
    FormSource,
    FormStatus,
    NeededFor,
    ResponsibleParty,
    StructuredFormField,
    WorkingClaim,
)
from backend.domain.runtime import RuntimeWorkItemRecord
from backend.repositories.fixture import FixtureRepository
from backend.repositories.protocols import PersistenceRepository
from backend.services.agent import ControlledAgent
from backend.services.runtime_work_items import current_runtime_work_items

CLAIMANT_HEADERS = {'Authorization': 'Bearer synthetic-claimant'}
STAFF_HEADERS = {'Authorization': 'Bearer synthetic-staff'}


def test_runtime_work_items_reconcile_latest_subject_and_completed_fact() -> None:
    now = datetime.now(UTC)
    records = [
        RuntimeWorkItemRecord(
            work_item_id='wki_old',
            claim_id='clm_1',
            turn_id='turn_1',
            kind='question',
            subject_ref='incident.location',
            owner='claimant',
            status='open',
            blocks_action='provide_incident_location',
            source_refs=['msg_1'],
            created_at=now - timedelta(minutes=2),
            updated_at=now - timedelta(minutes=2),
        ),
        RuntimeWorkItemRecord(
            work_item_id='wki_latest',
            claim_id='clm_1',
            turn_id='turn_2',
            kind='question',
            subject_ref='incident.location',
            owner='claimant',
            status='open',
            blocks_action='provide_incident_location',
            source_refs=['msg_2'],
            created_at=now - timedelta(minutes=1),
            updated_at=now - timedelta(minutes=1),
        ),
    ]
    repository = cast(
        PersistenceRepository,
        SimpleNamespace(list_runtime_work_items=lambda _claim, _customer: records),
    )
    claim = WorkingClaim(
        claim_id='clm_1',
        customer_id='cus_1',
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        claim_state=ClaimState(),
        form={
            'incident.location': StructuredFormField(
                source=FormSource.CLAIMANT,
                status=FormStatus.CONFIRMED,
                value='Symonds Street',
                needed_for=NeededFor.CURRENT_ACTION,
                updated_at=now,
                updated_by=ActorReference(actor_type=ActorType.CLAIMANT, actor_id='cus_1'),
            )
        },
        customer_next_step=CustomerNextStep(
            status='continue_intake',
            summary='Continue the Claim.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=now,
        updated_at=now,
    )

    projected = current_runtime_work_items(repository, claim)

    assert len(projected) == 1
    assert projected[0].work_item_id == 'wki_latest'
    assert projected[0].status == 'completed'
    assert projected[0].completed_at is not None


def test_runtime_work_item_endpoint_is_staff_only_and_projects_current_claim_state() -> None:
    repository = FixtureRepository()
    app = create_app(
        Settings(environment='test', identity_mode=IdentityMode.DEVELOPER),
        repository=repository,
        agent_turn_provider=ControlledAgent(),
    )
    with TestClient(app) as client:
        created = client.post(
            '/api/v1/claims',
            headers={**CLAIMANT_HEADERS, 'Idempotency-Key': 'runtime-work-item-claim'},
            json={'channel': 'web_agent', 'locale': 'en-NZ'},
        )
        assert created.status_code == 201, created.text
        claim = created.json()['claim']
        session = created.json()['session']
        turn = client.post(
            f'/api/v1/claims/{claim["claim_id"]}/sessions/{session["session_id"]}/messages',
            headers={
                **CLAIMANT_HEADERS,
                'Idempotency-Key': 'runtime-work-item-turn',
                'If-Match': str(claim['revision']),
            },
            json={
                'client_message_id': 'runtime-work-item-message',
                'content': {'type': 'text', 'text': 'My car was hit yesterday.'},
            },
        )
        assert turn.status_code == 200, turn.text

        claimant_read = client.get(
            f'/api/v1/workbench/claims/{claim["claim_id"]}/runtime-work-items',
            headers=CLAIMANT_HEADERS,
        )
        staff_read = client.get(
            f'/api/v1/workbench/claims/{claim["claim_id"]}/runtime-work-items',
            headers=STAFF_HEADERS,
        )

    assert claimant_read.status_code == 403
    assert claimant_read.json()['error']['code'] == 'ACCESS_DENIED'
    assert staff_read.status_code == 200, staff_read.text
    assert staff_read.json()['items']
    assert all('needed_for' not in item for item in staff_read.json()['items'])
    assert all(item['source_refs'] for item in staff_read.json()['items'])
