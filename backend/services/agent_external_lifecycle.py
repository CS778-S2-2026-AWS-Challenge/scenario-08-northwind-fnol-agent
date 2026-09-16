"""Build the bounded external-service lifecycle context for the claimant Agent.

The repository owns task and result persistence; the canonical registry owns lifecycle
meaning.  This module only joins those two read surfaces and deliberately omits provider
payloads, delivery evidence, and internal staff wording from the model context.
"""

from __future__ import annotations

from backend.domain.external_service_registry import (
    ExternalLifecycleStatus,
    ExternalServiceLifecycleProjection,
    ExternalTaskResultVerification,
    InvalidExternalLifecycleTransition,
    assert_projection_provenance,
    build_lifecycle_projection,
    capability_context,
    service_registry_entry,
)
from backend.domain.external_services import (
    ASSESSOR_SERVICE_IDENTITY,
    ExternalTaskOperationStatus,
    ExternalTaskResult,
    assert_result_matches_task,
    request_provenance,
)
from backend.domain.models import AssessorRoutingResult, AssessorRoutingStatus
from backend.repositories.protocols import PersistenceRepository

MAX_EXTERNAL_LIFECYCLE_PROJECTIONS = 8


class ExternalLifecycleContextError(ValueError):
    """A persisted external record cannot be represented safely to the Agent."""

    retryable = False


class ExternalLifecycleContextUnavailable(ExternalLifecycleContextError):
    """The authoritative external lifecycle records could not be read."""

    retryable = True


def _result_status(result_verification: ExternalTaskResultVerification) -> ExternalLifecycleStatus:
    """Keep result arrival separate from operation acknowledgement and verification."""

    if result_verification is ExternalTaskResultVerification.UNVERIFIED:
        return ExternalLifecycleStatus.RESULT_RECEIVED
    return ExternalLifecycleStatus.RESULT_VERIFIED


def build_agent_external_lifecycle_context(
    repository: PersistenceRepository,
    claim_id: str,
    assessor_routing: AssessorRoutingResult | None = None,
    product_family: str | None = None,
) -> tuple[ExternalServiceLifecycleProjection, ...]:
    """Return the complete bounded lifecycle context for one Claim.

    The consumer verifies repository scoping, task/result identity, capability provenance,
    and the canonical registry mapping. More than eight tasks fail closed because silently
    dropping an unresolved operation would let the model reason from incomplete state.
    """

    try:
        tasks = repository.list_external_tasks_internal(claim_id)
        results = repository.list_external_task_results_internal(claim_id)
    except RuntimeError as error:
        raise ExternalLifecycleContextUnavailable(
            f'External lifecycle records for Claim {claim_id} are unavailable.'
        ) from error

    if len(tasks) > MAX_EXTERNAL_LIFECYCLE_PROJECTIONS:
        raise ExternalLifecycleContextError(
            f'Claim {claim_id} has {len(tasks)} external tasks; the Agent context limit is '
            f'{MAX_EXTERNAL_LIFECYCLE_PROJECTIONS}.'
        )
    if any(task.claim_id != claim_id for task in tasks):
        raise ExternalLifecycleContextError(
            f'The external task read for Claim {claim_id} returned a cross-Claim record.'
        )
    task_ids = {task.task_id for task in tasks}
    if len(task_ids) != len(tasks):
        raise ExternalLifecycleContextError(
            f'The external task read for Claim {claim_id} returned duplicate task identities.'
        )
    by_task: dict[str, ExternalTaskResult] = {}
    for returned_result in results:
        if returned_result.task_id not in task_ids or returned_result.claim_id != claim_id:
            raise ExternalLifecycleContextError(
                f'{returned_result.result_id}: result is not linked to a task on Claim {claim_id}.'
            )
        if returned_result.task_id in by_task:
            raise ExternalLifecycleContextError(
                f'{returned_result.task_id}: more than one external result was returned.'
            )
        by_task[returned_result.task_id] = returned_result

    projections: list[ExternalServiceLifecycleProjection] = []
    for task in tasks:
        try:
            entry = service_registry_entry(task.service_identity)
        except KeyError as error:
            raise ExternalLifecycleContextError(
                f'{task.task_id}: no canonical registry entry for {task.service_identity}.'
            ) from error
        if not entry.uses_external_task:
            raise ExternalLifecycleContextError(
                f'{task.task_id}: manual service {task.service_identity} cannot have an '
                'ExternalTask record.'
            )
        latest_result = by_task.get(task.task_id)
        if latest_result is not None:
            try:
                assert_result_matches_task(latest_result, task)
            except ValueError as error:
                raise ExternalLifecycleContextError(str(error)) from error
        try:
            assert_projection_provenance(
                service_identity=task.service_identity,
                request_provenance=request_provenance(task).value,
            )
        except (KeyError, InvalidExternalLifecycleTransition) as error:
            raise ExternalLifecycleContextError(f'{task.task_id}: {error}') from error
        try:
            service_progress_status = None
            service_progress_reference = None
            if (
                task.service_identity == ASSESSOR_SERVICE_IDENTITY
                and task.status is ExternalTaskOperationStatus.ACCEPTED
                and assessor_routing is not None
                and assessor_routing.routing_status
                in {AssessorRoutingStatus.QUEUED, AssessorRoutingStatus.ASSIGNED}
            ):
                service_progress_status = assessor_routing.routing_status.value
                service_progress_reference = (
                    assessor_routing.assessor_reference or assessor_routing.queue_reference
                )
            projections.append(
                build_lifecycle_projection(
                    service_identity=task.service_identity,
                    operation_status=task.status.value,
                    result_status=(
                        _result_status(latest_result.verification)
                        if latest_result is not None
                        else None
                    ),
                    result_verification=(
                        latest_result.verification if latest_result is not None else None
                    ),
                    provider_reference=task.provider_reference,
                    service_progress_status=service_progress_status,
                    service_progress_reference=service_progress_reference,
                )
            )
        except (KeyError, InvalidExternalLifecycleTransition) as error:
            raise ExternalLifecycleContextError(
                f'{task.task_id}: the canonical lifecycle projection is invalid.'
            ) from error
    active_identities = {item.service_identity for item in projections}
    available = (
        [
            item
            for item in capability_context(product_family)
            if item.service_identity not in active_identities
        ]
        if product_family is not None
        else []
    )
    combined = [*projections, *available]
    if len(combined) > MAX_EXTERNAL_LIFECYCLE_PROJECTIONS:
        combined = combined[:MAX_EXTERNAL_LIFECYCLE_PROJECTIONS]
    return tuple(combined)
