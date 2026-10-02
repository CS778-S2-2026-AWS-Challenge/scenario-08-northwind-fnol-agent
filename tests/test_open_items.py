"""What is still owed on a Claim, by whom, and what each turn recorded."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.auth import STAFF_SCOPES, Principal
from backend.core.errors import ApiError
from backend.domain.agent_v8 import V8DocumentRequest
from backend.domain.models import (
    ActorType,
    CustomerUpdateRecord,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    MessageRecord,
    MessageVisibility,
    OpenItemOwner,
    OpenItemState,
    ResponsibleParty,
)
from backend.domain.open_items import (
    claimant_message_content,
    model_message_content,
    staff_open_items,
)
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import InvariantGuardedAgent
from backend.services.claimant_questions import (
    AnswerClaimantQuestionRequest,
    answer_claimant_question,
)
from backend.services.turn_reducer import document_stance_evidence
from backend.services.workbench import get_workbench_claim_detail
from tests.journey_v8_support import Journey, V8JourneyProvider, envelope, fact
from tests.test_claim_decisions import _store_created_claim

NOW = datetime(2026, 10, 1, 4, 40, tzinfo=UTC)
QUESTION = {
    'question_id': 'nwq_hire',
    'question': 'Is my hire car covered?',
    'claimant_wording': 'will you pay for a hire car',
    'model_view': 'No hire-car clause in the excerpts.',
}


def _staff() -> Principal:
    return Principal(
        subject='stf_demo',
        actor_type='staff',
        scopes=STAFF_SCOPES,
        roles=frozenset({'claims_professional'}),
        auth_source='test:staff',
    )


def _agent_message(
    claim_id: str, session_id: str, record: dict[str, Any], at: datetime = NOW
) -> MessageRecord:
    return MessageRecord(
        message_id=f'msg_{len(str(record))}_{at.timestamp():.0f}',
        claim_id=claim_id,
        session_id=session_id,
        actor=ActorType.AGENT,
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': 'Noted.', 'turn_record': record},
        created_at=at,
    )


def _evidence(
    evidence_id: str,
    kind: str,
    status: EvidenceStatus,
    file_status: EvidenceFileStatus,
    party: ResponsibleParty | None = None,
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        claim_id='clm_items',
        kind=kind,
        status=status,
        file_status=file_status,
        media_type='image/jpeg' if file_status is EvidenceFileStatus.READY else None,
        source=EvidenceSource.CLAIMANT,
        responsible_party=party,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.parametrize(
    ('stance', 'status', 'party'),
    [
        ('will_send_later', EvidenceStatus.PENDING, ResponsibleParty.CLAIMANT),
        ('does_not_have', EvidenceStatus.UNAVAILABLE, ResponsibleParty.CLAIMANT),
        ('third_party', EvidenceStatus.PENDING, ResponsibleParty.EXTERNAL_PARTY),
    ],
)
def test_the_claimants_stance_settles_who_owes_a_document(
    stance: str, status: EvidenceStatus, party: ResponsibleParty
) -> None:
    claim = SimpleNamespace(claim_id='clm_items')
    message = SimpleNamespace(message_id='msg_1', content={'text': 'Tomorrow, probably.'})
    turn = SimpleNamespace(
        document_requests=(
            V8DocumentRequest(
                document_kind='repair_quote',
                stance=stance,
                service_identity='repairer_quote' if stance == 'third_party' else None,
            ),
        )
    )

    record = document_stance_evidence(claim, turn, message, NOW, [])  # type: ignore[arg-type]

    assert record is not None
    assert (record.kind, record.status, record.responsible_party) == (
        'repair_quote',
        status,
        party,
    )
    # One record per kind: it is not owed twice.
    assert document_stance_evidence(claim, turn, message, NOW, [record]) is None  # type: ignore[arg-type]


def test_asking_or_an_unregistered_kind_records_nothing() -> None:
    claim = SimpleNamespace(claim_id='clm_items')
    message = SimpleNamespace(message_id='msg_1', content={'text': 'ok'})
    for request in (
        V8DocumentRequest(document_kind='repair_quote', stance='asking'),
        V8DocumentRequest(document_kind='towing_invoice', stance='will_send_later'),
    ):
        turn = SimpleNamespace(document_requests=(request,))
        assert document_stance_evidence(claim, turn, message, NOW, []) is None  # type: ignore[arg-type]


def test_open_items_follow_stored_records_and_the_models_file_reading() -> None:
    owed = _evidence(
        'evd_quote',
        'repair_quote',
        EvidenceStatus.PENDING,
        EvidenceFileStatus.NOT_AVAILABLE,
        ResponsibleParty.CLAIMANT,
    )
    chat_file = _evidence(
        'evd_chat', 'other_document', EvidenceStatus.RECEIVED, EvidenceFileStatus.READY
    )
    opened = _agent_message('clm_items', 'ses_1', {'opened_items': ['evd_quote']})
    question = _agent_message(
        'clm_items', 'ses_1', {'northwind_questions': [QUESTION]}, NOW + timedelta(minutes=1)
    )

    items = staff_open_items([owed, chat_file], [opened, question])
    assert [(item.kind, item.owner, item.state) for item in items] == [
        ('document', OpenItemOwner.CLAIMANT, OpenItemState.OPEN),
        ('question', OpenItemOwner.NORTHWIND, OpenItemState.OPEN),
    ]
    assert items[0].opened_in_message_id == opened.message_id
    assert items[1].model_view == QUESTION['model_view']

    # The model reads the chat file as the quote; a staff update answers the question.
    read = _agent_message(
        'clm_items',
        'ses_1',
        {'file_reads': [{'evidence_id': 'evd_chat', 'kind': 'repair_quote'}]},
        NOW + timedelta(minutes=2),
    )
    answer = CustomerUpdateRecord(
        update_id='cup_1',
        claim_id='clm_items',
        summary='Yes, up to 14 days.',
        responsible_party=ResponsibleParty.CLAIMS_PROFESSIONAL,
        related_refs=['nwq_hire'],
        created_by='stf_demo',
        created_at=NOW + timedelta(minutes=3),
    )
    settled = staff_open_items([owed, chat_file], [opened, question, read], [answer])
    assert [item.state for item in settled] == [OpenItemState.DONE, OpenItemState.DONE]
    assert settled[1].answer == 'Yes, up to 14 days.'


def test_the_claimant_never_reads_the_models_view_and_the_model_rereads_only_words() -> None:
    content = {
        'type': 'text',
        'text': 'I have passed that on.',
        'turn_record': {
            'recorded_facts': [{'field_code': 'incident.location'}],
            'northwind_questions': [QUESTION],
            'opened_items': ['nwq_hire'],
            'ending': 'card',
        },
    }

    claimant = claimant_message_content(content)
    assert 'northwind_questions' not in claimant['turn_record']
    assert claimant['turn_record']['opened_items'] == ['nwq_hire']
    assert 'No hire-car clause' not in str(claimant)
    assert model_message_content(content) == {'type': 'text', 'text': 'I have passed that on.'}


def test_staff_answer_a_question_once_and_it_reaches_the_claimant() -> None:
    repository = FixtureRepository()
    claim = _store_created_claim(repository, 'clm_answer')
    repository.save_message(
        _agent_message(
            claim.claim_id,
            claim.active_session_id or '',
            {
                'northwind_questions': [QUESTION],
                'opened_items': ['nwq_hire'],
                'file_reads': [{'evidence_id': 'evd_chat', 'kind': 'incident_photo'}],
            },
        ),
        claim.customer_id,
    )
    detail = get_workbench_claim_detail(repository, _staff(), claim.claim_id)
    assert detail.file_readings == {'evd_chat': 'incident_photo'}
    assert any(
        action.action_code == 'conversation.answer_claimant_question'
        and action.target_ref == 'nwq_hire'
        for action in detail.allowed_actions
    )

    response = answer_claimant_question(
        repository,
        _staff(),
        claim.claim_id,
        'nwq_hire',
        AnswerClaimantQuestionRequest(answer='Yes, hire car cover applies for 14 days.'),
        'answer-1',
        str(detail.revision),
    )

    assert response.update.related_refs == ['nwq_hire']
    after = get_workbench_claim_detail(repository, _staff(), claim.claim_id)
    question = next(item for item in after.open_items if item.item_id == 'nwq_hire')
    assert question.state is OpenItemState.DONE
    assert not any(
        action.action_code == 'conversation.answer_claimant_question'
        for action in after.allowed_actions
    )
    with pytest.raises(ApiError) as raised:
        answer_claimant_question(
            repository,
            _staff(),
            claim.claim_id,
            'nwq_hire',
            AnswerClaimantQuestionRequest(answer='Again.'),
            'answer-2',
            str(after.revision),
        )
    assert raised.value.code == 'QUESTION_NOT_OPEN'


def test_a_turn_records_its_facts_and_opens_items_the_claimant_can_see(
    app: FastAPI, client: TestClient, repository: FixtureRepository
) -> None:
    provider = V8JourneyProvider(
        [
            {
                **envelope(
                    fields=[
                        fact('claim.product_family', 'motor', 'rear-ended'),
                        fact('incident.location', 'Queen Street', 'on Queen Street'),
                    ],
                    documents=[
                        {
                            'document_kind': 'repair_quote',
                            'stance': 'will_send_later',
                            'service_identity': None,
                        }
                    ],
                    reply='Thanks, I have that. Send the quote when you have it.',
                ),
                'northwind_questions': [
                    {key: QUESTION[key] for key in ('question', 'claimant_wording', 'model_view')}
                ],
                'turn_ending': 'card',
            }
        ]
    )
    app.state.agent_turn_provider = InvariantGuardedAgent(provider)
    journey = Journey(client, 'motor', 'open-items')

    turn = journey.send(
        "I was rear-ended on Queen Street. I'll get a repair quote tomorrow. "
        'Will you pay for a hire car?'
    )

    record = turn['agent_message']['content']['turn_record']
    assert {item['field_code'] for item in record['recorded_facts']} >= {'incident.location'}
    assert record['ending'] == 'card'
    assert 'northwind_questions' not in record
    items = journey.view()['open_items']
    assert [(item['kind'], item['owner'], item['state']) for item in items] == [
        ('document', 'claimant', 'open'),
        ('question', 'northwind', 'open'),
    ]
    assert {item['opened_in_message_id'] for item in items} == {turn['agent_message']['message_id']}
    assert 'model_view' not in items[1]
