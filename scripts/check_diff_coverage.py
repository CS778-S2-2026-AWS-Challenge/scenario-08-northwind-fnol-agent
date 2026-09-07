"""Check executable backend lines changed by a PR against a coverage.py JSON report."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def changed_backend_lines(diff_text: str) -> dict[str, set[int]]:
    """Return added executable candidates grouped by backend source path."""

    changed: dict[str, set[int]] = {}
    current_path: str | None = None
    current_line: int | None = None
    for raw_line in diff_text.splitlines():
        if raw_line.startswith('+++ b/'):
            path = raw_line[6:].replace('\\', '/')
            current_path = path if path.startswith('backend/') and path.endswith('.py') else None
            current_line = None
            continue
        if raw_line.startswith('@@ '):
            try:
                new_range = raw_line.split('+', 1)[1].split(' ', 1)[0]
                if ',' in new_range:
                    start, length = new_range.split(',', 1)
                else:
                    start, length = new_range, '1'
                current_line = int(start)
                if length == '0':
                    current_line = None
            except (IndexError, ValueError):
                current_line = None
            continue
        if current_path is None or current_line is None:
            continue
        if raw_line.startswith('+') and not raw_line.startswith('+++'):
            changed.setdefault(current_path, set()).add(current_line)
            current_line += 1
        elif raw_line.startswith('-') and not raw_line.startswith('---'):
            continue
        else:
            current_line += 1
    return changed


def diff_coverage(
    coverage: dict[str, Any], changed: dict[str, set[int]]
) -> tuple[int, int, dict[str, list[int]]]:
    """Return covered/executable counts and uncovered changed lines."""

    covered = 0
    executable = 0
    missing_by_file: dict[str, list[int]] = {}
    files = coverage.get('files', {})
    for path, lines in changed.items():
        report = files.get(path) or files.get(path.replace('\\', '/'))
        if not isinstance(report, dict):
            continue
        executed = set(report.get('executed_lines', []))
        missing = set(report.get('missing_lines', []))
        for line in sorted(lines & (executed | missing)):
            executable += 1
            if line in executed:
                covered += 1
            else:
                missing_by_file.setdefault(path, []).append(line)
    return covered, executable, missing_by_file


def _git_diff(base: str) -> str:
    result = subprocess.run(
        ['git', 'diff', '--unified=0', '--no-color', f'{base}...HEAD', '--', 'backend'],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--coverage', default='coverage.json', type=Path)
    parser.add_argument('--base', default='origin/main')
    parser.add_argument('--min', dest='minimum', default=85.0, type=float)
    args = parser.parse_args(argv)

    coverage = json.loads(args.coverage.read_text(encoding='utf-8'))
    changed = changed_backend_lines(_git_diff(args.base))
    covered, executable, missing = diff_coverage(coverage, changed)
    if executable == 0:
        print('Diff coverage: no changed executable backend lines; check skipped.')
        return 0
    percentage = covered / executable * 100
    print(f'Diff coverage: {covered}/{executable} executable backend lines ({percentage:.2f}%).')
    if missing:
        details = ', '.join(f'{path}:{lines}' for path, lines in sorted(missing.items()))
        print(f'Uncovered changed lines: {details}')
    if percentage < args.minimum:
        print(f'Diff coverage {percentage:.2f}% is below the required {args.minimum:.2f}%.')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
