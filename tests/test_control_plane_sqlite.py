import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.domain.configuration import (
    ApprovalDecision,
    AuditEvent,
    ConfigurationApprovalRecord,
    ConfigurationImpact,
    ConfigurationRecord,
    ConfigurationState,
)
from backend.domain.operations import OperationKind, OperationRecord, OperationState
from backend.domain.release import ReleaseSetAuditEvent, ReleaseSetRecord, ReleaseSetState
from backend.repositories.configuration import (
    ConfigurationIdempotencyRecord,
    ConfigurationRepository,
    SQLiteConfigurationRepository,
)
from backend.repositories.operations import SQLiteOperationRepository
from backend.repositories.release_set import (
    ReleaseSetIdempotencyRecord,
    ReleaseSetRepository,
    SQLiteReleaseSetRepository,
)


def _timestamp() -> datetime:
    return datetime(2026, 9, 6, tzinfo=UTC)


def test_sqlite_configuration_repository_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / 'control-plane.sqlite3'
    record = ConfigurationRecord(
        configuration_id='cfg_persisted',
        domain='feature',
        revision=1,
        state=ConfigurationState.PUBLISHED,
        impact=ConfigurationImpact.NORMAL,
        values={'enabled': True},
        author='adm_demo',
        reason='Persist the active feature.',
        effective_time=_timestamp(),
        updated_at=_timestamp(),
    )
    event = AuditEvent(
        event_id='aud_persisted',
        configuration_id=record.configuration_id,
        revision=record.revision,
        actor='adm_demo',
        action='publish',
        reason=record.reason,
        outcome='succeeded',
        created_at=_timestamp(),
    )
    first = SQLiteConfigurationRepository(str(path))
    first.create(record)
    first.add_audit(event)
    first.save_idempotency(
        ConfigurationIdempotencyRecord(
            actor='adm_demo',
            route='POST /configurations',
            key='persisted-key',
            fingerprint='fingerprint',
            response={'configuration_id': record.configuration_id},
            status_code=201,
        )
    )

    reopened = SQLiteConfigurationRepository(str(path))
    assert reopened.get(record.configuration_id) == record
    assert reopened.active('feature') == record
    assert reopened.audits(record.configuration_id) == [event]
    assert (
        reopened.find_idempotency('adm_demo', 'POST /configurations', 'persisted-key') is not None
    )


def test_sqlite_configuration_repository_scopes_active_integrations_by_service(
    tmp_path: Path,
) -> None:
    path = tmp_path / 'control-plane.sqlite3'
    repository = SQLiteConfigurationRepository(str(path))
    assessor = ConfigurationRecord(
        configuration_id='cfg_assessor',
        domain='integration',
        configuration_key='assessor_service',
        revision=1,
        state=ConfigurationState.PUBLISHED,
        impact=ConfigurationImpact.NORMAL,
        values={
            'service_id': 'assessor_service',
            'capability': 'assessor_routing',
            'source': 'fixture',
        },
        author='adm_demo',
        reason='Publish the assessor integration.',
        effective_time=_timestamp(),
        updated_at=_timestamp(),
    )
    handoff = assessor.model_copy(
        update={
            'configuration_id': 'cfg_handoff',
            'configuration_key': 'handoff_dispatch',
            'values': {
                'service_id': 'handoff_dispatch',
                'capability': 'handoff_dispatch',
                'source': 'fixture',
            },
            'reason': 'Publish the handoff integration.',
        }
    )
    repository.create(assessor)
    repository.create(handoff)

    reopened = SQLiteConfigurationRepository(str(path))

    assert reopened.active('integration', 'assessor_service') == assessor
    assert reopened.active('integration', 'handoff_dispatch') == handoff
    assert reopened.active('integration') is None


def test_sqlite_configuration_repository_derives_key_for_legacy_integration(
    tmp_path: Path,
) -> None:
    path = tmp_path / 'control-plane.sqlite3'
    repository = SQLiteConfigurationRepository(str(path))
    legacy = ConfigurationRecord(
        configuration_id='cfg_legacy_assessor',
        domain='integration',
        configuration_key='assessor_service',
        revision=1,
        state=ConfigurationState.PUBLISHED,
        impact=ConfigurationImpact.NORMAL,
        values={
            'service_id': 'assessor_service',
            'capability': 'assessor_routing',
            'source': 'fixture',
        },
        author='adm_demo',
        reason='Preserve a pre-key integration record.',
        effective_time=_timestamp(),
        updated_at=_timestamp(),
    )
    payload = legacy.model_dump(mode='json')
    del payload['configuration_key']
    with sqlite3.connect(repository.path) as connection:
        connection.execute(
            'INSERT INTO configuration_records VALUES (?, ?, ?)',
            (legacy.configuration_id, legacy.revision, json.dumps(payload)),
        )

    reopened = SQLiteConfigurationRepository(str(path))

    assert reopened.active('integration', 'assessor_service') == legacy


def test_sqlite_configuration_approval_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / 'control-plane.sqlite3'
    approval = ConfigurationApprovalRecord(
        approval_id='apr_persisted',
        configuration_id='cfg_persisted',
        configuration_revision=2,
        reviewer='apr_demo',
        decision=ApprovalDecision.APPROVED,
        reason='Independent review completed.',
        created_at=_timestamp(),
    )
    first = SQLiteConfigurationRepository(str(path))
    first.add_approval(approval)

    reopened = SQLiteConfigurationRepository(str(path))
    assert reopened.approvals('cfg_persisted', 2) == [approval]


def test_sqlite_release_set_repository_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / 'control-plane.sqlite3'
    record = ReleaseSetRecord(
        release_set_id='rel_persisted',
        environment='local',
        runtime_profile='fixture',
        revision=1,
        state=ReleaseSetState.PUBLISHED,
        configuration_refs={},
        author='adm_demo',
        reason='Persist the active release.',
        effective_time=_timestamp(),
        updated_at=_timestamp(),
    )
    event = ReleaseSetAuditEvent(
        event_id='aud_release_persisted',
        release_set_id=record.release_set_id,
        revision=record.revision,
        actor='adm_demo',
        action='publish',
        reason=record.reason,
        outcome='succeeded',
        created_at=_timestamp(),
    )
    first = SQLiteReleaseSetRepository(str(path))
    first.create(record)
    first.add_audit(event)
    first.save_idempotency(
        ReleaseSetIdempotencyRecord(
            actor='adm_demo',
            route='POST /release-sets',
            key='persisted-key',
            fingerprint='fingerprint',
            response={'release_set_id': record.release_set_id},
            status_code=201,
        )
    )

    reopened = SQLiteReleaseSetRepository(str(path))
    assert reopened.get(record.release_set_id) == record
    assert reopened.active('local', 'fixture') == record
    assert reopened.audits(record.release_set_id) == [event]
    assert reopened.find_idempotency('adm_demo', 'POST /release-sets', 'persisted-key') is not None


def test_sqlite_operation_repository_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / 'control-plane.sqlite3'
    created = _timestamp()
    record = OperationRecord(
        operation_id='opr_persisted',
        kind=OperationKind.EVALUATION,
        subject_type='configuration',
        subject_id='cfg_persisted',
        state=OperationState.QUEUED,
        revision=1,
        status_url='/internal/v1/admin/operations/opr_persisted',
        progress_percent=0,
        created_at=created,
        updated_at=created,
    )
    first = SQLiteOperationRepository(str(path))
    first.create(record)
    completed = record.model_copy(
        update={
            'state': OperationState.SUCCEEDED,
            'revision': 2,
            'progress_percent': 100,
            'result': {'ok': True},
            'updated_at': created,
        }
    )
    first.save(completed, 1)

    reopened = SQLiteOperationRepository(str(path))
    assert reopened.get('opr_persisted') == completed
    assert reopened.list(state='succeeded') == [completed]
    assert reopened.metrics_records() == [completed]


def test_normal_app_uses_durable_control_plane_repositories(tmp_path: Path) -> None:
    settings = Settings(
        environment='test',
        identity_mode=IdentityMode.NORMAL,
        identity_db_path=str(tmp_path / 'customers.sqlite3'),
        staff_identity_db_path=str(tmp_path / 'staff.sqlite3'),
        control_plane_db_path=str(tmp_path / 'control-plane.sqlite3'),
    )
    app = create_app(settings)
    assert isinstance(app.state.configuration_repository, SQLiteConfigurationRepository)
    assert isinstance(app.state.release_set_repository, SQLiteReleaseSetRepository)
    assert isinstance(app.state.operation_repository, SQLiteOperationRepository)


def test_configuration_repositories_commit_atomic_publication_and_approval(
    tmp_path: Path,
) -> None:
    for repository in (
        ConfigurationRepository(),
        SQLiteConfigurationRepository(str(tmp_path / 'configuration-transitions.sqlite3')),
    ):
        previous = ConfigurationRecord(
            configuration_id='cfg_previous',
            domain='feature',
            revision=1,
            state=ConfigurationState.PUBLISHED,
            impact=ConfigurationImpact.NORMAL,
            values={'enabled': False},
            author='adm_demo',
            reason='Previous publication.',
            validation_evidence={'result': 'passed'},
            effective_time=_timestamp(),
            updated_at=_timestamp(),
        )
        candidate = previous.model_copy(
            update={
                'configuration_id': 'cfg_candidate',
                'state': ConfigurationState.DRAFT,
                'values': {'enabled': True},
                'reason': 'Candidate publication.',
                'effective_time': None,
            }
        )
        repository.create(previous)
        repository.create(candidate)
        superseded = previous.model_copy(
            update={'revision': 2, 'state': ConfigurationState.SUPERSEDED}
        )
        published = candidate.model_copy(
            update={
                'revision': 2,
                'state': ConfigurationState.PUBLISHED,
                'previous_version': previous.configuration_id,
                'effective_time': _timestamp(),
            }
        )
        events = (
            AuditEvent(
                event_id='aud_previous_superseded',
                configuration_id=previous.configuration_id,
                revision=2,
                previous_revision=1,
                actor='adm_demo',
                action='supersede',
                reason='Replaced.',
                outcome='succeeded',
                created_at=_timestamp(),
            ),
            AuditEvent(
                event_id='aud_candidate_published',
                configuration_id=candidate.configuration_id,
                revision=2,
                previous_revision=1,
                actor='adm_demo',
                action='publish',
                reason='Publish candidate.',
                outcome='succeeded',
                created_at=_timestamp(),
            ),
        )

        assert repository.replace_active(previous, superseded, published, 1, events) == published
        assert repository.active('feature') == published
        assert repository.audits(previous.configuration_id) == [events[0]]

        awaiting = ConfigurationRecord(
            configuration_id='cfg_approval',
            domain='model',
            revision=1,
            state=ConfigurationState.AWAITING_APPROVAL,
            impact=ConfigurationImpact.HIGH,
            values={'provider': 'test'},
            author='adm_author',
            reason='Await review.',
            validation_evidence={'result': 'passed'},
            updated_at=_timestamp(),
        )
        repository.create(awaiting)
        approval = ConfigurationApprovalRecord(
            approval_id='apr_transition',
            configuration_id=awaiting.configuration_id,
            configuration_revision=1,
            reviewer='adm_reviewer',
            decision=ApprovalDecision.REJECTED,
            reason='Return for correction.',
            created_at=_timestamp(),
        )
        returned = awaiting.model_copy(update={'revision': 2, 'state': ConfigurationState.DRAFT})
        approval_event = AuditEvent(
            event_id='aud_approval_transition',
            configuration_id=awaiting.configuration_id,
            revision=2,
            previous_revision=1,
            actor='adm_reviewer',
            action='return_to_draft',
            reason='Return for correction.',
            outcome='succeeded',
            created_at=_timestamp(),
        )
        assert (
            repository.save_approval_transition(approval, returned, 1, (approval_event,))
            == returned
        )
        assert repository.approvals(awaiting.configuration_id, 1) == [approval]
        assert repository.approvals(awaiting.configuration_id) == [approval]
        assert repository.get(awaiting.configuration_id) == returned

        rollback = previous.model_copy(
            update={
                'configuration_id': 'cfg_rollback',
                'rollback_target': previous.configuration_id,
                'previous_version': published.configuration_id,
            }
        )
        published_superseded = published.model_copy(
            update={'revision': 3, 'state': ConfigurationState.SUPERSEDED}
        )
        rollback_event = AuditEvent(
            event_id='aud_configuration_rollback',
            configuration_id=rollback.configuration_id,
            revision=1,
            previous_revision=2,
            actor='adm_demo',
            action='rollback',
            reason='Restore previous configuration.',
            outcome='succeeded',
            created_at=_timestamp(),
        )
        assert (
            repository.replace_active_with_new(
                published, published_superseded, rollback, (rollback_event,)
            )
            == rollback
        )
        assert repository.active('feature') == rollback


def test_configuration_repositories_reject_stale_and_conflicting_records(tmp_path: Path) -> None:
    for repository in (
        ConfigurationRepository(),
        SQLiteConfigurationRepository(str(tmp_path / 'configuration-conflicts.sqlite3')),
    ):
        record = ConfigurationRecord(
            configuration_id='cfg_conflict',
            domain='feature',
            revision=1,
            state=ConfigurationState.DRAFT,
            impact=ConfigurationImpact.NORMAL,
            values={'enabled': True},
            author='adm_demo',
            reason='Conflict test.',
            updated_at=_timestamp(),
        )
        repository.create(record)
        with pytest.raises(ValueError, match='stale_revision'):
            repository.save(record.model_copy(update={'revision': 2}), 99)

        idempotency = ConfigurationIdempotencyRecord(
            actor='adm_demo',
            route='POST /configurations',
            key='conflict-key',
            fingerprint='first',
            response={'configuration_id': record.configuration_id},
            status_code=201,
        )
        repository.save_idempotency(idempotency)
        repository.save_idempotency(idempotency)
        with pytest.raises(ValueError, match='idempotency_conflict'):
            repository.save_idempotency(
                ConfigurationIdempotencyRecord(
                    actor=idempotency.actor,
                    route=idempotency.route,
                    key=idempotency.key,
                    fingerprint='different',
                    response=idempotency.response,
                    status_code=201,
                )
            )
        assert repository.find_idempotency('adm_demo', 'POST /configurations', 'missing') is None

        approval = ConfigurationApprovalRecord(
            approval_id='apr_conflict',
            configuration_id=record.configuration_id,
            configuration_revision=1,
            reviewer='adm_reviewer',
            decision=ApprovalDecision.APPROVED,
            reason='Approve once.',
            created_at=_timestamp(),
        )
        repository.add_approval(approval)
        with pytest.raises(ValueError, match='approval_exists'):
            repository.add_approval(
                approval.model_copy(update={'approval_id': 'apr_conflict_duplicate'})
            )


def test_release_set_repositories_commit_atomic_replace_and_rollback(
    tmp_path: Path,
) -> None:
    for repository in (
        ReleaseSetRepository(),
        SQLiteReleaseSetRepository(str(tmp_path / 'release-transitions.sqlite3')),
    ):
        previous = ReleaseSetRecord(
            release_set_id='rel_previous',
            environment='test',
            runtime_profile='fixture',
            revision=1,
            state=ReleaseSetState.PUBLISHED,
            configuration_refs={},
            author='adm_demo',
            reason='Previous release.',
            effective_time=_timestamp(),
            updated_at=_timestamp(),
        )
        candidate = previous.model_copy(
            update={
                'release_set_id': 'rel_candidate',
                'state': ReleaseSetState.DRAFT,
                'reason': 'Candidate release.',
                'effective_time': None,
            }
        )
        repository.create(previous)
        repository.create(candidate)
        superseded = previous.model_copy(
            update={'revision': 2, 'state': ReleaseSetState.SUPERSEDED}
        )
        published = candidate.model_copy(
            update={
                'revision': 2,
                'state': ReleaseSetState.PUBLISHED,
                'previous_release_set_id': previous.release_set_id,
                'effective_time': _timestamp(),
            }
        )
        events = (
            ReleaseSetAuditEvent(
                event_id='aud_release_previous',
                release_set_id=previous.release_set_id,
                revision=2,
                previous_revision=1,
                actor='adm_demo',
                action='supersede',
                reason='Replaced.',
                outcome='succeeded',
                created_at=_timestamp(),
            ),
            ReleaseSetAuditEvent(
                event_id='aud_release_candidate',
                release_set_id=candidate.release_set_id,
                revision=2,
                previous_revision=1,
                actor='adm_demo',
                action='publish',
                reason='Publish candidate.',
                outcome='succeeded',
                created_at=_timestamp(),
            ),
        )
        assert repository.replace_active(previous, superseded, published, 1, events) == published
        assert repository.active('test', 'fixture') == published

        rollback = previous.model_copy(
            update={
                'release_set_id': 'rel_rollback',
                'rollback_target': previous.release_set_id,
                'previous_release_set_id': published.release_set_id,
            }
        )
        published_superseded = published.model_copy(
            update={'revision': 3, 'state': ReleaseSetState.SUPERSEDED}
        )
        rollback_event = ReleaseSetAuditEvent(
            event_id='aud_release_rollback',
            release_set_id=rollback.release_set_id,
            revision=1,
            previous_revision=2,
            actor='adm_demo',
            action='rollback',
            reason='Restore previous release.',
            outcome='succeeded',
            created_at=_timestamp(),
        )
        assert (
            repository.replace_active_with_new(
                published, published_superseded, rollback, (rollback_event,)
            )
            == rollback
        )
        assert repository.active('test', 'fixture') == rollback
