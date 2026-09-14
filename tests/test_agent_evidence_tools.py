from datetime import UTC, datetime

import pytest

from backend.domain.agent_action_registry import (
    ActionIdempotencyPolicy,
    ActionStateEffect,
    ActionVisibility,
    action_contract,
)
from backend.domain.models import (
    Channel,
    CustomerNextStep,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    ResponsibleParty,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.services.agent_tools import (
    read_evidence_history_for_runtime,
    validate_evidence_proposal,
)


def _claim(claim_id: str = 'clm_target', customer_id: str = 'cus_owner') -> WorkingClaim:
    now = datetime.now(UTC)
    return WorkingClaim(
        claim_id=claim_id,
        customer_id=customer_id,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Describe the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=now,
        updated_at=now,
    )


def _evidence(
    evidence_id: str,
    claim_id: str,
    *,
    status: EvidenceStatus = EvidenceStatus.RECEIVED,
    file_status: EvidenceFileStatus = EvidenceFileStatus.READY,
    source: EvidenceSource = EvidenceSource.CLAIMANT,
) -> EvidenceRecord:
    now = datetime.now(UTC)
    return EvidenceRecord(
        evidence_id=evidence_id,
        claim_id=claim_id,
        kind='incident_image',
        status=status,
        file_status=file_status,
        original_filename=f'{evidence_id}.jpg',
        media_type='image/jpeg',
        size_bytes=10,
        source=source,
        created_at=now,
        updated_at=now,
    )


def test_history_tool_is_bounded_to_authenticated_claimant_records() -> None:
    repository = FixtureRepository()
    target = _claim()
    other = _claim('clm_other', 'cus_other')
    repository._claims[target.claim_id] = target
    repository._claims[other.claim_id] = other
    repository.save_evidence(_evidence('evd_ready', target.claim_id), target.customer_id)
    repository.save_evidence(
        _evidence('evd_processing', target.claim_id, file_status=EvidenceFileStatus.PROCESSING),
        target.customer_id,
    )
    repository.save_evidence(_evidence('evd_other', other.claim_id), other.customer_id)
    repository.save_evidence(
        _evidence('evd_external', target.claim_id, source=EvidenceSource.EXTERNAL_SYSTEM),
        target.customer_id,
    )

    result = read_evidence_history_for_runtime(repository, target, {})

    assert result['tool'] == 'evidence.history'
    assert result['status'] == 'succeeded'
    assert {item['evidence_id'] for item in result['items']} == {
        'evd_ready',
        'evd_processing',
    }
    assert set(result['source_refs']) == {'evd_ready', 'evd_processing'}
    assert all('storage_key' not in item for item in result['items'])
    assert all(item['can_remove'] is False for item in result['items'])


def test_history_tool_rejects_provider_selected_scope_and_bad_limit() -> None:
    repository = FixtureRepository()
    target = _claim()

    with pytest.raises(ValueError, match='does not accept'):
        read_evidence_history_for_runtime(repository, target, {'customer_id': target.customer_id})
    with pytest.raises(ValueError, match='between 1 and 50'):
        read_evidence_history_for_runtime(repository, target, {'limit': 0})


def test_evidence_proposal_contracts_are_proposal_only_and_confirmation_bound() -> None:
    reuse = action_contract('evidence.propose_reuse')
    remove = action_contract('evidence.propose_remove')

    assert reuse.state_effect is ActionStateEffect.CLAIM_PROPOSAL
    assert reuse.side_effect_class.value == 'none'
    assert reuse.idempotency_policy is ActionIdempotencyPolicy.NOT_REQUIRED
    assert reuse.requires_confirmation is True
    assert reuse.visibility == (ActionVisibility.CLAIMANT,)
    assert remove.requires_confirmation is True
    assert remove.permitted_tools == ('evidence.history',)


def test_reuse_requires_owned_ready_evidence_and_explicit_confirmation() -> None:
    repository = FixtureRepository()
    source = _claim('clm_source')
    target = _claim('clm_target')
    repository._claims[source.claim_id] = source
    repository._claims[target.claim_id] = target
    repository.save_evidence(_evidence('evd_ready', source.claim_id), source.customer_id)

    missing_confirmation = validate_evidence_proposal(
        repository,
        target,
        action_code='evidence.propose_reuse',
        evidence_id='evd_ready',
        source_claim_id=source.claim_id,
    )
    assert missing_confirmation == {
        'status': 'rejected',
        'reason': 'CLAIMANT_CONFIRMATION_REQUIRED',
    }

    proposed = validate_evidence_proposal(
        repository,
        target,
        action_code='evidence.propose_reuse',
        evidence_id='evd_ready',
        source_claim_id=source.claim_id,
        confirmation_ref='msg_confirmed_reuse',
    )
    assert proposed['status'] == 'proposed'
    assert proposed['target_claim_id'] == target.claim_id
    assert proposed['source_claim_id'] == source.claim_id


def test_reuse_and_remove_fail_closed_for_ineligible_or_unavailable_paths() -> None:
    repository = FixtureRepository()
    target = _claim()
    repository._claims[target.claim_id] = target
    repository.save_evidence(
        _evidence('evd_processing', target.claim_id, file_status=EvidenceFileStatus.PROCESSING),
        target.customer_id,
    )

    rejected = validate_evidence_proposal(
        repository,
        target,
        action_code='evidence.propose_reuse',
        evidence_id='evd_processing',
        source_claim_id=target.claim_id,
        confirmation_ref='msg_confirmed_reuse',
    )
    assert rejected == {'status': 'rejected', 'reason': 'EVIDENCE_NOT_REUSABLE'}

    unavailable = validate_evidence_proposal(
        repository,
        target,
        action_code='evidence.propose_remove',
        evidence_id='evd_processing',
        confirmation_ref='msg_confirmed_remove',
        removal_scope='persisted',
    )
    assert unavailable['status'] == 'unavailable'
    assert unavailable['reason'] == 'PERSISTED_REMOVE_HANDLER_UNAVAILABLE'
    assert unavailable['can_remove'] is False
