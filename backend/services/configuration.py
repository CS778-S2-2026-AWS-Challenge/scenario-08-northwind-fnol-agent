from collections.abc import Sequence

from backend.core.errors import ApiError
from backend.domain.configuration import (
    AuditEvent,
    ConfigurationCreate,
    ConfigurationImpact,
    ConfigurationPatch,
    ConfigurationRecord,
    ConfigurationState,
    DataProfileConfiguration,
    DataRuntimeProfileValue,
    ModelRuntimeConfiguration,
    ObjectStorageAdapterValue,
    TransitionRequest,
    ValidationRequest,
    now_utc,
)
from backend.repositories.configuration import ConfigurationRepository

_PROFILE_OBJECT_STORAGE_COMPATIBILITY = {
    DataRuntimeProfileValue.FIXTURE: {
        ObjectStorageAdapterValue.FIXTURE,
        ObjectStorageAdapterValue.S3_COMPATIBLE,
    },
    DataRuntimeProfileValue.LOCAL_MVP: {ObjectStorageAdapterValue.S3_COMPATIBLE},
    DataRuntimeProfileValue.CLOUDFLARE: {ObjectStorageAdapterValue.S3_COMPATIBLE},
    DataRuntimeProfileValue.MONGODB: {ObjectStorageAdapterValue.S3_COMPATIBLE},
    DataRuntimeProfileValue.AWS: {ObjectStorageAdapterValue.S3_COMPATIBLE},
}


def _error(status: int, code: str, message: str) -> ApiError:
    return ApiError(status_code=status, code=code, message=message)


def _audit(
    repo: ConfigurationRepository,
    record: ConfigurationRecord,
    actor: str,
    action: str,
    reason: str,
    outcome: str,
    *,
    previous_revision: int | None = None,
    changed_fields: Sequence[str] = (),
) -> None:
    repo.add_audit(
        AuditEvent(
            event_id=repo.new_event_id(),
            configuration_id=record.configuration_id,
            revision=record.revision,
            previous_revision=previous_revision,
            actor=actor,
            action=action,
            reason=reason,
            outcome=outcome,
            changed_fields=sorted(set(changed_fields)),
            created_at=now_utc(),
        )
    )


def create(
    repo: ConfigurationRepository, payload: ConfigurationCreate, actor: str
) -> ConfigurationRecord:
    record = ConfigurationRecord(
        configuration_id=repo.new_configuration_id(),
        revision=1,
        state=ConfigurationState.DRAFT,
        author=actor,
        updated_at=now_utc(),
        **payload.model_dump(),
    )
    _reject_plaintext_secrets(record.values)
    _validate_secret_references(record.secret_references)
    _validate_configuration_values(record.domain, record.values, for_validation=False)
    saved = repo.create(record)
    _audit(
        repo,
        saved,
        actor,
        'create_draft',
        payload.reason,
        'succeeded',
        changed_fields=('domain', 'impact', 'values', 'secret_references', 'state'),
    )
    return saved


def read(
    repo: ConfigurationRepository, configuration_id: str, revision: int | None = None
) -> ConfigurationRecord:
    record = repo.get(configuration_id, revision)
    if record is None:
        raise _error(404, 'CONFIGURATION_NOT_FOUND', 'The configuration was not found.')
    return record


def read_active(repo: ConfigurationRepository, domain: str) -> ConfigurationRecord:
    """Return the single published configuration available to runtime consumers.

    Args:
        repo: Provider-neutral configuration repository.
        domain: Configuration domain requested by the runtime.

    Returns:
        The active immutable published configuration.

    Raises:
        ApiError: If the domain has no published configuration.
    """
    record = repo.active(domain)
    if record is None:
        raise _error(
            404,
            'ACTIVE_CONFIGURATION_NOT_FOUND',
            'No published configuration is available for the requested domain.',
        )
    return record


def patch(
    repo: ConfigurationRepository,
    configuration_id: str,
    payload: ConfigurationPatch,
    actor: str,
    expected_revision: int,
) -> ConfigurationRecord:
    current = read(repo, configuration_id)
    if current.revision != expected_revision:
        raise _error(409, 'REVISION_CONFLICT', 'The configuration revision is stale.')
    if current.state is not ConfigurationState.DRAFT:
        raise _error(
            400, 'INVALID_CONFIGURATION_TRANSITION', 'Only a draft configuration can be updated.'
        )
    values = payload.values if payload.values is not None else current.values
    _reject_plaintext_secrets(values)
    secret_references = (
        payload.secret_references
        if payload.secret_references is not None
        else current.secret_references
    )
    _validate_secret_references(secret_references)
    _validate_configuration_values(current.domain, values, for_validation=False)
    updated = current.model_copy(
        update={
            'revision': current.revision + 1,
            'values': values,
            'secret_references': secret_references,
            'reason': payload.reason,
            'updated_at': now_utc(),
        }
    )
    saved = repo.save(updated, expected_revision)
    changed_fields = ['reason']
    if payload.values is not None and payload.values != current.values:
        changed_fields.append('values')
    if (
        payload.secret_references is not None
        and payload.secret_references != current.secret_references
    ):
        changed_fields.append('secret_references')
    _audit(
        repo,
        saved,
        actor,
        'update_draft',
        payload.reason,
        'succeeded',
        previous_revision=current.revision,
        changed_fields=changed_fields,
    )
    return saved


def validate(
    repo: ConfigurationRepository,
    configuration_id: str,
    payload: ValidationRequest,
    actor: str,
    expected_revision: int,
) -> ConfigurationRecord:
    current = read(repo, configuration_id)
    if current.revision != expected_revision:
        _audit(repo, current, actor, 'validate', 'The configuration revision is stale.', 'rejected')
        raise _error(409, 'REVISION_CONFLICT', 'The configuration revision is stale.')
    if current.state is not ConfigurationState.DRAFT:
        _audit(repo, current, actor, 'validate', 'Only a draft can enter validation.', 'rejected')
        raise _error(400, 'INVALID_CONFIGURATION_TRANSITION', 'Only a draft can enter validation.')
    evidence = {
        'scenarios': [item.model_dump() for item in payload.scenario_results],
        'result': 'passed',
    }
    try:
        _validate_configuration_values(current.domain, current.values, for_validation=True)
    except ApiError as error:
        _audit(repo, current, actor, 'validate', error.message, 'rejected')
        raise
    failed = [item for item in payload.scenario_results if item.outcome == 'failed']
    if failed:
        evidence['result'] = 'failed'
        _audit(repo, current, actor, 'validate', 'Validation failed.', 'rejected')
        raise _error(
            422,
            'VALIDATION_FAILED',
            'One or more required validation scenarios failed.',
        )
    previous = repo.active(current.domain) if current.impact is ConfigurationImpact.NORMAL else None
    updated = current.model_copy(
        update={
            'revision': current.revision + 1,
            'state': ConfigurationState.AWAITING_APPROVAL
            if current.impact is ConfigurationImpact.HIGH
            else ConfigurationState.PUBLISHED,
            'validation_evidence': evidence,
            'effective_time': now_utc() if current.impact is ConfigurationImpact.NORMAL else None,
            'previous_version': previous.configuration_id if previous is not None else None,
            'updated_at': now_utc(),
        }
    )
    if previous is not None:
        superseded = previous.model_copy(
            update={
                'state': ConfigurationState.SUPERSEDED,
                'revision': previous.revision + 1,
                'updated_at': now_utc(),
            }
        )
        supersede_event = AuditEvent(
            event_id=repo.new_event_id(),
            configuration_id=superseded.configuration_id,
            revision=superseded.revision,
            previous_revision=previous.revision,
            actor=actor,
            action='supersede',
            reason='Replaced by a newer publication.',
            outcome='succeeded',
            changed_fields=['state'],
            created_at=now_utc(),
        )
        validate_event_record = updated
        validate_event = AuditEvent(
            event_id=repo.new_event_id(),
            configuration_id=validate_event_record.configuration_id,
            revision=validate_event_record.revision,
            previous_revision=current.revision,
            actor=actor,
            action='validate',
            reason='Validation completed.',
            outcome='succeeded',
            changed_fields=[
                'effective_time',
                'previous_version',
                'state',
                'validation_evidence',
            ],
            created_at=now_utc(),
        )
        saved = repo.replace_active(
            previous,
            superseded,
            updated,
            expected_revision,
            (supersede_event, validate_event),
        )
    else:
        saved = repo.save(updated, expected_revision)
        _audit(
            repo,
            saved,
            actor,
            'validate',
            'Validation completed.',
            'succeeded',
            previous_revision=current.revision,
            changed_fields=('effective_time', 'state', 'validation_evidence'),
        )
    return saved


def publish(
    repo: ConfigurationRepository,
    configuration_id: str,
    payload: TransitionRequest,
    actor: str,
    expected_revision: int,
) -> ConfigurationRecord:
    current = read(repo, configuration_id)
    if current.revision != expected_revision:
        _audit(repo, current, actor, 'publish', 'The configuration revision is stale.', 'rejected')
        raise _error(409, 'REVISION_CONFLICT', 'The configuration revision is stale.')
    if (
        current.state is not ConfigurationState.AWAITING_APPROVAL
        or current.validation_evidence is None
    ):
        _audit(
            repo,
            current,
            actor,
            'publish',
            'The configuration is not ready for publication.',
            'rejected',
        )
        raise _error(
            400,
            'INVALID_CONFIGURATION_TRANSITION',
            'The configuration is not ready for publication.',
        )
    updated = current.model_copy(
        update={
            'revision': current.revision + 1,
            'state': ConfigurationState.PUBLISHED,
            'effective_time': now_utc(),
            'updated_at': now_utc(),
        }
    )
    previous = repo.active(current.domain)
    if previous is not None:
        updated = updated.model_copy(update={'previous_version': previous.configuration_id})
        superseded = previous.model_copy(
            update={
                'state': ConfigurationState.SUPERSEDED,
                'revision': previous.revision + 1,
                'updated_at': now_utc(),
            }
        )
        saved = repo.replace_active(
            previous,
            superseded,
            updated,
            expected_revision,
            (
                AuditEvent(
                    event_id=repo.new_event_id(),
                    configuration_id=superseded.configuration_id,
                    revision=superseded.revision,
                    previous_revision=previous.revision,
                    actor=actor,
                    action='supersede',
                    reason='Replaced by a newer publication.',
                    outcome='succeeded',
                    changed_fields=['state'],
                    created_at=now_utc(),
                ),
                AuditEvent(
                    event_id=repo.new_event_id(),
                    configuration_id=updated.configuration_id,
                    revision=updated.revision,
                    previous_revision=current.revision,
                    actor=actor,
                    action='publish',
                    reason=payload.reason,
                    outcome='succeeded',
                    changed_fields=['effective_time', 'previous_version', 'state'],
                    created_at=now_utc(),
                ),
            ),
        )
    else:
        saved = repo.save(updated, expected_revision)
        _audit(
            repo,
            saved,
            actor,
            'publish',
            payload.reason,
            'succeeded',
            previous_revision=current.revision,
            changed_fields=('effective_time', 'state'),
        )
    return saved


def withdraw(
    repo: ConfigurationRepository,
    configuration_id: str,
    payload: TransitionRequest,
    actor: str,
    expected_revision: int,
) -> ConfigurationRecord:
    current = read(repo, configuration_id)
    if current.revision != expected_revision:
        _audit(repo, current, actor, 'withdraw', 'The configuration revision is stale.', 'rejected')
        raise _error(409, 'REVISION_CONFLICT', 'The configuration revision is stale.')
    if current.state not in {
        ConfigurationState.DRAFT,
        ConfigurationState.PUBLISHED,
        ConfigurationState.AWAITING_APPROVAL,
    }:
        _audit(
            repo,
            current,
            actor,
            'withdraw',
            'The configuration cannot be withdrawn from its current state.',
            'rejected',
        )
        raise _error(
            400,
            'INVALID_CONFIGURATION_TRANSITION',
            'The configuration cannot be withdrawn from its current state.',
        )
    updated = current.model_copy(
        update={
            'revision': current.revision + 1,
            'state': ConfigurationState.WITHDRAWN,
            'reason': payload.reason,
            'updated_at': now_utc(),
        }
    )
    saved = repo.save(updated, expected_revision)
    _audit(
        repo,
        saved,
        actor,
        'withdraw',
        payload.reason,
        'succeeded',
        previous_revision=current.revision,
        changed_fields=('reason', 'state'),
    )
    return saved


def rollback(
    repo: ConfigurationRepository,
    configuration_id: str,
    payload: TransitionRequest,
    actor: str,
    expected_revision: int,
) -> ConfigurationRecord:
    current = read(repo, configuration_id)
    if current.revision != expected_revision:
        _audit(repo, current, actor, 'rollback', 'The configuration revision is stale.', 'rejected')
        raise _error(409, 'REVISION_CONFLICT', 'The configuration revision is stale.')
    if current.state is not ConfigurationState.PUBLISHED:
        _audit(
            repo,
            current,
            actor,
            'rollback',
            'Only a published configuration can be rolled back.',
            'rejected',
        )
        raise _error(
            400,
            'INVALID_CONFIGURATION_TRANSITION',
            'Only a published configuration can be rolled back.',
        )
    target_id = payload.rollback_target or current.rollback_target or current.previous_version
    if target_id is None:
        _audit(repo, current, actor, 'rollback', 'A rollback target is required.', 'rejected')
        raise _error(400, 'ROLLBACK_TARGET_REQUIRED', 'A rollback target is required.')
    target = read(repo, target_id)
    if target.validation_evidence is None or target.state not in {
        ConfigurationState.SUPERSEDED,
        ConfigurationState.PUBLISHED,
    }:
        _audit(repo, current, actor, 'rollback', 'The rollback target is not approved.', 'rejected')
        raise _error(
            400,
            'INVALID_ROLLBACK_TARGET',
            'The rollback target is not an approved immutable version.',
        )
    new = target.model_copy(
        update={
            'configuration_id': repo.new_configuration_id(),
            'revision': 1,
            'state': ConfigurationState.PUBLISHED,
            'author': actor,
            'reason': payload.reason,
            'previous_version': current.configuration_id,
            'rollback_target': target.configuration_id,
            'effective_time': now_utc(),
            'updated_at': now_utc(),
        }
    )
    superseded = current.model_copy(
        update={
            'state': ConfigurationState.SUPERSEDED,
            'revision': current.revision + 1,
            'updated_at': now_utc(),
        }
    )
    saved = repo.replace_active_with_new(
        current,
        superseded,
        new,
        (
            AuditEvent(
                event_id=repo.new_event_id(),
                configuration_id=superseded.configuration_id,
                revision=superseded.revision,
                previous_revision=current.revision,
                actor=actor,
                action='supersede',
                reason='Replaced by a rollback publication.',
                outcome='succeeded',
                changed_fields=['state'],
                created_at=now_utc(),
            ),
            AuditEvent(
                event_id=repo.new_event_id(),
                configuration_id=new.configuration_id,
                revision=new.revision,
                previous_revision=current.revision,
                actor=actor,
                action='rollback',
                reason=payload.reason,
                outcome='succeeded',
                changed_fields=[
                    'effective_time',
                    'previous_version',
                    'rollback_target',
                    'state',
                ],
                created_at=now_utc(),
            ),
        ),
    )
    return saved


def audit(repo: ConfigurationRepository, configuration_id: str) -> list[AuditEvent]:
    read(repo, configuration_id)
    return repo.audits(configuration_id)


def _reject_plaintext_secrets(values: dict[str, object]) -> None:
    if any(
        'secret' in key.lower() or 'password' in key.lower() or 'api_key' in key.lower()
        for key in values
    ):
        raise _error(
            422, 'SECRET_VALUE_FORBIDDEN', 'Secret values must be supplied as protected references.'
        )


def _validate_secret_references(references: dict[str, str]) -> None:
    if any(
        not value.startswith(('secret://', 'vault://', 'arn:')) for value in references.values()
    ):
        raise _error(
            422,
            'SECRET_REFERENCE_INVALID',
            'Secret references must use an approved protected-reference format.',
        )


def _validate_configuration_values(
    domain: str, values: dict[str, object], *, for_validation: bool
) -> None:
    """Validate the structured provider configuration consumed by the runtime boundary."""
    if domain == 'model':
        try:
            ModelRuntimeConfiguration.model_validate(values)
        except ValueError as error:
            raise _error(
                422,
                'PROVIDER_CONFIGURATION_INVALID',
                'model requires a complete provider-neutral runtime configuration.',
            ) from error
        return
    if domain != 'data_profile':
        return
    try:
        profile = DataProfileConfiguration.model_validate(values)
    except ValueError as error:
        raise _error(
            422,
            'PROVIDER_CONFIGURATION_INVALID',
            'data_profile requires one runtime profile and one object-storage adapter.',
        ) from error
    compatible_adapters = _PROFILE_OBJECT_STORAGE_COMPATIBILITY[profile.data_runtime_profile]
    if profile.object_storage_adapter not in compatible_adapters:
        raise _error(
            422,
            'PROVIDER_CONFIGURATION_INVALID',
            'The selected runtime profile is incompatible with the object-storage adapter.',
        )
    if (
        profile.data_runtime_profile
        in {
            DataRuntimeProfileValue.CLOUDFLARE,
            DataRuntimeProfileValue.MONGODB,
            DataRuntimeProfileValue.AWS,
        }
        and for_validation
    ):
        raise _error(
            422,
            'PROVIDER_CONFIGURATION_UNAVAILABLE',
            'The selected provider profile is not verified and cannot be published.',
        )
