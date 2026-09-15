from dataclasses import replace
from datetime import UTC, datetime

import pytest

from backend.domain.agent_action_commands import ClaimContextCommand, build_claim_context_command
from backend.domain.agent_action_registry import (
    ActionActorRole,
    ActionIdempotencyPolicy,
    ActionSideEffectClass,
    ActionStateEffect,
    ActionVisibility,
    ExecutionAuthority,
    action_contract,
)
from backend.domain.agent_tool_registry import tool_contract
from backend.domain.models import (
    Channel,
    ClaimState,
    CustomerNextStep,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    ResponsibleParty,
    WorkflowState,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.services.agent_evidence_actions import (
    EvidenceActionBackendResult,
    EvidenceActionConfirmation,
    EvidenceActionRequest,
    EvidenceActionStatus,
    execute_confirmed_evidence_action,
)


def _claim(claim_id: str, customer_id: str = 'cus_owner') -> WorkingClaim:
    now = datetime.now(UTC)
    return WorkingClaim(
        claim_id=claim_id,
        customer_id=customer_id,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        claim_state=ClaimState(workflow_state=WorkflowState.COLLECTING),
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Describe the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=now,
        updated_at=now,
    )


def _evidence(
    claim_id: str,
    *,
    file_status: EvidenceFileStatus = EvidenceFileStatus.READY,
    status: EvidenceStatus = EvidenceStatus.RECEIVED,
    source: EvidenceSource = EvidenceSource.CLAIMANT,
) -> EvidenceRecord:
    now = datetime.now(UTC)
    return EvidenceRecord(
        evidence_id='evd_history',
        claim_id=claim_id,
        kind='incident_image',
        status=status,
        file_status=file_status,
        source=source,
        created_at=now,
        updated_at=now,
    )


def _command(action_code: str = 'claim.reuse_evidence') -> ClaimContextCommand:
    return build_claim_context_command(
        action_code,
        {
            'claim_id': 'clm_target',
            'evidence_id': 'evd_history',
            'source_claim_id': 'clm_source',
            'expected_revision': 1,
            'proposal_ref': 'turn:proposal-1',
        },
        proposer_role=ActionActorRole.RUNTIME,
        approved_authority=ExecutionAuthority.CLAIMANT_STAFF_OR_PUBLISHED_RULE,
        authority_reference='message:confirmation-1',
        workflow_state=WorkflowState.COLLECTING,
        idempotency_key='evidence-action-1',
    )


def _confirmation(action_code: str = 'claim.reuse_evidence') -> EvidenceActionConfirmation:
    return EvidenceActionConfirmation(
        claimant_id='cus_owner',
        action_code=action_code,
        claim_id='clm_target',
        evidence_id='evd_history',
        source_claim_id='clm_source',
        proposal_ref='turn:proposal-1',
        confirmation_ref='message:confirmation-1',
        confirmed=True,
    )


def _repository() -> FixtureRepository:
    repository = FixtureRepository()
    repository._claims['clm_target'] = _claim('clm_target')
    repository._claims['clm_source'] = _claim('clm_source')
    repository.save_evidence(_evidence('clm_source'), 'cus_owner')
    return repository


class RecordingBackend:
    def __init__(
        self,
        repository: FixtureRepository,
        status: EvidenceActionStatus = EvidenceActionStatus.SUCCEEDED,
    ) -> None:
        self.repository = repository
        self.status = status
        self.calls: list[EvidenceActionRequest] = []
        self.results: dict[str, EvidenceActionBackendResult] = {}

    def find_result(self, request: EvidenceActionRequest) -> EvidenceActionBackendResult | None:
        return self.results.get(request.idempotency_key)

    def execute(self, request: EvidenceActionRequest) -> EvidenceActionBackendResult:
        self.calls.append(request)
        revision = None
        refs: tuple[str, ...] = ()
        if self.status is EvidenceActionStatus.SUCCEEDED:
            claim = self.repository.get_claim_internal(request.claim_id)
            assert claim is not None
            revision = claim.revision + 1
            self.repository.save_claim(
                claim.model_copy(update={'revision': revision, 'updated_at': datetime.now(UTC)}),
                expected_revision=claim.revision,
            )
            refs = (f'evidence-relation:{request.claim_id}:{request.evidence_id}',)
        result = EvidenceActionBackendResult(
            action_code=request.action_code,
            status=self.status,
            claim_id=request.claim_id,
            evidence_id=request.evidence_id,
            source_claim_id=request.source_claim_id,
            idempotency_key=request.idempotency_key,
            reason_code=self.status.value.upper(),
            resulting_revision=revision,
            state_change_refs=refs,
        )
        self.results[request.idempotency_key] = result
        return result


def test_execution_actions_are_confirmed_idempotent_internal_writes() -> None:
    for action_code, tool_name in (
        ('claim.reuse_evidence', 'evidence.reuse'),
        ('claim.remove_evidence', 'evidence.remove'),
    ):
        contract = action_contract(action_code)
        assert contract.allowed_actor_roles == (ActionActorRole.RUNTIME,)
        assert contract.requires_confirmation is True
        assert contract.side_effect_class is ActionSideEffectClass.INTERNAL_WRITE
        assert contract.state_effect is ActionStateEffect.CLAIM_MUTATION
        assert contract.idempotency_policy is ActionIdempotencyPolicy.REQUIRED
        assert contract.visibility == (ActionVisibility.CLAIMANT,)
        assert contract.permitted_tools == (tool_name,)
        assert tool_contract(tool_name).read_only is False


@pytest.mark.parametrize(
    ('change', 'reason'),
    [
        ('unconfirmed', 'CONFIRMATION_MISMATCH'),
        ('evidence', 'CONFIRMATION_MISMATCH'),
        ('source_claim', 'CONFIRMATION_MISMATCH'),
        ('proposal', 'CONFIRMATION_MISMATCH'),
        ('confirmation', 'CONFIRMATION_MISMATCH'),
        ('claimant', 'EVIDENCE_SCOPE_DENIED'),
    ],
)
def test_confirmation_and_claimant_scope_fail_closed(
    change: str,
    reason: str,
) -> None:
    confirmation = _confirmation()
    match change:
        case 'unconfirmed':
            confirmation = replace(confirmation, confirmed=False)
        case 'evidence':
            confirmation = replace(confirmation, evidence_id='evd_other')
        case 'source_claim':
            confirmation = replace(confirmation, source_claim_id='clm_other')
        case 'proposal':
            confirmation = replace(confirmation, proposal_ref='turn:other')
        case 'confirmation':
            confirmation = replace(confirmation, confirmation_ref='message:other')
        case 'claimant':
            confirmation = replace(confirmation, claimant_id='cus_other')
    result = execute_confirmed_evidence_action(
        _repository(),
        _command(),
        confirmation,
        None,
    )

    assert result.status is EvidenceActionStatus.REJECTED
    assert result.reason_code == reason
    assert 'reused' not in result.claimant_message


def test_missing_backend_is_typed_unavailable_without_mutation() -> None:
    repository = _repository()

    result = execute_confirmed_evidence_action(
        repository,
        _command(),
        _confirmation(),
        None,
    )

    assert result.status is EvidenceActionStatus.UNAVAILABLE
    assert result.reason_code == 'BACKEND_HANDLER_UNAVAILABLE'
    assert repository.get_claim_internal('clm_target').revision == 1  # type: ignore[union-attr]
    assert 'reused' not in result.claimant_message


@pytest.mark.parametrize(
    'command',
    [
        replace(_command(), payload={**_command().payload, 'evidence_id': ''}),
        replace(_command(), idempotency_key=None),
    ],
    ids=['blank-identifier', 'missing-idempotency-metadata'],
)
def test_malformed_evidence_commands_are_rejected(command: ClaimContextCommand) -> None:
    with pytest.raises(ValueError):
        execute_confirmed_evidence_action(_repository(), command, _confirmation(), None)


@pytest.mark.parametrize(
    'command',
    [
        replace(_command(), action_code='claim.update_fact'),
        replace(_command(), proposer_role=ActionActorRole.STAFF),
    ],
    ids=['unsupported-action', 'wrong-actor'],
)
def test_execution_rejects_commands_outside_the_runtime_evidence_boundary(
    command: ClaimContextCommand,
) -> None:
    with pytest.raises(ValueError):
        execute_confirmed_evidence_action(_repository(), command, _confirmation(), None)


def test_claim_read_failure_returns_retryable_dependency_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository()

    def fail_claim_read(claim_id: str) -> WorkingClaim | None:
        raise RuntimeError(claim_id)

    monkeypatch.setattr(repository, 'get_claim_internal', fail_claim_read)

    result = execute_confirmed_evidence_action(
        repository,
        _command(),
        _confirmation(),
        None,
    )

    assert result.status is EvidenceActionStatus.FAILED
    assert result.reason_code == 'DEPENDENCY_FAILURE'
    assert result.retryable is True


def test_evidence_read_failure_returns_retryable_dependency_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository()

    def fail_evidence_read(customer_id: str) -> list[EvidenceRecord]:
        raise RuntimeError(customer_id)

    monkeypatch.setattr(repository, 'list_evidence_for_customer', fail_evidence_read)

    result = execute_confirmed_evidence_action(
        repository,
        _command(),
        _confirmation(),
        None,
    )

    assert result.status is EvidenceActionStatus.FAILED
    assert result.reason_code == 'DEPENDENCY_FAILURE'
    assert result.retryable is True


def test_verified_success_and_same_key_retry_execute_once() -> None:
    repository = _repository()
    backend = RecordingBackend(repository)
    command = _command()
    confirmation = _confirmation()

    first = execute_confirmed_evidence_action(repository, command, confirmation, backend)
    replay = execute_confirmed_evidence_action(repository, command, confirmation, backend)

    assert first.status is EvidenceActionStatus.SUCCEEDED
    assert first.resulting_revision == 2
    assert first.state_change_refs == ('evidence-relation:clm_target:evd_history',)
    assert first.claimant_message == 'The Evidence was reused for this Claim.'
    assert replay == first
    assert len(backend.calls) == 1


@pytest.mark.parametrize(
    'status',
    [
        EvidenceActionStatus.REJECTED,
        EvidenceActionStatus.UNAVAILABLE,
        EvidenceActionStatus.FAILED,
        EvidenceActionStatus.UNKNOWN,
    ],
)
def test_backend_non_success_outcomes_remain_distinct(status: EvidenceActionStatus) -> None:
    repository = _repository()

    result = execute_confirmed_evidence_action(
        repository,
        _command('claim.remove_evidence'),
        _confirmation('claim.remove_evidence'),
        RecordingBackend(repository, status),
    )

    assert result.status is status
    assert result.resulting_revision is None
    assert repository.get_claim_internal('clm_target').revision == 1  # type: ignore[union-attr]
    assert 'removed for this Claim' not in result.claimant_message


@pytest.mark.parametrize(
    ('file_status', 'status'),
    [
        (EvidenceFileStatus.PROCESSING, EvidenceStatus.RECEIVED),
        (EvidenceFileStatus.READY, EvidenceStatus.INVALID),
        (EvidenceFileStatus.READY, EvidenceStatus.EXPIRED),
    ],
)
def test_reuse_rejects_ineligible_evidence_before_backend(
    file_status: EvidenceFileStatus,
    status: EvidenceStatus,
) -> None:
    repository = _repository()
    repository.save_evidence(
        _evidence('clm_source', file_status=file_status, status=status),
        'cus_owner',
    )
    backend = RecordingBackend(repository)

    result = execute_confirmed_evidence_action(
        repository,
        _command(),
        _confirmation(),
        backend,
    )

    assert result.status is EvidenceActionStatus.REJECTED
    assert result.reason_code == 'EVIDENCE_NOT_REUSABLE'
    assert backend.calls == []


def test_false_backend_success_is_not_presented_as_completed() -> None:
    repository = _repository()
    backend = RecordingBackend(repository)
    request = EvidenceActionRequest(
        action_code='claim.reuse_evidence',
        claimant_id='cus_owner',
        claim_id='clm_target',
        evidence_id='evd_history',
        source_claim_id='clm_source',
        expected_revision=1,
        idempotency_key='evidence-action-1',
        proposal_ref='turn:proposal-1',
        confirmation_ref='message:confirmation-1',
    )
    backend.results[request.idempotency_key] = EvidenceActionBackendResult(
        action_code=request.action_code,
        status=EvidenceActionStatus.SUCCEEDED,
        claim_id=request.claim_id,
        evidence_id=request.evidence_id,
        source_claim_id=request.source_claim_id,
        idempotency_key=request.idempotency_key,
        reason_code='SUCCEEDED',
        resulting_revision=2,
        state_change_refs=('claimed-but-not-persisted',),
    )

    result = execute_confirmed_evidence_action(
        repository,
        _command(),
        _confirmation(),
        backend,
    )

    assert result.status is EvidenceActionStatus.FAILED
    assert result.reason_code == 'UNVERIFIED_PERSISTED_RESULT'
    assert 'reused' not in result.claimant_message
