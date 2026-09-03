from datetime import UTC, datetime

from backend.core.errors import ApiError
from backend.domain.agent_action_commands import ClaimContextCommand, build_claim_context_command
from backend.domain.agent_action_registry import ActionActorRole, ExecutionAuthority
from backend.domain.models import (
    Channel,
    ClaimState,
    CustomerNextStep,
    ResponsibleParty,
    SessionRecord,
    WorkflowState,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.protocols import RevisionConflict
from backend.services.agent_action_execution import (
    ClaimContextExecutionStatus,
    ClaimContextHandlerBinding,
    ClaimContextHandlerOutcome,
    execute_claim_context_command,
)


def _seed_claim(
    repository: FixtureRepository,
    *,
    workflow_state: WorkflowState = WorkflowState.COLLECTING,
) -> WorkingClaim:
    timestamp = datetime.now(UTC)
    claim = WorkingClaim(
        claim_id='clm_execution',
        customer_id='cus_execution',
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        claim_state=ClaimState(workflow_state=workflow_state),
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Describe the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )
    session = SessionRecord(
        session_id='ses_execution',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        started_at=timestamp,
        last_active_at=timestamp,
    )
    repository.create_claim(claim, session)
    return claim


def _fact_patch_command(*, expected_revision: int = 1) -> ClaimContextCommand:
    return build_claim_context_command(
        'claim.apply_fact_patch',
        {
            'claim_id': 'clm_execution',
            'fact_patches': [],
            'expected_revision': expected_revision,
        },
        proposer_role=ActionActorRole.RUNTIME,
        approved_authority=ExecutionAuthority.CLAIMANT_STAFF_OR_PUBLISHED_RULE,
        authority_reference='published-rule:fact-patch-v1',
        workflow_state=WorkflowState.COLLECTING,
        idempotency_key=f'patch-{expected_revision}',
    )


def test_execution_gate_applies_only_after_current_state_checks() -> None:
    repository = FixtureRepository()
    _seed_claim(repository)
    command = _fact_patch_command()
    calls = 0

    def apply_patch(_command: ClaimContextCommand) -> ClaimContextHandlerOutcome:
        nonlocal calls
        calls += 1
        current = repository.get_claim_internal('clm_execution')
        assert current is not None
        updated = current.model_copy(
            update={
                'revision': current.revision + 1,
                'updated_at': datetime.now(UTC),
            }
        )
        repository.save_claim(updated, expected_revision=current.revision)
        return ClaimContextHandlerOutcome(
            claim_id=updated.claim_id,
            resulting_revision=updated.revision,
        )

    result = execute_claim_context_command(
        repository,
        command,
        {
            command.action_code: ClaimContextHandlerBinding(
                tool_name='claim_store.compare_and_set',
                handler=apply_patch,
            )
        },
    )

    assert calls == 1
    assert result.status is ClaimContextExecutionStatus.APPLIED
    assert result.reason_code == 'APPLIED'
    assert result.claim_id == 'clm_execution'
    assert result.resulting_revision == 2
    assert result.failure_policy is None


def test_stale_revision_is_rejected_before_handler_side_effect() -> None:
    repository = FixtureRepository()
    claim = _seed_claim(repository)
    updated = claim.model_copy(
        update={
            'revision': 2,
            'updated_at': datetime.now(UTC),
        }
    )
    repository.save_claim(updated, expected_revision=1)
    command = _fact_patch_command(expected_revision=1)
    calls = 0

    def should_not_run(_command: ClaimContextCommand) -> ClaimContextHandlerOutcome:
        nonlocal calls
        calls += 1
        return ClaimContextHandlerOutcome(claim_id='clm_execution', resulting_revision=3)

    result = execute_claim_context_command(
        repository,
        command,
        {
            command.action_code: ClaimContextHandlerBinding(
                tool_name='claim_store.compare_and_set',
                handler=should_not_run,
            )
        },
    )

    assert calls == 0
    assert result.status is ClaimContextExecutionStatus.REJECTED
    assert result.reason_code == 'REVISION_CONFLICT'
    assert result.resulting_revision == 2
    assert result.retryable is True
    assert result.failure_policy == command.failure_policy


def test_changed_workflow_state_is_rejected_before_handler_side_effect() -> None:
    repository = FixtureRepository()
    _seed_claim(repository, workflow_state=WorkflowState.READY_FOR_NEXT)
    command = _fact_patch_command()
    calls = 0

    def should_not_run(_command: ClaimContextCommand) -> ClaimContextHandlerOutcome:
        nonlocal calls
        calls += 1
        return ClaimContextHandlerOutcome(claim_id='clm_execution', resulting_revision=2)

    result = execute_claim_context_command(
        repository,
        command,
        {
            command.action_code: ClaimContextHandlerBinding(
                tool_name='claim_store.compare_and_set',
                handler=should_not_run,
            )
        },
    )

    assert calls == 0
    assert result.status is ClaimContextExecutionStatus.REJECTED
    assert result.reason_code == 'WORKFLOW_STATE_CHANGED'
    assert result.failure_policy == command.failure_policy


def test_handler_must_match_command_tool_allow_list() -> None:
    repository = FixtureRepository()
    _seed_claim(repository)
    command = _fact_patch_command()

    result = execute_claim_context_command(
        repository,
        command,
        {
            command.action_code: ClaimContextHandlerBinding(
                tool_name='claims_service.create_claim',
                handler=lambda _command: ClaimContextHandlerOutcome(
                    claim_id='clm_execution',
                    resulting_revision=2,
                ),
            )
        },
    )

    assert result.status is ClaimContextExecutionStatus.REJECTED
    assert result.reason_code == 'TOOL_NOT_ALLOWED'
    assert result.failure_policy == command.failure_policy


def test_repository_conflict_is_returned_as_bounded_rejection() -> None:
    repository = FixtureRepository()
    _seed_claim(repository)
    command = _fact_patch_command()

    def conflict(_command: ClaimContextCommand) -> ClaimContextHandlerOutcome:
        raise RevisionConflict(current_revision=4)

    result = execute_claim_context_command(
        repository,
        command,
        {
            command.action_code: ClaimContextHandlerBinding(
                tool_name='claim_store.compare_and_set',
                handler=conflict,
            )
        },
    )

    assert result.status is ClaimContextExecutionStatus.REJECTED
    assert result.reason_code == 'REVISION_CONFLICT'
    assert result.resulting_revision == 4
    assert result.retryable is True
    assert result.failure_policy == command.failure_policy


def test_dependency_failure_does_not_claim_execution_succeeded() -> None:
    repository = FixtureRepository()
    _seed_claim(repository)
    command = _fact_patch_command()

    def dependency_failure(_command: ClaimContextCommand) -> ClaimContextHandlerOutcome:
        raise ApiError(
            status_code=503,
            code='DEPENDENCY_UNAVAILABLE',
            message='The dependency is unavailable.',
            retryable=True,
        )

    result = execute_claim_context_command(
        repository,
        command,
        {
            command.action_code: ClaimContextHandlerBinding(
                tool_name='claim_store.compare_and_set',
                handler=dependency_failure,
            )
        },
    )

    stored = repository.get_claim_internal('clm_execution')
    assert stored is not None
    assert stored.revision == 1
    assert result.status is ClaimContextExecutionStatus.FAILED
    assert result.reason_code == 'DEPENDENCY_UNAVAILABLE'
    assert result.retryable is True
    assert result.failure_policy == command.failure_policy


def test_unpersisted_handler_success_is_rejected_as_invalid_execution_result() -> None:
    repository = FixtureRepository()
    _seed_claim(repository)
    command = _fact_patch_command()

    result = execute_claim_context_command(
        repository,
        command,
        {
            command.action_code: ClaimContextHandlerBinding(
                tool_name='claim_store.compare_and_set',
                handler=lambda _command: ClaimContextHandlerOutcome(
                    claim_id='clm_execution',
                    resulting_revision=2,
                ),
            )
        },
    )

    assert result.status is ClaimContextExecutionStatus.FAILED
    assert result.reason_code == 'INVALID_EXECUTION_RESULT'
    assert result.failure_policy == command.failure_policy


def test_unsupported_command_is_rejected_without_execution() -> None:
    repository = FixtureRepository()
    _seed_claim(repository)
    command = _fact_patch_command()

    result = execute_claim_context_command(repository, command, {})

    assert result.status is ClaimContextExecutionStatus.REJECTED
    assert result.reason_code == 'UNSUPPORTED_ACTION'
    assert result.failure_policy == command.failure_policy
