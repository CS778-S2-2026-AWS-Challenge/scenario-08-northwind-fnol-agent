from collections.abc import Iterator
from datetime import UTC, datetime

import mongomock
import pytest

from backend.core.auth import Principal
from backend.domain.models import (
    ActorType,
    Channel,
    CustomerNextStep,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    MessageRecord,
    MessageVisibility,
    ResponsibleParty,
    SessionRecord,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
)
from backend.services.message_history import list_claim_messages
from backend.services.workbench import list_workbench_messages


@pytest.fixture(params=('fixture', 'mongodb'))
def repository(request: pytest.FixtureRequest) -> Iterator[PersistenceRepository]:
    if request.param == 'fixture':
        yield FixtureRepository()
        return

    mongo = MongoDBRepository(mongomock.MongoClient(), f'record_integrity_{request.node.name}')
    mongo._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    yield mongo


def _claim_graph(
    repository: PersistenceRepository,
    *,
    suffix: str = 'primary',
    customer_id: str = 'cus_integrity',
) -> tuple[WorkingClaim, SessionRecord]:
    timestamp = datetime(2026, 9, 21, 8, 0, tzinfo=UTC)
    session_id = f'ses_integrity_{suffix}'
    claim = WorkingClaim(
        claim_id=f'clm_integrity_{suffix}',
        customer_id=customer_id,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        active_session_id=session_id,
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Describe the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )
    session = SessionRecord(
        session_id=session_id,
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        started_at=timestamp,
        last_active_at=timestamp,
    )
    repository.create_claim(claim, session)
    return claim, session


def _evidence(claim: WorkingClaim, evidence_id: str = 'evd_integrity') -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        claim_id=claim.claim_id,
        kind='incident_image',
        status=EvidenceStatus.RECEIVED,
        file_status=EvidenceFileStatus.READY,
        source=EvidenceSource.CLAIMANT,
        related_fields=['incident.description'],
        needed_for=['current_action'],
        created_at=claim.created_at,
        updated_at=claim.updated_at,
    )


def _message(
    claim: WorkingClaim,
    session: SessionRecord,
    message_id: str,
    *,
    actor: ActorType = ActorType.CLAIMANT,
    evidence_refs: list[str] | None = None,
    in_reply_to: str | None = None,
) -> MessageRecord:
    return MessageRecord(
        message_id=message_id,
        claim_id=claim.claim_id,
        session_id=session.session_id,
        client_message_id=f'client-{message_id}' if actor is ActorType.CLAIMANT else None,
        actor=actor,
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': message_id},
        evidence_refs=evidence_refs or [],
        in_reply_to=in_reply_to,
        created_at=claim.created_at,
    )


@pytest.mark.parametrize(
    ('update', 'match'),
    (
        ({'kind': 'unregistered_kind'}, 'Unregistered Evidence kind'),
        (
            {'related_fields': ['incident.description', 'incident.description']},
            'related_fields must not contain duplicates',
        ),
        ({'related_fields': ['unregistered.field']}, 'Unregistered Evidence related_fields'),
        (
            {'needed_for': ['current_action', 'current_action']},
            'needed_for must not contain duplicates',
        ),
        ({'needed_for': ['unregistered_need']}, 'Unregistered Evidence needed_for'),
        (
            {
                'status': EvidenceStatus.MISSING,
                'file_status': EvidenceFileStatus.READY,
            },
            'not a registered evidence shape',
        ),
    ),
)
def test_evidence_write_boundaries_reject_unregistered_or_contradictory_records(
    repository: PersistenceRepository,
    update: dict[str, object],
    match: str,
) -> None:
    claim, _session = _claim_graph(repository)
    evidence = _evidence(claim).model_copy(update=update)

    with pytest.raises(ValueError, match=match):
        repository.save_evidence(evidence, claim.customer_id)

    assert repository.get_evidence(claim.claim_id, evidence.evidence_id, claim.customer_id) is None


@pytest.mark.parametrize('kind', ('item_photo', 'photo', 'document'))
def test_existing_production_evidence_kinds_remain_registered(
    repository: PersistenceRepository,
    kind: str,
) -> None:
    claim, _session = _claim_graph(repository)
    evidence = _evidence(claim).model_copy(
        update={
            'evidence_id': f'evd_{kind}',
            'kind': kind,
        }
    )

    repository.save_evidence(evidence, claim.customer_id)

    assert (
        repository.get_evidence(claim.claim_id, evidence.evidence_id, claim.customer_id) == evidence
    )


def test_message_write_boundaries_reject_missing_duplicate_and_foreign_evidence(
    repository: PersistenceRepository,
) -> None:
    claim, session = _claim_graph(repository)
    foreign_claim, _foreign_session = _claim_graph(repository, suffix='foreign')
    own = _evidence(claim)
    foreign = _evidence(foreign_claim, 'evd_integrity_foreign')
    repository.save_evidence(own, claim.customer_id)
    repository.save_evidence(foreign, foreign_claim.customer_id)

    invalid_references = (
        ['evd_missing'],
        [own.evidence_id, own.evidence_id],
        [foreign.evidence_id],
    )
    for index, evidence_refs in enumerate(invalid_references):
        message = _message(
            claim,
            session,
            f'msg_invalid_evidence_{index}',
            evidence_refs=evidence_refs,
        )
        with pytest.raises(ValueError, match='[Ee]vidence'):
            repository.save_message(message, claim.customer_id)


def test_message_write_boundaries_reject_invalid_reply_actor_and_visibility(
    repository: PersistenceRepository,
) -> None:
    claim, session = _claim_graph(repository)
    second_session = session.model_copy(update={'session_id': 'ses_integrity_second'})
    repository.save_session(second_session)
    target = _message(claim, second_session, 'msg_second_session')
    repository.save_message(target, claim.customer_id)

    invalid_messages = (
        _message(claim, session, 'msg_self_reply').model_copy(
            update={'in_reply_to': 'msg_self_reply'}
        ),
        _message(claim, session, 'msg_cross_session', in_reply_to=target.message_id),
        _message(claim, session, 'msg_agent_client_id', actor=ActorType.AGENT).model_copy(
            update={'client_message_id': 'agent-client-id'}
        ),
        _message(claim, session, 'msg_claimant_internal').model_copy(
            update={'visibility': MessageVisibility.INTERNAL_ONLY}
        ),
    )
    expected = ('reply', 'reply', 'client_message_id', 'actor and visibility')
    for message, match in zip(invalid_messages, expected, strict=True):
        with pytest.raises(ValueError, match=match):
            repository.save_message(message, claim.customer_id)


def test_claimant_retry_identity_is_unique_within_claim(
    repository: PersistenceRepository,
) -> None:
    claim, session = _claim_graph(repository)
    original = _message(claim, session, 'msg_original')
    repository.save_message(original, claim.customer_id)
    duplicate = original.model_copy(update={'message_id': 'msg_duplicate'})

    with pytest.raises(IdempotencyConflict):
        repository.save_message(duplicate, claim.customer_id)


def test_invalid_message_mutation_leaves_complete_provider_state_unchanged(
    repository: PersistenceRepository,
) -> None:
    claim, session = _claim_graph(repository)
    updated_claim = claim.model_copy(
        update={'revision': 2, 'updated_at': claim.updated_at.replace(minute=1)}
    )
    updated_session = session.model_copy(
        update={
            'context_revision': 2,
            'last_active_at': session.last_active_at.replace(minute=1),
        }
    )
    invalid = _message(claim, session, 'msg_invalid_atomic').model_copy(
        update={'visibility': MessageVisibility.INTERNAL_ONLY}
    )
    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route='/integrity/messages',
        key='invalid-message-atomicity',
        request_fingerprint='invalid-message-atomicity',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        message_id=invalid.message_id,
    )

    def snapshot() -> object:
        if isinstance(repository, FixtureRepository):
            return (
                repository.get_claim_internal(claim.claim_id),
                repository.get_session(claim.claim_id, session.session_id, claim.customer_id),
                repository.list_messages(claim.claim_id, session.session_id, claim.customer_id),
                dict(repository._message_ids_by_session),
                dict(repository._idempotency),
                repository.replay_realtime_events(None, limit=1000),
            )
        assert isinstance(repository, MongoDBRepository)
        return list(repository._collection.find().sort('_id', 1))

    before = snapshot()
    with pytest.raises(ValueError, match='actor and visibility'):
        repository.save_message_mutation(
            updated_claim,
            claim.revision,
            updated_session,
            invalid,
            idempotency,
        )

    assert snapshot() == before


def test_valid_message_evidence_reply_and_projection_order_are_provider_neutral(
    repository: PersistenceRepository,
) -> None:
    claim, session = _claim_graph(repository)
    evidence = _evidence(claim)
    repository.save_evidence(evidence, claim.customer_id)
    claimant = _message(
        claim,
        session,
        'msg_z_claimant',
        evidence_refs=[evidence.evidence_id],
    )
    agent = _message(
        claim,
        session,
        'msg_a_agent',
        actor=ActorType.AGENT,
        in_reply_to=claimant.message_id,
    )
    repository.save_message(claimant, claim.customer_id)
    repository.save_message(agent, claim.customer_id)

    stored = repository.get_message(
        claim.claim_id,
        session.session_id,
        claimant.message_id,
        claim.customer_id,
    )
    assert stored == claimant
    claimant_page = list_claim_messages(
        repository,
        Principal(subject=claim.customer_id, actor_type='claimant'),
        claim.claim_id,
        session.session_id,
        limit=10,
        cursor=None,
        before=None,
        after=None,
    )
    workbench_page = list_workbench_messages(
        repository,
        Principal(subject='stf_integrity', actor_type='staff'),
        claim.claim_id,
        session.session_id,
        limit=10,
        cursor=None,
    )

    expected_order = ['msg_z_claimant', 'msg_a_agent']
    assert [item.message_id for item in claimant_page.items] == expected_order
    assert [item.message_id for item in workbench_page.items] == expected_order
    assert workbench_page.items[1].in_reply_to == claimant.message_id
