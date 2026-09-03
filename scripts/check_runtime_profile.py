import argparse
import json
import os
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.config import Settings
from backend.core.runtime_profiles import (
    RuntimeProfileConfigurationError,
    build_data_runtime_bundle,
    runtime_capability_statuses,
)

_SETTING_NAME = re.compile(r'[A-Z][A-Z0-9_]*\Z')
_MANAGED_PREFIXES = ('NORTHWIND_', 'MODEL_', 'AWS_', 'CLOUDFLARE_')
_MANAGED_NAMES = {'DATA_RUNTIME_PROFILE', 'AGENT_RUNTIME_PROFILE'}
_READY_CAPABILITY_STATES = {'using_fixture', 'configured_service', 'verified'}


def load_environment_example(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError('Runtime environment example cannot be read.') from error
    for position, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            raise ValueError(f'Runtime environment line {position} must use NAME=value.')
        name, value = line.split('=', 1)
        if not _SETTING_NAME.fullmatch(name) or name in values:
            raise ValueError(f'Runtime environment line {position} has an invalid setting name.')
        values[name] = value
    if 'DATA_RUNTIME_PROFILE' not in values:
        raise ValueError('Runtime environment example must select DATA_RUNTIME_PROFILE.')
    return values


def _is_managed(name: str) -> bool:
    return name in _MANAGED_NAMES or name.startswith(_MANAGED_PREFIXES)


@contextmanager
def isolated_environment(values: dict[str, str]) -> Iterator[None]:
    original = {
        name: value for name, value in os.environ.items() if _is_managed(name) or name in values
    }
    for name in tuple(os.environ):
        if _is_managed(name) or name in values:
            del os.environ[name]
    os.environ.update(values)
    try:
        yield
    finally:
        for name in tuple(os.environ):
            if _is_managed(name) or name in values:
                del os.environ[name]
        os.environ.update(original)


def inspect_environment(values: dict[str, str]) -> tuple[dict[str, object], int]:
    """Inspect already parsed runtime settings without inheriting managed host values."""

    with isolated_environment(values):
        settings = Settings.from_environment()
        result: dict[str, object] = {
            'profile': settings.data_runtime_profile.value,
            'object_storage_adapter': settings.object_storage_adapter.value,
            'capabilities': runtime_capability_statuses(settings.data_runtime_profile),
        }
        try:
            bundle = build_data_runtime_bundle(settings)
        except (RuntimeProfileConfigurationError, ValueError) as error:
            readiness = getattr(error, 'readiness', None)
            if isinstance(readiness, dict):
                result['readiness'] = readiness
            result.update(status='startup_refused', reason=str(error))
            return result, 2
        try:
            readiness = bundle.readiness_checks()
            result['readiness'] = readiness
            refused = {
                capability: status
                for capability, status in readiness.items()
                if status not in _READY_CAPABILITY_STATES
            }
            if refused:
                details = ', '.join(
                    f'{capability}={status}' for capability, status in sorted(refused.items())
                )
                result.update(
                    status='startup_refused',
                    reason=f'Runtime readiness check failed: {details}. Startup refused.',
                )
                return result, 2
            result['status'] = 'startup_ready'
            return result, 0
        finally:
            bundle.close()


def inspect_runtime(path: Path) -> tuple[dict[str, object], int]:
    return inspect_environment(load_environment_example(path))


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Check one Northwind runtime environment before serving requests.'
    )
    parser.add_argument('environment', type=Path)
    parser.add_argument(
        '--expect', choices=('ready', 'refused'), help='Make an expected result exit successfully.'
    )
    arguments = parser.parse_args()
    try:
        result, exit_code = inspect_runtime(arguments.environment)
    except ValueError as error:
        result, exit_code = {'status': 'invalid_environment', 'reason': str(error)}, 2
    print(json.dumps(result, indent=2, sort_keys=True))
    expected_status = {
        'ready': 'startup_ready',
        'refused': 'startup_refused',
    }.get(arguments.expect)
    if expected_status is not None:
        raise SystemExit(0 if result['status'] == expected_status else 1)
    raise SystemExit(exit_code)


if __name__ == '__main__':
    main()
