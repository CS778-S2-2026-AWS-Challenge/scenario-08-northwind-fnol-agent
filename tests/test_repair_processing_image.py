"""Operator CLI safety regressions; providers and repair service are mocked."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.core.config import DataRuntimeProfile, Settings
from backend.core.errors import ApiError
from backend.domain.models import EvidenceFileStatus
from backend.services import evidence
from scripts import repair_processing_image as command

ARGS = [
    '--claim-id',
    'clm_test',
    '--evidence-id',
    'evd_test',
    '--revision',
    '3',
    '--material-version',
    '1',
]


@pytest.mark.parametrize('apply', [False, True])
def test_explicit_target_and_dry_run_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], apply: bool
) -> None:
    monkeypatch.setattr(
        Settings,
        'from_environment',
        Mock(return_value=SimpleNamespace(data_runtime_profile=DataRuntimeProfile.LOCAL_MVP)),
    )
    bundle = Mock()
    monkeypatch.setattr(command, 'build_data_runtime_bundle', Mock(return_value=bundle))
    repair = Mock(
        return_value=SimpleNamespace(
            evidence=SimpleNamespace(file_status=EvidenceFileStatus.READY), revision=4
        )
    )
    monkeypatch.setattr(evidence, 'repair_processing_image', repair)

    assert command.main([*ARGS, *(['--apply'] if apply else [])]) == 0

    repair.assert_called_once_with(
        bundle.repository,
        bundle.evidence_storage,
        claim_id='clm_test',
        evidence_id='evd_test',
        expected_revision=3,
        material_version=1,
        apply=apply,
    )
    bundle.close.assert_called_once_with()
    assert json.loads(capsys.readouterr().out) == {
        'mode': 'applied' if apply else 'dry-run',
        'file_status': 'ready',
        'revision': 4,
    }


def test_fixture_refused_before_runtime_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        Settings,
        'from_environment',
        Mock(return_value=SimpleNamespace(data_runtime_profile=DataRuntimeProfile.FIXTURE)),
    )
    build = Mock()
    monkeypatch.setattr(command, 'build_data_runtime_bundle', build)
    assert command.main(ARGS) == 1
    build.assert_not_called()


@pytest.mark.parametrize(
    'error',
    [
        ApiError(
            status_code=409, code='REVISION_CONFLICT', message='private data', current_revision=5
        ),
        RuntimeError('secret provider credential'),
    ],
)
def test_failure_redaction_and_provider_cleanup(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], error: Exception
) -> None:
    monkeypatch.setattr(
        Settings,
        'from_environment',
        Mock(return_value=SimpleNamespace(data_runtime_profile=DataRuntimeProfile.LOCAL_MVP)),
    )
    bundle = Mock()
    monkeypatch.setattr(command, 'build_data_runtime_bundle', Mock(return_value=bundle))
    monkeypatch.setattr(evidence, 'repair_processing_image', Mock(side_effect=error))
    assert command.main(ARGS) == 1
    bundle.close.assert_called_once_with()
    output = capsys.readouterr()
    assert not output.out
    assert str(error) not in output.err
    if isinstance(error, ApiError):
        assert json.loads(output.err)['current_revision'] == 5


@pytest.mark.parametrize('arguments', [[], [*ARGS[:-2]], [*ARGS[:-1], '0']])
def test_missing_target_or_invalid_guard_refused_before_providers(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    build = Mock()
    monkeypatch.setattr(command, 'build_data_runtime_bundle', build)
    with pytest.raises(SystemExit) as error:
        command.main(arguments)
    assert error.value.code == 2
    build.assert_not_called()
