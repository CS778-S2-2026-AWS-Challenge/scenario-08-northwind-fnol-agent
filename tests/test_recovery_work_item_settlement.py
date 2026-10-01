from datetime import UTC, datetime, timedelta

import mongomock
import pytest

from backend.domain.models import (
    Channel,
    ClaimState,
    CustomerNextStep,
    ResponsibleParty,
    SessionRecord,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import PersistenceRepository
from backend.services.recovery_decisions import (
    build_recovery_work_item,
    reduce_external_unknown_recovery,
)

NOW = datetime(2026, 9, 30, 0, 0, tzinfo=UTC)


def _repository(kind: str) -> PersistenceRepository:
    if kind == 'fixture':
        return FixtureRepository()
    repository = MongoDBRepository(
        mongomock.MongoClient(),
        f'recovery_work_item_{kind}',
    )
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    return repository


def _seed_claim(repository: PersistenceRepository) -> WorkingClaim:
    claim = WorkingClaim(
        claim_id='clm_recovery_work_item',
        customer_id='cus_recovery_work_item',
        revision=1,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        claim_state=ClaimState(),
        active_session_id='ses_recovery_work_item',
        customer_next_step=CustomerNextStep(
            status='waiting_external',
            summary='Waiting for the existing external operation.',
            responsible_party=ResponsibleParty.EXTERNAL_PARTY,
        ),
        created_at=NOW,
        updated_at=NOW,
    )
    session = SessionRecord(
        session_id='ses_recovery_work_item',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        context_revision=claim.revision,
        started_at=NOW,
        last_active_at=NOW,
    )
    repository.create_claim(claim, session)
    return claim


@pytest.mark.parametrize('kind', ['fixture', 'mongo'])
def test_external_reconciliation_settles_same_logical_work_item(
    kind: str,
) -> None:
    repository = _repository(kind)
    claim = _seed_claim(repository)

    opened_transition = reduce_external_unknown_recovery(
        claim_id=claim.claim_id,
        claim_revision=claim.revision,
        operation_id='op_external_same',
        delivery_state='submitted',
        event_id='external-recovery:attempt',
        source_refs=['external-task:task-1'],
        now=NOW,
    )
    opened = build_recovery_work_item(
        opened_transition,
        claim_id=claim.claim_id,
        subject_ref='external-task:task-1',
        now=NOW,
    )
    assert opened is not None
    repository.save_runtime_work_item(opened, claim.customer_id)

    completion_transition = reduce_external_unknown_recovery(
        claim_id=claim.claim_id,
        claim_revision=claim.revision,
        operation_id='op_external_same',
        delivery_state='submitted',
        event_id='external-recovery-complete:attempt',
        source_refs=['external-task:task-1', 'provider:confirmed'],
        now=NOW + timedelta(minutes=1),
    )
    completion = build_recovery_work_item(
        completion_transition,
        claim_id=claim.claim_id,
        subject_ref='external-task:task-1',
        now=NOW + timedelta(minutes=1),
        status='completed',
    )
    assert completion is not None

    assert completion.work_item_id == opened.work_item_id

    settled = opened.model_copy(
        update={
            'status': 'completed',
            'blocks_action': None,
            'source_refs': list(dict.fromkeys([*opened.source_refs, *completion.source_refs])),
            'updated_at': NOW + timedelta(minutes=1),
            'completed_at': NOW + timedelta(minutes=1),
        }
    )
    repository.save_runtime_work_item(settled, claim.customer_id)

    stored = repository.list_runtime_work_items(
        claim.claim_id,
        claim.customer_id,
    )
    assert stored == [settled]
