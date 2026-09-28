from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.domain.feedback import FeedbackRecord
from backend.repositories.feedback import (
    FeedbackIdempotencyConflict,
    FeedbackRepository,
    SQLiteFeedbackRepository,
)


def _headers(actor: str, key: str | None = None) -> dict[str, str]:
    headers = {'Authorization': f'Bearer synthetic-{actor}'}
    if key is not None:
        headers['Idempotency-Key'] = key
    return headers


def _client(repository: FeedbackRepository | None = None) -> TestClient:
    return TestClient(
        create_app(
            Settings(environment='test', identity_mode=IdentityMode.DEVELOPER),
            feedback_repository=repository,
        )
    )


def test_staff_feedback_is_validated_idempotent_and_admin_only_to_read() -> None:
    repository = FeedbackRepository()
    with _client(repository) as client:
        assert client.post('/api/v1/staff/feedback', json={'message': 'Useful'}).status_code == 401
        assert (
            client.post(
                '/api/v1/staff/feedback',
                headers=_headers('claimant', 'claimant-feedback'),
                json={'message': 'Not staff'},
            ).status_code
            == 403
        )

        created = client.post(
            '/api/v1/staff/feedback',
            headers=_headers('staff', 'feedback-create'),
            json={'message': '  Please keep the queue filters visible.  '},
        )
        assert created.status_code == 201, created.text
        receipt = created.json()
        assert receipt['feedback_id'].startswith('fdb_')

        replay = client.post(
            '/api/v1/staff/feedback',
            headers=_headers('staff', 'feedback-create'),
            json={'message': '  Please keep the queue filters visible.  '},
        )
        assert replay.status_code == 201
        assert replay.json() == receipt

        conflict = client.post(
            '/api/v1/staff/feedback',
            headers=_headers('staff', 'feedback-create'),
            json={'message': 'A different request'},
        )
        assert conflict.status_code == 409
        assert conflict.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'

        assert (
            client.get('/internal/v1/admin/feedback', headers=_headers('staff')).status_code == 403
        )
        listed = client.get(
            '/internal/v1/admin/feedback?staff_id=stf_demo',
            headers=_headers('admin'),
        )
        assert listed.status_code == 200
        assert listed.json()['page'] == {'next_cursor': None}
        assert listed.json()['items'] == [
            {
                'feedback_id': receipt['feedback_id'],
                'message': 'Please keep the queue filters visible.',
                'submitted_by_staff_id': 'stf_demo',
                'submitted_by_display_name': 'Demo Claims Professional',
                'source': 'workbench',
                'created_at': receipt['created_at'],
            }
        ]
        detail = client.get(
            f'/internal/v1/admin/feedback/{receipt["feedback_id"]}',
            headers=_headers('admin'),
        )
        assert detail.status_code == 200
        assert detail.json() == listed.json()['items'][0]


def test_feedback_rejects_missing_keys_invalid_messages_and_unknown_records() -> None:
    with _client() as client:
        missing_key = client.post(
            '/api/v1/staff/feedback',
            headers=_headers('staff'),
            json={'message': 'A valid message'},
        )
        assert missing_key.status_code == 400
        assert missing_key.json()['error']['code'] == 'VALIDATION_ERROR'

        for message in ('   ', 'x' * 2001):
            invalid = client.post(
                '/api/v1/staff/feedback',
                headers=_headers('staff', f'invalid-{len(message)}'),
                json={'message': message},
            )
            assert invalid.status_code == 422

        missing = client.get(
            '/internal/v1/admin/feedback/fdb_missing',
            headers=_headers('admin'),
        )
        assert missing.status_code == 404
        assert missing.json()['error']['code'] == 'FEEDBACK_NOT_FOUND'


def test_feedback_repository_paginates_and_filters_through_the_admin_api() -> None:
    repository = FeedbackRepository()
    with _client(repository) as client:
        for index in range(101):
            response = client.post(
                '/api/v1/staff/feedback',
                headers=_headers('staff', f'feedback-{index}'),
                json={'message': f'Feedback {index}'},
            )
            assert response.status_code == 201

        first = client.get('/internal/v1/admin/feedback?limit=100', headers=_headers('admin'))
        assert first.status_code == 200
        assert len(first.json()['items']) == 100
        cursor = first.json()['page']['next_cursor']
        assert cursor
        second = client.get(
            f'/internal/v1/admin/feedback?limit=100&cursor={cursor}',
            headers=_headers('admin'),
        )
        assert second.status_code == 200
        assert len(second.json()['items']) == 1
        assert second.json()['page']['next_cursor'] is None


def test_sqlite_feedback_reads_use_parameterized_queries_without_file_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = FeedbackRecord(
        feedback_id='fdb_mocked',
        message='Read through the durable adapter.',
        submitted_by_staff_id='stf_demo',
        submitted_by_display_name='Demo Claims Professional',
        created_at=datetime.now(UTC),
    )
    row = {'payload': record.model_dump_json()}
    connection = MagicMock()
    connection.__enter__.return_value = connection

    def execute(query: str, parameters: tuple[object, ...] = ()) -> MagicMock:
        cursor = MagicMock()
        if 'WHERE feedback_id = ?' in query:
            cursor.fetchone.return_value = row
        else:
            cursor.fetchall.return_value = [row]
        return cursor

    connection.execute.side_effect = execute
    make_directories = MagicMock()
    monkeypatch.setattr('backend.repositories.feedback.os.makedirs', make_directories)
    monkeypatch.setattr(
        'backend.repositories.feedback.sqlite3.connect',
        lambda _path: connection,
    )

    database_path = Path.cwd() / 'virtual' / 'control-plane.sqlite3'
    repository = SQLiteFeedbackRepository(str(database_path))

    assert repository.get(record.feedback_id) == record
    assert repository.list(staff_id='stf_demo', limit=500, offset=-1) == [record]
    make_directories.assert_called_once_with(str(database_path.parent), exist_ok=True)
    connection.executescript.assert_called_once()
    query, parameters = connection.execute.call_args_list[-1].args
    assert 'submitted_by_staff_id' in query
    assert parameters == ('stf_demo', 101, 0)


@pytest.mark.integration
def test_sqlite_feedback_repository_survives_reopen_and_replays(tmp_path: Path) -> None:
    path = tmp_path / 'control-plane.sqlite3'
    repository = SQLiteFeedbackRepository(str(path))
    record = FeedbackRecord.model_validate(
        {
            'feedback_id': 'fdb_persisted',
            'message': 'Persist this feedback.',
            'submitted_by_staff_id': 'stf_demo',
            'submitted_by_display_name': 'Demo Claims Professional',
            'source': 'workbench',
            'created_at': datetime.now(UTC),
        }
    )
    assert (
        repository.submit(
            record,
            actor='stf_demo',
            key='persisted-key',
            fingerprint='same',
        )
        == record
    )

    reopened = SQLiteFeedbackRepository(str(path))
    assert reopened.get(record.feedback_id) == record
    assert reopened.list(staff_id='stf_demo') == [record]
    assert (
        reopened.submit(
            record.model_copy(update={'feedback_id': 'fdb_unused'}),
            actor='stf_demo',
            key='persisted-key',
            fingerprint='same',
        )
        == record
    )
    with pytest.raises(FeedbackIdempotencyConflict):
        reopened.submit(
            record.model_copy(update={'feedback_id': 'fdb_conflict'}),
            actor='stf_demo',
            key='persisted-key',
            fingerprint='different',
        )


def _assert_feedback_idempotency_coordinate_expires(repository: FeedbackRepository) -> None:
    expired = FeedbackRecord(
        feedback_id='fdb_expired',
        message='Old request.',
        submitted_by_staff_id='stf_demo',
        submitted_by_display_name='Demo Claims Professional',
        created_at=datetime.now(UTC) - timedelta(hours=25),
    )
    repository.submit(expired, actor='stf_demo', key='reusable-key', fingerprint='old')

    replacement = expired.model_copy(
        update={
            'feedback_id': 'fdb_replacement',
            'message': 'New request.',
            'created_at': datetime.now(UTC),
        }
    )
    assert (
        repository.submit(
            replacement,
            actor='stf_demo',
            key='reusable-key',
            fingerprint='new',
        )
        == replacement
    )


def test_feedback_idempotency_coordinates_expire_after_24_hours() -> None:
    _assert_feedback_idempotency_coordinate_expires(FeedbackRepository())


@pytest.mark.integration
def test_sqlite_feedback_idempotency_coordinates_expire_after_24_hours(
    tmp_path: Path,
) -> None:
    _assert_feedback_idempotency_coordinate_expires(
        SQLiteFeedbackRepository(str(tmp_path / 'expiry.sqlite3'))
    )
