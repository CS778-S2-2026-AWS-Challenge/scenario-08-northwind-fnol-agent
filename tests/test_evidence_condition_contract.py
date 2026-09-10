"""The split between what a material *is* and where its file *is*.

`EvidenceStatus` used to carry both. `incomplete` meant an upload that had not finished
*and* a document that arrived unusable; `pending_generation` meant a document that did
not exist yet, which is a fact about the material, but was told apart from a file in
flight only by reading `EvidenceFileStatus` as well. Because one word answered two
questions, a projection reading the status alone could state something false — and did:
an illegible receipt was shown to staff as `pending`, as if the claimant still owed it.

These check the split holds, and that the values that were retired went where their
actual producers said they should.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from backend.domain.evidence import (
    evidence_state_for,
    evidence_summary_for,
    is_in_conflict,
    is_registered_evidence_shape,
    unresolved_conflicts,
)
from backend.domain.models import (
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceReference,
    EvidenceRelation,
    EvidenceRelationState,
    EvidenceSource,
    EvidenceState,
    EvidenceStatus,
)
from backend.services.support import now_utc

RAISED = now_utc()


def _record(
    *,
    status: EvidenceStatus = EvidenceStatus.RECEIVED,
    file_status: EvidenceFileStatus = EvidenceFileStatus.READY,
    references: list[EvidenceReference] | None = None,
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id='evd_subject',
        claim_id='clm_1',
        kind='receipt',
        status=status,
        file_status=file_status,
        source=EvidenceSource.CLAIMANT,
        references=references or [],
        created_at=RAISED,
        updated_at=RAISED,
    )


def _conflict(
    *,
    evidence_id: str | None = 'evd_other',
    field_code: str | None = None,
    state: EvidenceRelationState = EvidenceRelationState.UNRESOLVED,
    resolved_at: datetime | None = None,
) -> EvidenceReference:
    return EvidenceReference(
        relation=EvidenceRelation.CONFLICTS_WITH,
        evidence_id=evidence_id,
        field_code=field_code,
        state=state,
        reason='The two records give different answers for the same fact.',
        raised_at=RAISED,
        resolved_at=resolved_at,
    )


def test_the_two_vocabularies_share_no_word() -> None:
    """A value in both would be a place the two could drift apart again."""

    conditions = {member.value for member in EvidenceStatus}
    file_states = {member.value for member in EvidenceFileStatus}

    assert conditions & file_states == set()


def test_disputed_is_not_a_condition() -> None:
    """A material can be received, readable, and contested at the same time.

    A status can say only one thing, so making conflict a status would force a choice
    between recording that the material arrived and recording that it is contested.
    """

    assert 'disputed' not in {member.value for member in EvidenceStatus}


@pytest.mark.parametrize(
    ('retired', 'replacement', 'why'),
    [
        ('pending_generation', EvidenceStatus.PENDING, 'the material does not exist yet'),
        ('incomplete', EvidenceStatus.PENDING, 'an upload that has not finished is a file fact'),
        ('incomplete', EvidenceStatus.INVALID, 'a file that arrived unusable is not'),
        ('inconsistent', EvidenceStatus.RECEIVED, 'a contested material is a received one'),
    ],
)
def test_every_retired_value_has_a_stated_replacement(
    retired: str,
    replacement: EvidenceStatus,
    why: str,
) -> None:
    """The migration, written down where it can be read rather than inferred.

    `incomplete` appears twice on purpose: it carried two meanings, and which one a
    record had is decided by its file status rather than by its old name.
    """

    assert retired not in {member.value for member in EvidenceStatus}
    assert replacement in EvidenceStatus
    assert why


def test_a_contested_material_is_still_received_and_counted_as_needing_attention() -> None:
    """The conflict changes what staff must do, not whether the material arrived."""

    record = _record(references=[_conflict()])

    assert record.status is EvidenceStatus.RECEIVED
    assert record.file_status is EvidenceFileStatus.READY
    assert is_in_conflict(record.references) is True
    assert unresolved_conflicts(record.references) == ('evd_other',)
    assert evidence_state_for([record]) is EvidenceState.IN_CONFLICT
    # It arrived, but it is not something the claim can rely on yet.
    summary = evidence_summary_for([record])
    assert (summary.received, summary.pending, summary.needs_attention) == (0, 0, 1)


def test_a_conflict_may_name_a_claim_fact_instead_of_another_record() -> None:
    """Evidence can contradict what the claimant said, not only another document."""

    record = _record(references=[_conflict(evidence_id=None, field_code='incident.cause')])

    assert unresolved_conflicts(record.references) == ('field:incident.cause',)


def test_a_resolved_conflict_stops_contesting_and_records_when() -> None:
    """A decided conflict is history; the record returns to being simply received."""

    record = _record(
        references=[_conflict(state=EvidenceRelationState.RESOLVED, resolved_at=RAISED)]
    )

    assert is_in_conflict(record.references) is False
    assert evidence_state_for([record]) is EvidenceState.RECEIVED
    assert evidence_summary_for([record]).received == 1


def test_a_reference_must_name_exactly_one_thing() -> None:
    """Naming both, or neither, leaves the other side ambiguous."""

    with pytest.raises(ValidationError, match='exactly one'):
        _conflict(evidence_id='evd_other', field_code='incident.cause')
    with pytest.raises(ValidationError, match='exactly one'):
        _conflict(evidence_id=None, field_code=None)


def test_only_a_conflict_may_name_a_claim_field() -> None:
    """A claim fact cannot supersede a document, or establish that one is unavailable."""

    with pytest.raises(ValidationError, match='must name another evidence record'):
        EvidenceReference(
            relation=EvidenceRelation.SUPERSEDED_BY,
            field_code='incident.cause',
            reason='A later account replaced it.',
            raised_at=RAISED,
        )


def test_resolution_state_and_timestamp_must_agree() -> None:
    """A resolved reference says when, and an unresolved one cannot."""

    with pytest.raises(ValidationError, match='must record when it was resolved'):
        _conflict(state=EvidenceRelationState.RESOLVED)
    with pytest.raises(ValidationError, match='must record when it was resolved'):
        _conflict(state=EvidenceRelationState.UNRESOLVED, resolved_at=RAISED)


def test_a_reference_cannot_be_resolved_before_it_was_raised() -> None:
    with pytest.raises(ValidationError, match='cannot be resolved before'):
        _conflict(
            state=EvidenceRelationState.RESOLVED,
            resolved_at=RAISED - timedelta(seconds=1),
        )


@pytest.mark.parametrize(
    ('status', 'file_status', 'registered', 'why'),
    [
        (
            EvidenceStatus.MISSING,
            EvidenceFileStatus.NOT_AVAILABLE,
            True,
            'nothing was offered, so there is nothing to open',
        ),
        (
            EvidenceStatus.MISSING,
            EvidenceFileStatus.READY,
            False,
            'a readable file contradicts a material nobody supplied',
        ),
        (
            EvidenceStatus.UNAVAILABLE,
            EvidenceFileStatus.NOT_AVAILABLE,
            True,
            'it was sought and established as unobtainable',
        ),
        (
            EvidenceStatus.UNAVAILABLE,
            EvidenceFileStatus.READY,
            False,
            'a document that opens is not one that cannot be obtained',
        ),
        (
            EvidenceStatus.SUPERSEDED,
            EvidenceFileStatus.READY,
            True,
            'the earlier issue is kept in the record',
        ),
        (
            EvidenceStatus.SUPERSEDED,
            EvidenceFileStatus.AWAITING_UPLOAD,
            False,
            'something that never arrived cannot have been replaced',
        ),
        (
            EvidenceStatus.INVALID,
            EvidenceFileStatus.READY,
            True,
            'it arrived and cannot be used',
        ),
        (
            EvidenceStatus.INVALID,
            EvidenceFileStatus.NOT_AVAILABLE,
            False,
            'content that does not exist cannot be deficient',
        ),
        (
            EvidenceStatus.PENDING,
            EvidenceFileStatus.NOT_AVAILABLE,
            True,
            'the document does not exist yet',
        ),
        (
            EvidenceStatus.PENDING,
            EvidenceFileStatus.READY,
            False,
            'a ready file means it is no longer awaited',
        ),
    ],
)
def test_a_condition_and_a_file_state_may_not_contradict_each_other(
    status: EvidenceStatus,
    file_status: EvidenceFileStatus,
    registered: bool,
    why: str,
) -> None:
    """This is what separating the vocabularies buys: contradictions become visible."""

    assert is_registered_evidence_shape(_record(status=status, file_status=file_status)) is (
        registered
    ), why


def test_the_claimant_projection_has_no_place_for_a_reference() -> None:
    """Catalogue section 7: a claimant is told a check is in progress, not which side.

    `ContractModel` forbids unknown fields, so the absence is enforced by the contract
    rather than by every projection remembering to strip it.
    """

    from backend.domain.models import ClaimantEvidence

    assert 'references' not in ClaimantEvidence.model_fields
