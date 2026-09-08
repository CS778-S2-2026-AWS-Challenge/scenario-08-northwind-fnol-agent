"""Aggregate persisted Control Plane and model operation records."""

from datetime import UTC, datetime, timedelta

from backend.domain.configuration import OperationalConfiguration
from backend.domain.operations import (
    ModelCostMetrics,
    ModelUsageMetrics,
    OperationalAlertProjection,
    OperationKind,
    OperationMetricsProjection,
    OperationRecord,
    RateLimitMetrics,
)
from backend.repositories.operations import OperationRepository
from backend.services.runtime_configuration import (
    RuntimeConfigurationResolutionError,
    RuntimeConfigurationResolver,
)


def _integer(result: dict[str, object] | None, field: str) -> int | None:
    value = result.get(field) if result is not None else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _model_identifier(record: OperationRecord) -> str | None:
    value = record.result.get('provider_model') if record.result is not None else None
    return value if isinstance(value, str) and value else None


def _operational_configuration(
    resolver: RuntimeConfigurationResolver,
) -> tuple[OperationalConfiguration | None, str | None, int | None]:
    try:
        record = resolver.resolve('operational')
    except RuntimeConfigurationResolutionError:
        return None, None, None
    if record is None:
        return None, None, None
    try:
        configuration = OperationalConfiguration.model_validate(record.values)
    except ValueError:
        return None, record.configuration_id, record.revision
    return configuration, record.configuration_id, record.revision


def _alert(
    code: str,
    metric: str,
    observed: int | None,
    threshold: int,
) -> OperationalAlertProjection:
    status = 'unknown' if observed is None else 'triggered' if observed >= threshold else 'clear'
    return OperationalAlertProjection(
        alert_code=code,
        metric=metric,
        status=status,
        observed=observed,
        threshold=threshold,
    )


def operation_metrics(
    repository: OperationRepository,
    resolver: RuntimeConfigurationResolver,
    *,
    observed_at: datetime | None = None,
) -> OperationMetricsProjection:
    """Build the administration projection from persisted operation records.

    Args:
        repository: Provider-neutral Control Plane operation repository.
        resolver: Resolver for the active published operational configuration.
        observed_at: Optional deterministic timestamp for rate-limit window evaluation.

    Returns:
        Bounded usage, cost, rate-limit, alert, and operation aggregates.
    """

    records = repository.metrics_records()
    by_state: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for record in records:
        by_state[record.state.value] = by_state.get(record.state.value, 0) + 1
        by_kind[record.kind.value] = by_kind.get(record.kind.value, 0) + 1

    model_records = [item for item in records if item.kind is OperationKind.MODEL_INVOCATION]
    reported_records = [
        item for item in model_records if _integer(item.result, 'total_tokens') is not None
    ]
    usage = ModelUsageMetrics(
        calls=len(model_records),
        reported_calls=len(reported_records),
        input_tokens=sum(_integer(item.result, 'input_tokens') or 0 for item in model_records),
        output_tokens=sum(_integer(item.result, 'output_tokens') or 0 for item in model_records),
        total_tokens=sum(_integer(item.result, 'total_tokens') or 0 for item in model_records),
    )

    configuration, configuration_id, configuration_revision = _operational_configuration(resolver)
    priced_calls = 0
    estimated_microunits = 0
    if configuration is not None:
        rates = {item.model_identifier: item for item in configuration.model_cost_rates}
        for record in model_records:
            rate = rates.get(_model_identifier(record) or '')
            input_tokens = _integer(record.result, 'input_tokens')
            output_tokens = _integer(record.result, 'output_tokens')
            if rate is None or input_tokens is None or output_tokens is None:
                continue
            estimated_microunits += (
                input_tokens * rate.input_microunits_per_million_tokens
                + output_tokens * rate.output_microunits_per_million_tokens
                + 500_000
            ) // 1_000_000
            priced_calls += 1
    unpriced_calls = len(model_records) - priced_calls
    cost_status = (
        'unconfigured' if configuration is None else 'partial' if unpriced_calls else 'configured'
    )
    cost = ModelCostMetrics(
        status=cost_status,
        currency=configuration.currency if configuration is not None else None,
        estimated_microunits=estimated_microunits,
        priced_calls=priced_calls,
        unpriced_calls=unpriced_calls,
        configuration_id=configuration_id,
        configuration_revision=configuration_revision,
    )

    now = observed_at or datetime.now(UTC)
    rate_limit_records: list[OperationRecord] = []
    if configuration is not None:
        window_start = now - timedelta(seconds=configuration.rate_limit_window_seconds)
        rate_limit_records = [
            item
            for item in model_records
            if item.error_code == 'MODEL_RATE_LIMIT' and item.created_at >= window_start
        ]
    latest_rate_limit = max(
        (item.created_at for item in rate_limit_records),
        default=None,
    )
    rate_limit = RateLimitMetrics(
        status=(
            'unconfigured'
            if configuration is None
            else 'limited'
            if rate_limit_records
            else 'clear'
        ),
        events_in_window=len(rate_limit_records),
        window_seconds=(
            configuration.rate_limit_window_seconds if configuration is not None else None
        ),
        latest_event_at=latest_rate_limit,
    )

    alerts: list[OperationalAlertProjection] = []
    if configuration is not None:
        alerts = [
            _alert(
                'operations.total_tokens',
                'total_tokens',
                usage.total_tokens if usage.reported_calls == usage.calls else None,
                configuration.token_alert_threshold,
            ),
            _alert(
                'operations.estimated_cost',
                'estimated_cost_microunits',
                estimated_microunits if not unpriced_calls else None,
                configuration.cost_alert_threshold_microunits,
            ),
            _alert(
                'operations.rate_limit_events',
                'rate_limit_events',
                len(rate_limit_records),
                configuration.rate_limit_alert_count,
            ),
        ]

    return OperationMetricsProjection(
        total=len(records),
        by_state=by_state,
        by_kind=by_kind,
        usage=usage,
        cost=cost,
        rate_limit=rate_limit,
        alerts=alerts,
    )
