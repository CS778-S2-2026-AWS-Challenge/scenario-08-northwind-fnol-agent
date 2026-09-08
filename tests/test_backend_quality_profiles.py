from pathlib import Path

import pytest


@pytest.mark.parametrize(
    'profile_path',
    [Path('.circleci/config.yml'), Path('.github/workflows/ci.yml')],
)
def test_backend_quality_profiles_separate_total_and_diff_coverage(
    profile_path: Path,
) -> None:
    lines = profile_path.read_text(encoding='utf-8').splitlines()
    pytest_commands = [
        line.strip() for line in lines if line.strip().startswith('python -m pytest --cov=backend')
    ]
    diff_commands = [
        line.strip()
        for line in lines
        if line.strip().startswith('python scripts/check_diff_coverage.py')
    ]

    assert len(pytest_commands) == 2
    full_command = next(
        command for command in pytest_commands if '--cov-report=term-missing' in command
    )
    scoped_command = next(
        command for command in pytest_commands if '--cov-report=term-missing' not in command
    )

    assert '--cov-report=json:coverage.json' in full_command
    assert '--cov-fail-under=0' not in full_command
    assert '--cov-report=json:coverage.json' in scoped_command
    assert '--cov-fail-under=0' in scoped_command
    assert len(diff_commands) == 2
    assert all('--coverage coverage.json' in command for command in diff_commands)
    assert all('--min 85' in command for command in diff_commands)
