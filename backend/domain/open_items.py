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
    StaffOpenItem,
)

TURN_RECORD_KEY = 'turn_record'

# Content keys a claimant may read. Anything else stays server-side.
_CLAIMANT_CONTENT_KEYS = frozenset({'type', 'text', 'parts'})
_CLAIMANT_TURN_RECORD_KEYS = frozenset(
    {'recorded_facts', 'file_reads', 'opened_items', 'ending', 'scope_note'}
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


def interpreted_evidence_kinds(messages: Iterable[MessageRecord]) -> dict[str, str]:
    """The latest kind the model read each file to be, by Evidence id."""

    kinds: dict[str, str] = {}
    for message in sorted(messages, key=lambda item: item.created_at):
        if message.actor is not ActorType.AGENT:
            continue
        for read in turn_record(message.content).get('file_reads', ()):
            if isinstance(read, Mapping) and read.get('evidence_id') and read.get('kind'):
                kinds[str(read['evidence_id'])] = str(read['kind'])
    return kinds


def _questions(
    messages: Sequence[MessageRecord],
    updates: Sequence[CustomerUpdateRecord],
) -> list[StaffOpenItem]:
    # A staff answer is a claimant-visible customer update that names the question.
    answers: dict[str, str] = {}
    for update in sorted(updates, key=lambda item: item.created_at):
        for ref in update.related_refs:
            answers[ref] = update.summary
    items: list[StaffOpenItem] = []
    for message in messages:
        if message.actor is not ActorType.AGENT:
            continue
        for question in turn_record(message.content).get('northwind_questions', ()):
            if not isinstance(question, Mapping) or not question.get('question_id'):
                continue
            question_id = str(question['question_id'])
            answer = answers.get(question_id)
            items.append(
                StaffOpenItem(
                    item_id=question_id,
                    kind='question',
                    owner=OpenItemOwner.NORTHWIND,
                    state=OpenItemState.DONE if answer is not None else OpenItemState.OPEN,
                    subject=str(question.get('question') or '')[:200] or 'Question',
                    answer=answer,
                    opened_in_message_id=message.message_id,
                    claimant_wording=question.get('claimant_wording'),
                    model_view=question.get('model_view'),
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
) -> list[StaffOpenItem]:
    """Every outstanding or settled item on a Claim, oldest first."""

    ordered = sorted(messages, key=lambda item: item.created_at)
    interpreted = interpreted_evidence_kinds(ordered)
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
) -> list[ClaimantOpenItem]:
    return [
        ClaimantOpenItem.model_validate(item.model_dump(exclude={'claimant_wording', 'model_view'}))
        for item in staff_open_items(evidence, messages, updates)
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
