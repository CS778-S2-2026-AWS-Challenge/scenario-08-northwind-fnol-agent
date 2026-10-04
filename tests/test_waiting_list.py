"""The waiting list: staff join after collection, settle items, and own the reply."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.core.auth import STAFF_SCOPES, Principal
from backend.core.errors import ApiError
from backend.domain.models import (
    ActorType,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    MessageRecord,
    MessageVisibility,
    OpenItemState,
)
from backend.domain.open_items import interpreted_evidence_kinds
from backend.repositories.fixture import FixtureRepository
from backend.services.claimant_questions import (
    AnswerClaimantQuestionRequest,
    answer_claimant_question,
)
from backend.services.evidence_readings import (
    CorrectEvidenceReadingRequest,
    correct_evidence_reading,
)
from backend.services.workbench import get_workbench_claim_detail
from tests.test_claim_api import submit_message
from tests.test_claim_decisions import _store_created_claim

NOW = datetime(2026, 9, 29, 2, 0, tzinfo=UTC)
QUESTION = {
    'question_id': 'nwq_hire',
    'kind': 'question',
    'question': 'Will you pay for a hire car?',
    'claimant_wording': 'will you pay for a hire car',
    'proposed_answer': 'Yes, for up to 14 days at an approved repairer.',
    'basis': 'MTR-BEN-03',
    'contact_preference': None,
}
CALL_ME = {
    'question_id': 'nwq_call',
    'kind': 'contact_request',
    'question': 'Please call me',
    'claimant_wording': 'can someone call me',
    'proposed_answer': None,
    'basis': 'General request to be contacted.',
    'contact_preference': 'Phone, after 5 pm',
}


def _staff() -> Principal:
    return Principal(
        subject='stf_demo',
        actor_type='staff',
        scopes=STAFF_SCOPES,
        roles=frozenset({'claims_professional'}),
        auth_source='test:staff',
    )


def _message(
    claim_id: str, session_id: str, actor: ActorType, at: datetime, **content: Any
) -> MessageRecord:
    return MessageRecord(
        message_id=f'msg_{actor.value}_{int(at.timestamp())}',
        claim_id=claim_id,
        session_id=session_id,
        actor=actor,
        visibility=MessageVisibility.SHARED
        if actor is not ActorType.AGENT
        else MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': 'x', **content},
        created_at=at,
    )


def _claim_with_items(repository: FixtureRepository) -> Any:
    claim = _store_created_claim(repository, 'clm_wait')
    repository.save_message(
        _message(
            claim.claim_id,
            claim.active_session_id or '',
            ActorType.AGENT,
            NOW,
            turn_record={'northwind_questions': [QUESTION, CALL_ME]},
        ),
        claim.customer_id,
    )
    return claim


def _settle(repository: FixtureRepository, item_id: str, key: str, **request: Any) -> Any:
    revision = get_workbench_claim_detail(repository, _staff(), 'clm_wait').revision
    return answer_claimant_question(
        repository,
        _staff(),
        'clm_wait',
        item_id,
        AnswerClaimantQuestionRequest(**request),
        key,
        str(revision),
    )


def test_items_lead_the_handlers_work_and_surface_the_claim() -> None:
    repository = FixtureRepository()
    _claim_with_items(repository)

    detail = get_workbench_claim_detail(repository, _staff(), 'clm_wait')

    assert [item.code for item in detail.work_summary.missing_information[:2]] == [
        'nwq_hire',
        'nwq_call',
    ]
    assert detail.work_summary.primary_blocker == 'Customer asked: Will you pay for a hire car?'
    # A lodged claim with waiting items is work, not a finished record.
    assert detail.work_summary.queue_key.value == 'processing'


def test_approve_sends_the_proposal_as_the_handlers_message() -> None:
    repository = FixtureRepository()
    claim = _claim_with_items(repository)

    response = _settle(repository, 'nwq_hire', 'approve-1', decision='approve')

    assert response.update.summary == QUESTION['proposed_answer']
    assert response.message is not None and response.message.actor is ActorType.STAFF
    assert response.message.content['answers_item_id'] == 'nwq_hire'
    stored = repository.list_messages(claim.claim_id, claim.active_session_id, claim.customer_id)
    assert any(item.message_id == response.message.message_id for item in stored)
    detail = get_workbench_claim_detail(repository, _staff(), 'clm_wait')
    hire = next(item for item in detail.open_items if item.item_id == 'nwq_hire')
    assert hire.state is OpenItemState.DONE


@pytest.mark.parametrize(
    ('item_id', 'request_body', 'state'),
    [
        ('nwq_hire', {'decision': 'decline', 'text': 'We will explain on the phone.'}, 'declined'),
        ('nwq_call', {'decision': 'contacted'}, 'done'),
        ('nwq_hire', {'decision': 'edit', 'text': 'Yes, for 10 days.'}, 'done'),
    ],
)
def test_each_decision_settles_the_item(
    item_id: str, request_body: dict[str, Any], state: str
) -> None:
    repository = FixtureRepository()
    _claim_with_items(repository)

    response = _settle(repository, item_id, f'settle-{state}', **request_body)

    detail = get_workbench_claim_detail(repository, _staff(), 'clm_wait')
    settled = next(item for item in detail.open_items if item.item_id == item_id)
    assert settled.state.value == state
    assert (response.message is not None) is (request_body['decision'] == 'edit')


def test_decisions_that_do_not_fit_the_item_are_refused() -> None:
    repository = FixtureRepository()
    _claim_with_items(repository)
    for item_id, body in (
        ('nwq_hire', {'decision': 'contacted'}),
        ('nwq_call', {'decision': 'approve'}),
    ):
        with pytest.raises(ApiError) as raised:
            _settle(repository, item_id, f'bad-{item_id}', **body)
        assert raised.value.code == 'VALIDATION_ERROR'
    with pytest.raises(ValueError):
        AnswerClaimantQuestionRequest(decision='decline')


def test_a_handlers_file_reading_overrides_the_models() -> None:
    repository = FixtureRepository()
    claim = _store_created_claim(repository, 'clm_wait')
    evidence = EvidenceRecord(
        evidence_id='evd_chat',
        claim_id=claim.claim_id,
        kind='other_document',
        status=EvidenceStatus.RECEIVED,
        file_status=EvidenceFileStatus.READY,
        media_type='image/jpeg',
        source=EvidenceSource.CLAIMANT,
        created_at=NOW,
        updated_at=NOW,
    )
    repository.save_evidence(evidence, claim.customer_id)
    repository.save_message(
        _message(
            claim.claim_id,
            claim.active_session_id or '',
            ActorType.AGENT,
            NOW,
            turn_record={'file_reads': [{'evidence_id': 'evd_chat', 'kind': 'incident_photo'}]},
        ),
        claim.customer_id,
    )
    detail = get_workbench_claim_detail(repository, _staff(), claim.claim_id)
    assert detail.file_readings == {'evd_chat': 'incident_photo'}

    correct_evidence_reading(
        repository,
        _staff(),
        claim.claim_id,
        'evd_chat',
        CorrectEvidenceReadingRequest(kind='repair_quote'),
        'reading-1',
        str(detail.revision),
    )

    after = get_workbench_claim_detail(repository, _staff(), claim.claim_id)
    assert after.file_readings['evd_chat'] == 'repair_quote'
    assert after.staff_file_readings == ['evd_chat']
    assert interpreted_evidence_kinds([], repository.list_staff_actions(claim.claim_id)) == {
        'evd_chat': 'repair_quote'
    }


def test_after_the_handler_writes_the_agent_stays_out_and_the_reply_is_unread(
    client: TestClient, auth_headers: dict[str, str], repository: FixtureRepository
) -> None:
    claim = _store_created_claim(repository, 'clm_owner_chat')
    session_id = claim.active_session_id or ''
    repository.save_message(
        _message(claim.claim_id, session_id, ActorType.AGENT, NOW), claim.customer_id
    )
    repository.save_message(
        _message(claim.claim_id, session_id, ActorType.STAFF, NOW + timedelta(minutes=1)),
        claim.customer_id,
    )
    before = get_workbench_claim_detail(repository, _staff(), claim.claim_id)
    assert before.work_summary.conversation_turn == 'waiting_on_claimant'

    reply = submit_message(
        client,
        auth_headers,
        claim.claim_id,
        session_id,
        revision=claim.revision,
        key='owner-chat-1',
        client_message_id='owner-chat-1',
        text='Yes, the car is at my house.',
    )

    assert reply.status_code == 200, reply.text
    assert reply.json()['agent_message'] is None
    after = get_workbench_claim_detail(repository, _staff(), claim.claim_id)
    assert after.work_summary.unread_claimant_messages == 1
    assert after.work_summary.conversation_turn == 'claimant_replied'
    assert after.work_summary.queue_key.value == 'processing'
    view = client.get(f'/api/v1/claims/{claim.claim_id}', headers=auth_headers).json()
    assert view['handler_assigned'] is True


def test_a_corrected_reading_closes_the_same_item_for_staff_and_claimant(
    client: TestClient, auth_headers: dict[str, str], repository: FixtureRepository
) -> None:
    claim = _store_created_claim(repository, 'clm_reading')
    common = {
        'claim_id': claim.claim_id,
        'source': EvidenceSource.CLAIMANT,
        'created_at': NOW,
        'updated_at': NOW,
    }
    # The claimant owes a repair quote; a file they sent was read as something else.
    repository.save_evidence(
        EvidenceRecord(
            evidence_id='evd_quote_owed',
            kind='repair_quote',
            status=EvidenceStatus.PENDING,
            file_status=EvidenceFileStatus.NOT_AVAILABLE,
            **common,
        ),
        claim.customer_id,
    )
    repository.save_evidence(
        EvidenceRecord(
            evidence_id='evd_sent',
            kind='other_document',
            status=EvidenceStatus.RECEIVED,
            file_status=EvidenceFileStatus.READY,
            media_type='application/pdf',
            **common,
        ),
        claim.customer_id,
    )

    def states() -> tuple[str, str]:
        staff = get_workbench_claim_detail(repository, _staff(), claim.claim_id)
        claimant = client.get(f'/api/v1/claims/{claim.claim_id}', headers=auth_headers).json()
        staff_state = next(i.state.value for i in staff.open_items if i.item_id == 'evd_quote_owed')
        claimant_state = next(
            i['state'] for i in claimant['open_items'] if i['item_id'] == 'evd_quote_owed'
        )
        return staff_state, claimant_state

    assert states() == ('open', 'open')

    correct_evidence_reading(
        repository,
        _staff(),
        claim.claim_id,
        'evd_sent',
        CorrectEvidenceReadingRequest(kind='repair_quote'),
        'reading-quote',
        str(get_workbench_claim_detail(repository, _staff(), claim.claim_id).revision),
    )

    assert states() == ('done', 'done')
