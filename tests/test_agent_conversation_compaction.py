from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import mongomock
import pytest

from backend.domain.models import (
    ActorType,
    Channel,
    CustomerNextStep,
    MessageRecord,
    MessageVisibility,
    ResponsibleParty,
    SessionRecord,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import IdempotencyConflict, PersistenceRepository
from backend.services.conversation_compaction import compact_conversation


def _mongo_repository() -> PersistenceRepository:
    repository = MongoDBRepository(mongomock.MongoClient(), 'northwind_v7_summary_test')
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    return repository


def _repository_factories() -> list[Callable[[], PersistenceRepository]]:
    return [
        FixtureRepository,
        _mongo_repository,
    ]


def _claim_and_session() -> tuple[WorkingClaim, SessionRecord]:
    timestamp = datetime.now(UTC)
    claim = WorkingClaim(
        claim_id='clm_summary',
        customer_id='cus_summary',
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Describe the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )
    session = SessionRecord(
        session_id='ses_summary',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        started_at=timestamp,
        last_active_at=timestamp,
        context_revision=claim.revision,
    )
    claim = claim.model_copy(update={'active_session_id': session.session_id})
    return claim, session


@pytest.mark.parametrize('repository_factory', _repository_factories())
def test_verified_compaction_persists_without_removing_raw_messages(
    repository_factory: Callable[[], PersistenceRepository],
) -> None:
    repository = repository_factory()
    claim, session = _claim_and_session()
    repository.create_claim(claim, session)
    for index in range(12):
        repository.save_message(
            MessageRecord(
                message_id=f'msg_{index:02d}',
                claim_id=claim.claim_id,
                session_id=session.session_id,
                actor=ActorType.CLAIMANT if index % 2 == 0 else ActorType.AGENT,
                visibility=MessageVisibility.CLAIMANT_VISIBLE,
                content={
                    'type': 'text',
                    'text': f'Message {index}: ' + ('bounded reported detail ' * 45),
                },
                created_at=claim.created_at + timedelta(seconds=index),
            ),
            claim.customer_id,
        )

    summary = compact_conversation(
        repository,
        claim.customer_id,
        claim.claim_id,
        session.session_id,
    )

    assert summary is not None
    assert summary.generator_profile_and_version == 'deterministic-verified-compactor@v1'
    assert summary.claim_revision_at_generation == claim.revision
    assert 'reported_history_only' in summary.summary
    assert (
        repository.get_latest_conversation_summary(
            claim.claim_id, session.session_id, claim.customer_id
        )
        == summary
    )
    assert (
        len(repository.list_messages(claim.claim_id, session.session_id, claim.customer_id)) == 12
    )
    assert (
        compact_conversation(
            repository,
            claim.customer_id,
            claim.claim_id,
            session.session_id,
        )
        == summary
    )
    with pytest.raises(IdempotencyConflict):
        repository.save_conversation_summary(
            summary.model_copy(update={'summary': 'Conflicting replacement.'}),
            claim.customer_id,
        )
    assert (
        repository.get_latest_conversation_summary(
            claim.claim_id, session.session_id, claim.customer_id
        )
        == summary
    )


def test_compaction_below_token_threshold_preserves_full_history_without_summary() -> None:
    repository = FixtureRepository()
    claim, session = _claim_and_session()
    repository.create_claim(claim, session)
    for index in range(6):
        repository.save_message(
            MessageRecord(
                message_id=f'msg_short_{index}',
                claim_id=claim.claim_id,
                session_id=session.session_id,
                actor=ActorType.CLAIMANT,
                visibility=MessageVisibility.CLAIMANT_VISIBLE,
                content={'type': 'text', 'text': f'Short message {index}.'},
                created_at=claim.created_at + timedelta(seconds=index),
            ),
            claim.customer_id,
        )

    assert (
        compact_conversation(
            repository,
            claim.customer_id,
            claim.claim_id,
            session.session_id,
        )
        is None
    )
    assert len(repository.list_messages(claim.claim_id, session.session_id, claim.customer_id)) == 6
