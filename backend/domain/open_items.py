"""What is still outstanding on a Claim, who owes it, and what each turn recorded.

Each Agent message carries a ``turn_record`` in its content, written in the same
atomic save as the turn: the facts the turn recorded, what the model read each
file to be, and the questions it handed to the claims team. Everything here is
read from stored records -- Evidence and those messages -- never inferred from
the current Claim afterwards.

An open item is owed by one of three parties:

- the claimant (a document they will send later, or do not have);
- Northwind (a question the model could not answer with authority);
- a third party (a document Northwind will get from a registered service).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from backend.domain.evidence import canonical_evidence_kind, evidence_kind
from backend.domain.models import (
    ActorType,
    ClaimantOpenItem,
    CustomerUpdateRecord,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceStatus,
    MessageRecord,
    OpenItemOwner,
    OpenItemState,
    ResponsibleParty,
    StaffActionRecord,
    StaffActionStatus,
    StaffOpenItem,
)

TURN_RECORD_KEY = 'turn_record'
# A handler's decision on a waiting-list item is a claimant-visible customer
# update whose related_refs name the item; a marker ref says how it was settled.
DECLINED_REF = 'waiting_item:declined'
CONTACTED_REF = 'waiting_item:contacted'

# Content keys a claimant may read. Anything else stays server-side.
_CLAIMANT_CONTENT_KEYS = frozenset({'type', 'text', 'parts', 'answers_item_id'})
_CLAIMANT_TURN_RECORD_KEYS = frozenset(
    {'recorded_facts', 'file_reads', 'opened_items', 'ending', 'scope_note', 'cited_clauses'}
)


def turn_record(content: Mapping[str, Any]) -> Mapping[str, Any]:
    record = content.get(TURN_RECORD_KEY)
    return record if isinstance(record, Mapping) else {}


def claimant_message_content(content: Mapping[str, Any]) -> dict[str, Any]:
    """The part of a message's content a claimant may read."""

    visible = {key: value for key, value in content.items() if key in _CLAIMANT_CONTENT_KEYS}
    record = turn_record(content)
    if record:
        visible[TURN_RECORD_KEY] = {
            key: value for key, value in record.items() if key in _CLAIMANT_TURN_RECORD_KEYS
        }
    return visible


def model_message_content(content: Mapping[str, Any]) -> dict[str, Any]:
    """Message content for model context: the words only.

    What earlier turns recorded reaches the model through the Claim projection
    and the open items, not by re-reading its own records.
    """

    return {key: value for key, value in content.items() if key != TURN_RECORD_KEY}


EVIDENCE_READING_ACTION = 'evidence_reading'


def staff_evidence_readings(actions: Iterable[StaffActionRecord]) -> dict[str, str]:
    """The latest kind a handler set for each file, by Evidence id."""

    kinds: dict[str, str] = {}
    completed = [
        item
        for item in actions
        if item.action_type == EVIDENCE_READING_ACTION
        and item.status is StaffActionStatus.COMPLETED
        and item.result is not None
    ]
    for action in sorted(completed, key=lambda item: item.completed_at or item.created_at):
        assert action.result is not None
        for evidence_id in action.source_refs:
            kinds[evidence_id] = action.result.outcome
    return kinds


def interpreted_evidence_kinds(
    messages: Iterable[MessageRecord], staff_actions: Iterable[StaffActionRecord] = ()
) -> dict[str, str]:
    """The kind each file counts as, by Evidence id: a handler's reading wins over
    the latest reading by the model."""

    kinds: dict[str, str] = {}
    for message in sorted(messages, key=lambda item: item.created_at):
        if message.actor is not ActorType.AGENT:
            continue
        for read in turn_record(message.content).get('file_reads', ()):
            if isinstance(read, Mapping) and read.get('evidence_id') and read.get('kind'):
                kinds[str(read['evidence_id'])] = str(read['kind'])
    kinds.update(staff_evidence_readings(staff_actions))
    return kinds


def _questions(
    messages: Sequence[MessageRecord],
    updates: Sequence[CustomerUpdateRecord],
) -> list[StaffOpenItem]:
    # A handler's decision is a claimant-visible customer update naming the item.
    decisions: dict[str, tuple[str, OpenItemState]] = {}
    for update in sorted(updates, key=lambda item: item.created_at):
        state = (
            OpenItemState.DECLINED if DECLINED_REF in update.related_refs else OpenItemState.DONE
        )
        for ref in update.related_refs:
            if not ref.startswith('waiting_item:'):
                decisions[ref] = (update.summary, state)
    items: list[StaffOpenItem] = []
    for message in messages:
        if message.actor is not ActorType.AGENT:
            continue
        for question in turn_record(message.content).get('northwind_questions', ()):
            if not isinstance(question, Mapping) or not question.get('question_id'):
                continue
            question_id = str(question['question_id'])
            decided = decisions.get(question_id)
            kind = 'contact_request' if question.get('kind') == 'contact_request' else 'question'
            items.append(
                StaffOpenItem(
                    item_id=question_id,
                    kind=kind,
                    owner=OpenItemOwner.NORTHWIND,
                    state=decided[1] if decided is not None else OpenItemState.OPEN,
                    subject=str(question.get('question') or '')[:200] or 'Question',
                    answer=decided[0] if decided is not None else None,
                    opened_in_message_id=message.message_id,
                    claimant_wording=question.get('claimant_wording'),
                    proposed_answer=question.get('proposed_answer'),
                    # Records from before the waiting list stored the basis as model_view.
                    basis=question.get('basis') or question.get('model_view'),
                    contact_preference=question.get('contact_preference'),
                    created_at=message.created_at,
                )
            )
    return items


def _documents(
    evidence: Sequence[EvidenceRecord],
    received_kinds: set[str],
    opened_in: Mapping[str, str],
) -> list[StaffOpenItem]:
    items: list[StaffOpenItem] = []
    for record in evidence:
        if record.file_status is not EvidenceFileStatus.NOT_AVAILABLE:
            continue
        kind = canonical_evidence_kind(record.kind)
        if record.status is EvidenceStatus.PENDING:
            owner = (
                OpenItemOwner.THIRD_PARTY
                if record.responsible_party is ResponsibleParty.EXTERNAL_PARTY
                else OpenItemOwner.CLAIMANT
            )
            state = OpenItemState.DONE if kind in received_kinds else OpenItemState.OPEN
        elif record.status is EvidenceStatus.UNAVAILABLE:
            owner = OpenItemOwner.CLAIMANT
            state = OpenItemState.NOT_AVAILABLE
        else:
            continue
        service = record.provenance.get('service_identity')
        items.append(
            StaffOpenItem(
                item_id=record.evidence_id,
                kind='document',
                owner=owner,
                state=state,
                subject=kind,
                service_identity=service if isinstance(service, str) else None,
                opened_in_message_id=opened_in.get(record.evidence_id),
                claimant_wording=record.claimant_note[:300] if record.claimant_note else None,
                created_at=record.created_at,
            )
        )
    return items


def staff_open_items(
    evidence: Sequence[EvidenceRecord],
    messages: Sequence[MessageRecord],
    updates: Sequence[CustomerUpdateRecord] = (),
    staff_actions: Sequence[StaffActionRecord] = (),
) -> list[StaffOpenItem]:
    """Every outstanding or settled item on a Claim, oldest first."""

    ordered = sorted(messages, key=lambda item: item.created_at)
    interpreted = interpreted_evidence_kinds(ordered, staff_actions)
    received = {
        evidence_kind(item, interpreted)
        for item in evidence
        if item.status is EvidenceStatus.RECEIVED
    }
    opened_in: dict[str, str] = {}
    for message in ordered:
        if message.actor is ActorType.AGENT:
            for item_id in turn_record(message.content).get('opened_items', ()):
                opened_in.setdefault(str(item_id), message.message_id)
    items = [*_documents(evidence, received, opened_in), *_questions(ordered, updates)]
    return sorted(items, key=lambda item: item.created_at)


def claimant_open_items(
    evidence: Sequence[EvidenceRecord],
    messages: Sequence[MessageRecord],
    updates: Sequence[CustomerUpdateRecord] = (),
    staff_actions: Sequence[StaffActionRecord] = (),
) -> list[ClaimantOpenItem]:
    """The claimant's view of the same items staff see; a handler's file reading
    counts here exactly as in the Workbench."""
    return [
        ClaimantOpenItem.model_validate(
            item.model_dump(
                exclude={'claimant_wording', 'proposed_answer', 'basis', 'contact_preference'}
            )
        )
        for item in staff_open_items(evidence, messages, updates, staff_actions)
    ]


def open_question(
    question_id: str,
    messages: Sequence[MessageRecord],
    updates: Sequence[CustomerUpdateRecord],
) -> StaffOpenItem | None:
    """The question with this id while it is still unanswered."""

    for item in _questions(sorted(messages, key=lambda m: m.created_at), updates):
        if item.item_id == question_id and item.state is OpenItemState.OPEN:
            return item
    return None
