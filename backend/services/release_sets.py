from collections.abc import Mapping

from backend.core.errors import ApiError
from backend.domain.configuration import ConfigurationRecord, ConfigurationState
from backend.domain.knowledge_admin import KnowledgeSourceRecord
from backend.domain.release import (
    ConfigurationReference,
    KnowledgeReference,
    ReleaseSetAuditEvent,
    ReleaseSetCreate,
    ReleaseSetRecord,
    ReleaseSetState,
    ReleaseSetValidationRequest,
    RuntimeSnapshot,
    now_utc,
)
from backend.repositories.configuration import ConfigurationRepository
from backend.repositories.knowledge_admin import KnowledgeAdminRepository
from backend.repositories.release_set import ReleaseSetRepository


def _error(status: int, code: str, message: str) -> ApiError:
    return ApiError(status_code=status, code=code, message=message)


def create(
    releases: ReleaseSetRepository,
    configurations: ConfigurationRepository,
    knowledge: KnowledgeAdminRepository,
    payload: ReleaseSetCreate,
    actor: str,
) -> ReleaseSetRecord:
    _assert_references_exist(configurations, payload.configuration_refs)
    _assert_integration_references_exist(configurations, payload.integration_refs)
    _assert_knowledge_references_exist(knowledge, payload.knowledge_refs)
    record = ReleaseSetRecord(
        release_set_id=releases.new_release_set_id(),
        revision=1,
        state=ReleaseSetState.DRAFT,
        author=actor,
        updated_at=now_utc(),
        **payload.model_dump(),
    )
    saved = releases.create(record)
    _audit(releases, saved, actor, 'create_draft', payload.reason, 'succeeded')
    return saved


def read(releases: ReleaseSetRepository, release_set_id: str) -> ReleaseSetRecord:
    record = releases.get(release_set_id)
    if record is None:
        raise _error(404, 'RELEASE_SET_NOT_FOUND', 'The release set was not found.')
    return record


def validate(
    releases: ReleaseSetRepository,
    configurations: ConfigurationRepository,
    knowledge: KnowledgeAdminRepository,
    release_set_id: str,
    payload: ReleaseSetValidationRequest,
    actor: str,
    expected_revision: int,
) -> ReleaseSetRecord:
    current = read(releases, release_set_id)
    _assert_revision(releases, current, expected_revision, actor, 'validate')
    if current.state is not ReleaseSetState.DRAFT:
        _reject(releases, current, actor, 'validate', 'Only a draft can enter validation.')
    _assert_references_published(configurations, current.configuration_refs)
    _assert_integration_references_published(configurations, current.integration_refs)
    _assert_knowledge_references_published(knowledge, current.knowledge_refs)
    failed = [item for item in payload.scenario_results if item.outcome == 'failed']
    evidence = {
        'scenarios': [item.model_dump() for item in payload.scenario_results],
        'result': 'failed' if failed else 'passed',
    }
    if failed:
        _audit(releases, current, actor, 'validate', 'Validation failed.', 'rejected')
        raise _error(422, 'RELEASE_SET_VALIDATION_FAILED', 'One or more release scenarios failed.')
    updated = current.model_copy(
        update={
            'revision': current.revision + 1,
            'state': ReleaseSetState.VALIDATION,
            'validation_evidence': evidence,
            'updated_at': now_utc(),
        }
    )
    saved = releases.save(updated, expected_revision)
    _audit(releases, saved, actor, 'validate', 'Release validation completed.', 'succeeded')
    return saved


def publish(
    releases: ReleaseSetRepository,
    release_set_id: str,
    reason: str,
    actor: str,
    expected_revision: int,
) -> ReleaseSetRecord:
    current = read(releases, release_set_id)
    _assert_revision(releases, current, expected_revision, actor, 'publish')
    if current.state is not ReleaseSetState.VALIDATION or current.validation_evidence is None:
        _reject(releases, current, actor, 'publish', 'The release set is not validated.')
    updated = current.model_copy(
        update={
            'revision': current.revision + 1,
            'state': ReleaseSetState.PUBLISHED,
            'effective_time': now_utc(),
            'updated_at': now_utc(),
        }
    )
    previous = releases.active(current.environment, current.runtime_profile)
    if previous is None:
        saved = releases.save(updated, expected_revision)
        _audit(releases, saved, actor, 'publish', reason, 'succeeded')
        return saved
    updated = updated.model_copy(update={'previous_release_set_id': previous.release_set_id})
    superseded = previous.model_copy(
        update={
            'revision': previous.revision + 1,
            'state': ReleaseSetState.SUPERSEDED,
            'updated_at': now_utc(),
        }
    )
    saved = releases.replace_active(
        previous,
        superseded,
        updated,
        expected_revision,
        (
            ReleaseSetAuditEvent(
                event_id=releases.new_event_id(),
                release_set_id=superseded.release_set_id,
                revision=superseded.revision,
                previous_revision=previous.revision,
                actor=actor,
                action='supersede',
                reason='Replaced by a newer release set.',
                outcome='succeeded',
                created_at=now_utc(),
            ),
            ReleaseSetAuditEvent(
                event_id=releases.new_event_id(),
                release_set_id=updated.release_set_id,
                revision=updated.revision,
                previous_revision=current.revision,
                actor=actor,
                action='publish',
                reason=reason,
                outcome='succeeded',
                created_at=now_utc(),
            ),
        ),
    )
    return saved


def rollback(
    releases: ReleaseSetRepository,
    release_set_id: str,
    target_id: str,
    reason: str,
    actor: str,
    expected_revision: int,
) -> ReleaseSetRecord:
    current = read(releases, release_set_id)
    _assert_revision(releases, current, expected_revision, actor, 'rollback')
    if current.state is not ReleaseSetState.PUBLISHED:
        _reject(
            releases, current, actor, 'rollback', 'Only a published release set can be rolled back.'
        )
    target = releases.get(target_id)
    if target is None or target.state is not ReleaseSetState.SUPERSEDED:
        _audit(
            releases,
            current,
            actor,
            'rollback',
            'The rollback target is not available.',
            'rejected',
        )
        raise _error(
            400,
            'INVALID_RELEASE_SET_ROLLBACK_TARGET',
            'The rollback target is not an approved prior release set.',
        )
    if (target.environment, target.runtime_profile) != (
        current.environment,
        current.runtime_profile,
    ):
        _audit(
            releases,
            current,
            actor,
            'rollback',
            'The rollback target has a different scope.',
            'rejected',
        )
        raise _error(
            422,
            'RELEASE_SET_SCOPE_MISMATCH',
            'The rollback target must use the same environment and runtime profile.',
        )
    new = target.model_copy(
        update={
            'release_set_id': releases.new_release_set_id(),
            'revision': 1,
            'state': ReleaseSetState.PUBLISHED,
            'author': actor,
            'reason': reason,
            'effective_time': now_utc(),
            'previous_release_set_id': current.release_set_id,
            'rollback_target': target.release_set_id,
            'updated_at': now_utc(),
        }
    )
    superseded = current.model_copy(
        update={
            'revision': current.revision + 1,
            'state': ReleaseSetState.SUPERSEDED,
            'updated_at': now_utc(),
        }
    )
    return releases.replace_active_with_new(
        current,
        superseded,
        new,
        (
            ReleaseSetAuditEvent(
                event_id=releases.new_event_id(),
                release_set_id=superseded.release_set_id,
                revision=superseded.revision,
                previous_revision=current.revision,
                actor=actor,
                action='supersede',
                reason='Replaced by a rollback release set.',
                outcome='succeeded',
                created_at=now_utc(),
            ),
            ReleaseSetAuditEvent(
                event_id=releases.new_event_id(),
                release_set_id=new.release_set_id,
                revision=new.revision,
                actor=actor,
                action='rollback',
                reason=reason,
                outcome='succeeded',
                created_at=now_utc(),
            ),
        ),
    )


def snapshot(
    releases: ReleaseSetRepository,
    configurations: ConfigurationRepository,
    knowledge: KnowledgeAdminRepository,
    environment: str,
    runtime_profile: str,
) -> RuntimeSnapshot:
    release = releases.active(environment, runtime_profile)
    if release is None:
        raise _error(404, 'ACTIVE_RELEASE_SET_NOT_FOUND', 'No published release set is available.')
    resolved: dict[str, object] = {}
    for domain, reference in release.configuration_refs.items():
        configuration = configurations.get(reference.configuration_id, reference.revision)
        if configuration is None or configuration.state is not ConfigurationState.PUBLISHED:
            raise _error(
                409,
                'RELEASE_SET_CONFIGURATION_UNAVAILABLE',
                'A published release references a configuration that is no longer available.',
            )
        resolved[domain] = configuration
    resolved_knowledge: dict[str, KnowledgeSourceRecord] = {}
    _assert_knowledge_references_published(knowledge, release.knowledge_refs)
    for product, knowledge_reference in release.knowledge_refs.items():
        knowledge_record = knowledge.get(knowledge_reference.knowledge_id)
        if knowledge_record is not None:
            resolved_knowledge[product] = knowledge_record
    resolved_integrations: dict[str, ConfigurationRecord] = {}
    _assert_integration_references_published(configurations, release.integration_refs)
    for service_id, integration_reference in release.integration_refs.items():
        integration = configurations.get(
            integration_reference.configuration_id,
            integration_reference.revision,
        )
        if integration is not None:
            resolved_integrations[service_id] = integration
    return RuntimeSnapshot(
        release_set_id=release.release_set_id,
        environment=environment,
        runtime_profile=runtime_profile,
        loaded_at=now_utc(),
        configurations=resolved,
        integrations=resolved_integrations,
        knowledge=resolved_knowledge,
    )


def audit(releases: ReleaseSetRepository, release_set_id: str) -> list[ReleaseSetAuditEvent]:
    read(releases, release_set_id)
    return releases.audits(release_set_id)


def _assert_references_exist(
    configurations: ConfigurationRepository,
    references: Mapping[str, ConfigurationReference],
) -> None:
    for domain, reference in references.items():
        configuration = configurations.get(reference.configuration_id, reference.revision)
        if configuration is None or configuration.domain != domain:
            raise _error(
                422, 'RELEASE_SET_CONFIGURATION_NOT_FOUND', f'No configuration exists for {domain}.'
            )


def _assert_references_published(
    configurations: ConfigurationRepository,
    references: Mapping[str, ConfigurationReference],
) -> None:
    _assert_references_exist(configurations, references)
    for domain, reference in references.items():
        configuration = configurations.get(reference.configuration_id, reference.revision)
        if configuration is None or configuration.state is not ConfigurationState.PUBLISHED:
            raise _error(
                422, 'RELEASE_SET_CONFIGURATION_NOT_PUBLISHED', f'{domain} is not published.'
            )


def _assert_knowledge_references_exist(
    knowledge: KnowledgeAdminRepository,
    references: Mapping[str, KnowledgeReference],
) -> None:
    for product, knowledge_reference in references.items():
        knowledge_record = knowledge.get(knowledge_reference.knowledge_id)
        if (
            knowledge_record is None
            or knowledge_record.revision != knowledge_reference.revision
            or knowledge_record.product != product
        ):
            raise _error(
                422,
                'RELEASE_SET_KNOWLEDGE_NOT_FOUND',
                f'No knowledge version exists for {product}.',
            )


def _assert_integration_references_exist(
    configurations: ConfigurationRepository,
    references: Mapping[str, ConfigurationReference],
) -> None:
    for service_id, integration_reference in references.items():
        configuration = configurations.get(
            integration_reference.configuration_id,
            integration_reference.revision,
        )
        if (
            configuration is None
            or configuration.domain != 'integration'
            or configuration.values.get('service_id') != service_id
        ):
            raise _error(
                422,
                'RELEASE_SET_INTEGRATION_NOT_FOUND',
                f'No integration configuration exists for {service_id}.',
            )


def _assert_integration_references_published(
    configurations: ConfigurationRepository,
    references: Mapping[str, ConfigurationReference],
) -> None:
    _assert_integration_references_exist(configurations, references)
    for service_id, integration_reference in references.items():
        configuration = configurations.get(
            integration_reference.configuration_id,
            integration_reference.revision,
        )
        if configuration is None or configuration.state is not ConfigurationState.PUBLISHED:
            raise _error(
                422,
                'RELEASE_SET_INTEGRATION_NOT_PUBLISHED',
                f'Integration {service_id} is not published.',
            )


def _assert_knowledge_references_published(
    knowledge: KnowledgeAdminRepository,
    references: Mapping[str, KnowledgeReference],
) -> None:
    _assert_knowledge_references_exist(knowledge, references)
    for product, knowledge_reference in references.items():
        knowledge_record = knowledge.get(knowledge_reference.knowledge_id)
        if knowledge_record is None or knowledge_record.state.value != 'published':
            raise _error(
                422,
                'RELEASE_SET_KNOWLEDGE_NOT_PUBLISHED',
                f'Knowledge for {product} is not published.',
            )


def _assert_revision(
    releases: ReleaseSetRepository,
    record: ReleaseSetRecord,
    expected_revision: int,
    actor: str,
    action: str,
) -> None:
    if record.revision != expected_revision:
        _audit(releases, record, actor, action, 'The release set revision is stale.', 'rejected')
        raise _error(409, 'REVISION_CONFLICT', 'The release set revision is stale.')


def _audit(
    releases: ReleaseSetRepository,
    record: ReleaseSetRecord,
    actor: str,
    action: str,
    reason: str,
    outcome: str,
) -> None:
    releases.add_audit(
        ReleaseSetAuditEvent(
            event_id=releases.new_event_id(),
            release_set_id=record.release_set_id,
            revision=record.revision,
            actor=actor,
            action=action,
            reason=reason,
            outcome=outcome,
            created_at=now_utc(),
        )
    )


def _reject(
    releases: ReleaseSetRepository,
    record: ReleaseSetRecord,
    actor: str,
    action: str,
    reason: str,
) -> None:
    _audit(releases, record, actor, action, reason, 'rejected')
    raise _error(400, 'INVALID_RELEASE_SET_TRANSITION', reason)
