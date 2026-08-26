from typing import Any

import pytest

from backend.repositories.mongodb import MongoDBConfigurationError
from scripts.validate_runtime_profiles import build_validation_report


def _startup(status: str) -> dict[str, object]:
    return {'status': status}


def test_report_classifies_verified_partial_and_unavailable_profiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = {
        'fixture.env.example': _startup('startup_ready'),
        'mongodb.env.example': _startup('startup_refused'),
        'cloudflare.env.example': _startup('startup_refused'),
        'aws.env.example': _startup('startup_refused'),
    }
    monkeypatch.setattr(
        'scripts.validate_runtime_profiles._runtime_result', lambda filename: results[filename]
    )
    monkeypatch.setattr(
        'scripts.validate_runtime_profiles._local_minio_result',
        lambda _endpoint: _startup('startup_ready'),
    )

    report, expected = build_validation_report(minio_endpoint='http://localhost:9000')

    profiles = report['profiles']
    assert isinstance(profiles, dict)
    assert profiles['fixture']['classification'] == 'verified'
    assert profiles['local_minio']['classification'] == 'verified'
    assert profiles['mongodb']['classification'] == 'partial'
    assert profiles['cloudflare']['classification'] == 'unavailable'
    assert profiles['aws']['classification'] == 'unavailable'
    assert report['isolation'] == 'verified_fail_closed'
    assert expected is True


def test_requested_minio_validation_fails_when_service_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        'scripts.validate_runtime_profiles._runtime_result',
        lambda filename: _startup(
            'startup_ready' if filename == 'fixture.env.example' else 'startup_refused'
        ),
    )
    monkeypatch.setattr(
        'scripts.validate_runtime_profiles._local_minio_result',
        lambda _endpoint: _startup('startup_refused'),
    )

    report, expected = build_validation_report(minio_endpoint='http://localhost:9000')

    profiles = report['profiles']
    assert isinstance(profiles, dict)
    assert profiles['local_minio']['classification'] == 'unavailable'
    assert expected is False


def test_report_does_not_claim_isolation_when_a_candidate_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        'scripts.validate_runtime_profiles._runtime_result',
        lambda filename: _startup(
            'startup_ready'
            if filename in {'fixture.env.example', 'aws.env.example'}
            else 'startup_refused'
        ),
    )
    monkeypatch.setattr(
        'scripts.validate_runtime_profiles._local_minio_result',
        lambda _endpoint: _startup('startup_refused'),
    )

    report, expected = build_validation_report()

    assert report['isolation'] == 'failed'
    assert expected is False


def test_mongodb_probe_failure_is_bounded_to_availability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        'scripts.validate_runtime_profiles._runtime_result',
        lambda filename: _startup(
            'startup_ready' if filename == 'fixture.env.example' else 'startup_refused'
        ),
    )
    monkeypatch.setattr(
        'scripts.validate_runtime_profiles._local_minio_result',
        lambda _endpoint: _startup('startup_refused'),
    )

    def fail_connection(_config: object) -> Any:
        raise MongoDBConfigurationError('provider detail must not enter the report')

    monkeypatch.setattr(
        'scripts.validate_runtime_profiles.connect_mongodb_repository', fail_connection
    )

    report, expected = build_validation_report(probe_mongodb=True)

    profiles = report['profiles']
    assert isinstance(profiles, dict)
    assert profiles['mongodb']['connectivity'] == 'unavailable'
    assert 'provider detail' not in str(report)
    assert expected is True
