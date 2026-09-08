from queue import Empty, Queue
from threading import Thread
from time import perf_counter
from typing import Any

from backend.core.errors import ApiError
from backend.domain.configuration import (
    REGISTERED_INTEGRATION_CAPABILITIES,
    REGISTERED_INTEGRATION_IDS,
)
from backend.domain.integration_health import (
    IntegrationHealthCheckPage,
    IntegrationHealthCheckRecord,
)
from backend.domain.integration_registry import (
    IntegrationHealthState,
    IntegrationStatusPage,
    IntegrationStatusProjection,
)
from backend.domain.operations import OperationKind, OperationRecord, OperationState
from backend.repositories.integration_health import IntegrationHealthRepository
from backend.repositories.operations import OperationRepository
from backend.services.runtime_integrations import (
    RuntimeIntegrationConfigurationError,
    RuntimeIntegrationPolicySnapshot,
)
from backend.services.support import decode_cursor, encode_cursor, now_utc

_INTEGRATION_SOURCES: tuple[tuple[str, str, str, str], ...] = (
    ('persistence', 'Claim persistence', 'persistence', 'data_runtime_bundle.repository'),
    ('evidence_storage', 'Evidence storage', 'evidence', 'data_runtime_bundle.evidence_storage'),
    ('policy', 'Policy lookup', 'policy_lookup', 'data_runtime_bundle.policy_history'),
    (
        'claim_history',
        'Claim history lookup',
        'claim_history_lookup',
        'data_runtime_bundle.policy_history',
    ),
    (
        'knowledge_documents',
        'Knowledge document store',
        'knowledge_ingestion',
        'data_runtime_bundle.knowledge_documents',
    ),
    (
        'knowledge_retrieval',
        'Knowledge retrieval',
        'knowledge_search',
        'data_runtime_bundle.knowledge_retrieval',
    ),
    ('claims_service', 'Claims service', 'claim_creation', 'claims_service_adapter'),
    ('assessor_service', 'Assessor routing', 'assessor_routing', 'assessor_service_adapter'),
    ('handoff_dispatch', 'Handoff dispatch', 'handoff_dispatch', 'handoff_dispatch_adapter'),
)

if tuple(item[0] for item in _INTEGRATION_SOURCES) != REGISTERED_INTEGRATION_IDS:
    raise RuntimeError('Integration registry definitions and configuration IDs are out of sync.')


def registered_capability(integration_id: str) -> str | None:
    """Return the canonical capability for a registered integration ID."""

    return REGISTERED_INTEGRATION_CAPABILITIES.get(integration_id)


def list_integrations(
    app_state: Any,
    policy: RuntimeIntegrationPolicySnapshot,
    limit: int,
    cursor: str | None,
) -> IntegrationStatusPage:
    projections: list[IntegrationStatusProjection] = [
        _project_integration(
            app_state,
            integration_id=integration_id,
            label=label,
            capability=capability,
            state_path=state_path,
            policy=policy,
        )
        for integration_id, label, capability, state_path in _INTEGRATION_SOURCES
    ]

    offset = decode_cursor(cursor)
    bounded_limit = min(limit, 100)
    selected = projections[offset : offset + bounded_limit]
    next_offset = offset + len(selected)
    next_cursor = encode_cursor(next_offset) if next_offset < len(projections) else None
    return IntegrationStatusPage(items=selected, page={'next_cursor': next_cursor})


def get_integration(
    app_state: Any,
    policy: RuntimeIntegrationPolicySnapshot,
    integration_id: str,
) -> IntegrationStatusProjection:
    """Run one bounded, provider-neutral health check for a registered integration."""

    definition = next(
        (item for item in _INTEGRATION_SOURCES if item[0] == integration_id),
        None,
    )
    if definition is None:
        raise ApiError(
            status_code=404,
            code='INTEGRATION_NOT_FOUND',
            message='The requested integration is not registered.',
        )
    registered_id, label, capability, state_path = definition
    return _project_integration(
        app_state,
        integration_id=registered_id,
        label=label,
        capability=capability,
        state_path=state_path,
        policy=policy,
    )


def check_integration(
    app_state: Any,
    health_repository: IntegrationHealthRepository,
    policy: RuntimeIntegrationPolicySnapshot,
    integration_id: str,
    operation_repository: OperationRepository | None = None,
) -> IntegrationHealthCheckRecord:
    operation: OperationRecord | None = None
    if operation_repository is not None:
        operation_id = operation_repository.new_operation_id()
        created_at = now_utc()
        operation = operation_repository.create(
            OperationRecord(
                operation_id=operation_id,
                kind=OperationKind.INTEGRATION_HEALTH_CHECK,
                subject_type='integration',
                subject_id=integration_id,
                state=OperationState.QUEUED,
                revision=1,
                status_url=f'/internal/v1/admin/operations/{operation_id}',
                progress_percent=0,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        running = operation.model_copy(
            update={
                'state': OperationState.RUNNING,
                'revision': 2,
                'progress_percent': 50,
                'updated_at': now_utc(),
            }
        )
        operation_repository.save(running, operation.revision)
        operation = running
    try:
        projection = get_integration(app_state, policy, integration_id)
        record = IntegrationHealthCheckRecord(
            check_id=health_repository.new_check_id(),
            integration_id=projection.integration_id,
            health=projection.health,
            source=projection.source,
            implementation=projection.implementation,
            latency_ms=projection.latency_ms or 0,
            failure_code=projection.failure_code,
            operation_id=operation.operation_id if operation is not None else None,
            checked_at=now_utc(),
        )
        saved = health_repository.create(record)
    except ApiError as exc:
        if operation_repository is not None and operation is not None:
            failed = operation.model_copy(
                update={
                    'state': OperationState.FAILED,
                    'revision': operation.revision + 1,
                    'progress_percent': 100,
                    'error_code': exc.code,
                    'updated_at': now_utc(),
                }
            )
            operation_repository.save(failed, operation.revision)
        raise
    if operation_repository is not None and operation is not None:
        completed = operation.model_copy(
            update={
                'state': OperationState.SUCCEEDED,
                'revision': operation.revision + 1,
                'progress_percent': 100,
                'result': {'check_id': saved.check_id, 'health': saved.health.value},
                'updated_at': now_utc(),
            }
        )
        operation_repository.save(completed, operation.revision)
    return saved


def health_history(
    health_repository: IntegrationHealthRepository,
    integration_id: str,
    limit: int,
) -> IntegrationHealthCheckPage:
    if registered_capability(integration_id) is None:
        raise ApiError(
            status_code=404,
            code='INTEGRATION_NOT_FOUND',
            message='The requested integration is not registered.',
        )
    return IntegrationHealthCheckPage(
        items=health_repository.list(integration_id, limit),
        page={'next_cursor': None},
    )


def _project_integration(
    app_state: Any,
    *,
    integration_id: str,
    label: str,
    capability: str,
    state_path: str,
    policy: RuntimeIntegrationPolicySnapshot,
) -> IntegrationStatusProjection:
    started = perf_counter()
    record = policy.record(integration_id)
    configuration_ids = [record.configuration_id] if record is not None else []
    try:
        configuration = policy.require(integration_id)
        adapter = _resolve_state_path(app_state, state_path)
        raw_status, failure_code = _connection_status(
            adapter,
            configuration.health_check_timeout_seconds if configuration is not None else 5.0,
        )
        health = _health_state(raw_status)
        source = _source(adapter, health)
        implementation = type(adapter).__name__
    except ApiError as error:
        health = IntegrationHealthState.UNAVAILABLE
        source = 'unavailable'
        failure_code = error.code
        implementation = 'unavailable'
    except RuntimeIntegrationConfigurationError:
        health = IntegrationHealthState.UNAVAILABLE
        source = 'unavailable'
        failure_code = 'INTEGRATION_CONFIGURATION_INVALID'
        implementation = 'unavailable'
    except Exception:
        health = IntegrationHealthState.UNKNOWN
        source = 'unavailable'
        failure_code = 'INTEGRATION_STATUS_FAILED'
        implementation = 'unavailable'
    latency_ms = round(max(0.0, (perf_counter() - started) * 1000), 3)
    return IntegrationStatusProjection(
        integration_id=integration_id,
        label=label,
        capability=capability,
        health=health,
        implementation=implementation,
        source=source,
        configuration_ids=configuration_ids,
        latency_ms=latency_ms,
        failure_code=failure_code,
    )


def _resolve_state_path(app_state: Any, path: str) -> Any:
    value = app_state
    for segment in path.split('.'):
        value = getattr(value, segment)
    return value


def _connection_status(adapter: Any, timeout_seconds: float) -> tuple[str, str | None]:
    status_method = getattr(adapter, 'connection_status', None)
    if not callable(status_method):
        return IntegrationHealthState.UNKNOWN.value, 'CONNECTION_STATUS_UNSUPPORTED'
    outcomes: Queue[tuple[str, str | None]] = Queue(maxsize=1)

    def read_status() -> None:
        try:
            outcomes.put((str(status_method()), None))
        except Exception:
            outcomes.put((IntegrationHealthState.UNKNOWN.value, 'INTEGRATION_STATUS_FAILED'))

    worker = Thread(target=read_status, daemon=True)
    worker.start()
    try:
        status, failure = outcomes.get(timeout=timeout_seconds)
    except Empty:
        return IntegrationHealthState.UNAVAILABLE.value, 'INTEGRATION_HEALTH_TIMEOUT'
    if failure is not None:
        return status, failure
    if status == IntegrationHealthState.UNAVAILABLE.value:
        return status, 'INTEGRATION_UNAVAILABLE'
    if status == IntegrationHealthState.PENDING_CONFIRMATION.value:
        return status, 'INTEGRATION_PENDING_CONFIRMATION'
    return status, None


def _health_state(status: str) -> IntegrationHealthState:
    try:
        return IntegrationHealthState(status)
    except ValueError:
        return IntegrationHealthState.UNKNOWN


def _source(adapter: Any, health: IntegrationHealthState) -> str:
    if health not in {
        IntegrationHealthState.USING_FIXTURE,
        IntegrationHealthState.VERIFIED,
        IntegrationHealthState.CONFIGURED_SERVICE,
    }:
        return 'unavailable'
    source = getattr(adapter, 'integration_source', None)
    if source is not None:
        return str(getattr(source, 'value', source))
    if health is IntegrationHealthState.USING_FIXTURE:
        return 'fixture'
    if health in {
        IntegrationHealthState.VERIFIED,
        IntegrationHealthState.CONFIGURED_SERVICE,
    }:
        return 'configured_service'
    return 'unavailable'
