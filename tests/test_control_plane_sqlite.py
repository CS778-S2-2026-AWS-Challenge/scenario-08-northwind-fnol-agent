import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

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
    SQLiteConfigurationRepository,
)
from backend.repositories.operations import SQLiteOperationRepository
from backend.repositories.release_set import ReleaseSetIdempotencyRecord, SQLiteReleaseSetRepository


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
