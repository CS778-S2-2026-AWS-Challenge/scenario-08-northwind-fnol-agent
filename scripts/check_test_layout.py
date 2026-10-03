"""Print advice about test files added by a pull request. Never fails the build.

Test files are named after the module or behaviour they test. A new file named after a
PR, issue, week, day, sprint, or prompt version, or one that extends the name of an existing
test file, usually belongs in an existing file instead.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable, Sequence
from pathlib import PurePosixPath

PROCESS_NAME = re.compile(r'(^|_)(pr?\d+|issue_?\d+|week\d+|day\d+|sprint\d+|v\d+)(_|$)')


def advice(added: Sequence[str], existing: Iterable[str]) -> list[str]:
    """Return one line of advice per questionable new test file."""

    stems = {PurePosixPath(path).stem for path in existing}
    messages: list[str] = []
    for path in sorted(added):
        name = PurePosixPath(path)
        if not (path.startswith('tests/') and name.name.startswith('test_')):
            continue
        stem = name.stem
        if PROCESS_NAME.search(stem.removeprefix('test_')):
            messages.append(
                f'{path}: name the file after the module or behaviour it tests, '
                'not a PR, issue, week, or version.'
            )
        parents = sorted(s for s in stems if s != stem and stem.startswith(f'{s}_'))
        if parents:
            messages.append(
                f'{path}: extends tests/{parents[-1]}.py; add these cases there unless they '
                'test a different module.'
            )
    return messages


def _git_lines(*args: str) -> list[str]:
    output = subprocess.run(['git', *args], check=True, capture_output=True, text=True).stdout
    return [line for line in output.splitlines() if line]


def main() -> int:
    base = _git_lines('merge-base', 'origin/main', 'HEAD')[0]
    added = _git_lines('diff', '--name-only', '--diff-filter=A', base, 'HEAD', '--', 'tests')
    existing = _git_lines('ls-tree', '-r', '--name-only', base, '--', 'tests')
    messages = advice(added, existing)
    for message in messages:
        print(f'ADVICE {message}')
    if not messages:
        print('No test-layout advice.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
