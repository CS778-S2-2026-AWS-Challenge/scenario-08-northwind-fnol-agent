"""Long-lived policy judgment validation and evidence-boundary regressions."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.domain.agent_v8 import V8PolicyJudgmentProposal
from backend.domain.models import (
    ActorReference,
    ContentsItem,
    FormStatus,
    StructuredFormField,
    WorkingClaim,
)
from backend.services.policy_judgment import (
    JUDGMENT_POINT_TAXONOMY,
    JudgmentPointSpec,
    policy_judgment_signals,
    validate_policy_judgment_proposals,
)
from tests.test_agent_context_runtime_v7 import _claim

NOW = datetime(2026, 9, 30, tzinfo=UTC)


def proposal(kind: str, *refs: str) -> V8PolicyJudgmentProposal:
    return V8PolicyJudgmentProposal(
        kind=kind,
        assessment='Advisory assessment for staff review.',
        rationale='The confirmed account requires professional application of this clause.',
        source_refs=list(refs or ('chunk_1',)),
    )


def fact(value: object, **updates: object) -> StructuredFormField:
    return StructuredFormField.model_validate(
        {
            'value': value,
            'source': 'claimant',
            'status': 'confirmed',
            'needed_for': 'current_action',
            'updated_at': NOW,
            'updated_by': {'actor_type': 'claimant', 'actor_id': 'cus_v7'},
            **updates,
        }
    )


def claim_for(family: str, **facts: object) -> WorkingClaim:
    claim = _claim(incident_type=family)
    claim.form = {'claim.product_family': fact(family)}
    claim.form.update({code: fact(value) for code, value in facts.items()})
    return claim


def evidence(clause: str) -> list[dict[str, object]]:
    return [
        {
            'chunk_id': 'chunk_1',
            'document_id': 'policy_1',
            'title': 'Standard policy',
            'section_path': f'Policy > {clause} - Clause title',
            'text': 'Policy clause evidence.',
            'source_uri': 's3://knowledge/policy',
            'version': '2026.1',
            'checksum': 'sha256:test',
        }
    ]


@pytest.mark.parametrize(
    ('family', 'kind', 'clause', 'facts'),
    [
        (
            'motor',
            'liability_split',
            'MTR-COV-02',
            {'parties.other_parties': True, 'incident.description': 'A second vehicle hit mine.'},
        ),
        (
            'home',
            'gradual_damage_discoverability',
            'HOM-BEN-03',
            {
                'incident.discovered_at': {'date': '2026-09-29', 'precision': 'exact'},
                'incident.description': 'Hidden leak discovered behind wall.',
            },
        ),
        (
            'contents',
            'theft_circumstance',
            'CON-COV-02',
            {
                'theft.entry_context': 'forced_entry',
                'incident.description': 'Door was forced and laptop stolen.',
            },
        ),
    ],
)
def test_three_family_judgments_create_advisory_signals_with_durable_sources(
    family: str, kind: str, clause: str, facts: dict[str, object]
) -> None:
    claim = claim_for(family, **facts)
    signals, rejected = policy_judgment_signals(
        claim,
        [proposal(kind)],
        authorized_knowledge=evidence(clause),
        trigger_message_id='msg_42',
        created_at=NOW,
    )
    assert rejected == []
    signal = signals[0]
    assert signal.code == 'POLICY_JUDGMENT_PROPOSAL'
    assert signal.judgment_point_kind == kind
    assert signal.source_refs == [
        'msg_42',
        f'claim:{claim.claim_id}:revision:{claim.revision}',
        'chunk_1',
    ]
    assert signal.policy_sources[0].section_path.endswith('Clause title')
    assert signal.proposed_assessment == proposal(kind).assessment
    assert claim.customer_next_step.status == 'describe_incident'


@pytest.mark.parametrize(
    'updates',
    [
        {'value': None},
        {'value': ''},
        {'value': 'unknown'},
        {'value': []},
        {'status': 'disputed'},
        {'status': 'proposed'},
        {'precision': 'unknown'},
        {'resolution_state': 'clarification_required'},
    ],
)
def test_required_fact_must_be_known_confirmed_and_resolved(updates: dict[str, object]) -> None:
    claim = claim_for('home')
    claim.form['incident.description'] = StructuredFormField.model_validate(
        {**fact('Observed damage').model_dump(), **updates}
    )
    valid, rejected = validate_policy_judgment_proposals(
        [proposal('excess_multiplicity')], claim=claim, authorized_knowledge=evidence('HOM-EXC-01')
    )
    assert valid == []
    assert rejected[0]['reason'] == 'required_facts_missing'


@pytest.mark.parametrize(
    ('family', 'kind', 'clause', 'ref', 'reason'),
    [
        ('home', 'liability_split', 'MTR-COV-02', 'chunk_1', 'family_not_eligible'),
        ('home', 'unknown_kind', 'HOM-EXC-01', 'chunk_1', 'unknown_kind'),
        ('home', 'excess_multiplicity', 'MTR-EXC-01', 'chunk_1', 'policy_evidence_not_authorized'),
        ('home', 'excess_multiplicity', 'HOM-EXC-010', 'chunk_1', 'policy_evidence_not_authorized'),
        (
            'home',
            'excess_multiplicity',
            'HOM-EXC-01',
            'chunk_other_claim',
            'policy_evidence_not_authorized',
        ),
        (
            'home',
            'excess_multiplicity',
            'HOM-EXC-01',
            'policy:HOM-EXC-01',
            'policy_evidence_not_authorized',
        ),
    ],
)
def test_kind_family_clause_and_authorized_source_boundaries(
    family: str, kind: str, clause: str, ref: str, reason: str
) -> None:
    valid, rejected = validate_policy_judgment_proposals(
        [proposal(kind, ref)],
        claim=claim_for(family, **{'incident.description': 'Damage reported.'}),
        authorized_knowledge=evidence(clause),
    )
    assert valid == []
    assert rejected == [{'kind': kind, 'reason': reason}]


def test_handoff_duplicate_and_replay_identity_boundaries() -> None:
    claim = claim_for('home', **{'incident.description': 'Damage reported.'})
    proposals = [proposal('excess_multiplicity'), proposal('excess_multiplicity')]
    knowledge = evidence('HOM-EXC-01')
    valid, rejected = validate_policy_judgment_proposals(
        proposals, claim=claim, authorized_knowledge=knowledge, handoff_active=True
    )
    assert valid == []
    assert {item['reason'] for item in rejected} == {'suppressed_during_handoff'}
    valid, rejected = validate_policy_judgment_proposals(
        proposals, claim=claim, authorized_knowledge=knowledge
    )
    assert len(valid) == 1
    assert rejected == [{'kind': 'excess_multiplicity', 'reason': 'duplicate_kind'}]
    first, _ = policy_judgment_signals(
        claim,
        valid,
        authorized_knowledge=evidence('HOM-EXC-01'),
        trigger_message_id='msg_1',
        created_at=NOW,
    )
    retry, _ = policy_judgment_signals(
        claim,
        valid,
        authorized_knowledge=evidence('HOM-EXC-01'),
        trigger_message_id='msg_1',
        created_at=NOW,
    )
    later, _ = policy_judgment_signals(
        claim,
        valid,
        authorized_knowledge=evidence('HOM-EXC-01'),
        trigger_message_id='msg_2',
        created_at=NOW,
    )
    assert first[0].signal_id == retry[0].signal_id != later[0].signal_id


def test_contents_item_requires_typed_confirmed_record_not_form_placeholder() -> None:
    claim = claim_for('contents', **{'contents.items': 'Laptop'})
    knowledge = evidence('CON-AUTH-01')
    assert (
        validate_policy_judgment_proposals(
            [proposal('item_classification_dispute')], claim=claim, authorized_knowledge=knowledge
        )[0]
        == []
    )
    claim.contents_items = [
        ContentsItem(
            item_id='itm_1',
            description='Laptop',
            category='electronics',
            loss_type='stolen',
            ownership='owned',
            source='claimant',
            status='confirmed',
            needed_for='current_action',
            updated_at=NOW,
            updated_by=ActorReference(actor_type='claimant', actor_id='cus_v7'),
        )
    ]
    assert (
        len(
            validate_policy_judgment_proposals(
                [proposal('item_classification_dispute')],
                claim=claim,
                authorized_knowledge=knowledge,
            )[0]
        )
        == 1
    )
    claim.contents_items[0].status = FormStatus.DISPUTED
    assert (
        validate_policy_judgment_proposals(
            [proposal('item_classification_dispute')], claim=claim, authorized_knowledge=knowledge
        )[0]
        == []
    )


def test_new_kind_requires_only_taxonomy_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        JUDGMENT_POINT_TAXONOMY,
        'new_review_kind',
        JudgmentPointSpec({'home': ('HOM-EXC-01',)}, ('incident.description',)),
    )
    valid, rejected = validate_policy_judgment_proposals(
        [proposal('new_review_kind')],
        claim=claim_for('home', **{'incident.description': 'Damage reported.'}),
        authorized_knowledge=evidence('HOM-EXC-01'),
    )
    assert [item.kind for item in valid] == ['new_review_kind']
    assert rejected == []


def test_blank_proposal_text_is_not_advisory_evidence() -> None:
    with pytest.raises(ValidationError):
        V8PolicyJudgmentProposal(
            kind='liability_split', assessment=' ', rationale=' ', source_refs=['chunk_1']
        )


@pytest.mark.parametrize('change', [{'text': ''}, {'version': None}, {'checksum': ''}])
def test_malformed_authorized_evidence_is_rejected_without_failing_turn(
    change: dict[str, object],
) -> None:
    knowledge = evidence('HOM-EXC-01')
    knowledge[0].update(change)
    valid, rejected = validate_policy_judgment_proposals(
        [proposal('excess_multiplicity')],
        claim=claim_for('home', **{'incident.description': 'Damage reported.'}),
        authorized_knowledge=knowledge,
    )
    assert valid == []
    assert rejected[0]['reason'] == 'policy_evidence_not_authorized'


def test_retrieval_repeats_do_not_duplicate_durable_evidence() -> None:
    claim = claim_for('home', **{'incident.description': 'Damage reported.'})
    signals, rejected = policy_judgment_signals(
        claim,
        [proposal('excess_multiplicity', 'chunk_1', 'chunk_1')],
        authorized_knowledge=evidence('HOM-EXC-01') * 12,
        trigger_message_id='msg_repeat',
        created_at=NOW,
    )
    assert rejected == []
    assert len(signals[0].policy_sources) == 1
    assert signals[0].source_refs == [
        'msg_repeat',
        f'claim:{claim.claim_id}:revision:{claim.revision}',
        'chunk_1',
    ]


def test_unknown_temporal_precision_and_absent_other_party_do_not_satisfy_prerequisites() -> None:
    home = claim_for(
        'home',
        **{
            'incident.description': 'Water damage.',
            'incident.discovered_at': {'reported_text': 'Not sure', 'precision': 'unknown'},
        },
    )
    assert (
        validate_policy_judgment_proposals(
            [proposal('gradual_damage_discoverability')],
            claim=home,
            authorized_knowledge=evidence('HOM-BEN-03'),
        )[0]
        == []
    )
    motor = claim_for(
        'motor',
        **{
            'incident.description': 'Hit my own garage.',
            'parties.other_parties': False,
        },
    )
    assert (
        validate_policy_judgment_proposals(
            [proposal('liability_split')],
            claim=motor,
            authorized_knowledge=evidence('MTR-COV-02'),
        )[0]
        == []
    )


def test_canonical_source_ids_and_confirmed_family_are_required() -> None:
    with pytest.raises(ValidationError):
        proposal('excess_multiplicity', ' ')
    claim = claim_for('home', **{'incident.description': 'Damage reported.'})
    claim.form.pop('claim.product_family')
    valid, rejected = validate_policy_judgment_proposals(
        [proposal('excess_multiplicity')],
        claim=claim,
        authorized_knowledge=evidence('HOM-EXC-01'),
    )
    assert valid == []
    assert rejected[0]['reason'] == 'family_not_eligible'
