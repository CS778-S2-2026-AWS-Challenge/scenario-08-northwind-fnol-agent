"""Build and read the map from backend source lines to the test files that execute them.

The full backend suite on ``main`` runs with ``--cov-context=test``. This script turns the
combined coverage data into a compact JSON map that pull requests read to select the test
files covering the lines they change.

Map format (gzip-compressed JSON)::

    {
      "schema": 1,
      "commit": "<sha the full suite ran on>",
      "tests": ["tests/test_a.py", ...],
      "files": {
        "backend/x.py": {
          "statements": [1, 2, 5, ...],
          "all": [0, 3],
          "lines": {"12": [0], "13": [0, 3]}
        }
      }
    }

``statements`` lists executable lines. ``lines`` maps an executed line to indexes into
``tests``; a line executed only while modules were imported has no entry, because no test
context was active. ``all`` is the union of the file's line entries.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

SCHEMA = 1


@dataclass(frozen=True)
class FileCoverage:
    """Test coverage recorded for one backend source file."""

    statements: frozenset[int]
    all_tests: frozenset[str]
    tests_by_line: dict[int, frozenset[str]]


@dataclass(frozen=True)
class CoverageMap:
    """Coverage map read from a full-suite run."""

    commit: str
    files: dict[str, FileCoverage]


def context_test_file(context: str) -> str | None:
    """Return the test file of a pytest-cov dynamic context such as ``tests/a.py::t|run``."""

    if not context:
        return None
    node = context.split('|', 1)[0]
    path = node.split('::', 1)[0].replace('\\', '/')
    return path if path.endswith('.py') else None


def build_map(
    commit: str,
    root: Path,
    coverage_data: object,
    statements_for: dict[str, Iterable[int]],
) -> dict[str, object]:
    """Build the serialisable map from a coverage.py ``CoverageData``.

    Args:
        commit: Commit the full suite ran on.
        root: Repository root used to make measured paths relative.
        coverage_data: A loaded ``coverage.CoverageData`` with test contexts.
        statements_for: Executable lines for each relative backend path.
    """

    tests: list[str] = []
    index: dict[str, int] = {}
    files: dict[str, object] = {}
    for measured in sorted(coverage_data.measured_files()):  # type: ignore[attr-defined]
        relative = _relative(measured, root)
        if relative is None:
            continue
        lines: dict[str, list[int]] = {}
        everything: set[int] = set()
        contexts = coverage_data.contexts_by_lineno(measured)  # type: ignore[attr-defined]
        for line, line_contexts in sorted(contexts.items()):
            ids: set[int] = set()
            for context in line_contexts:
                test_file = context_test_file(context)
                if test_file is None:
                    continue
                if test_file not in index:
                    index[test_file] = len(tests)
                    tests.append(test_file)
                ids.add(index[test_file])
            if ids:
                lines[str(line)] = sorted(ids)
                everything.update(ids)
        files[relative] = {
            'statements': sorted(set(statements_for.get(relative, ()))),
            'all': sorted(everything),
            'lines': lines,
        }
    return {'schema': SCHEMA, 'commit': commit, 'tests': tests, 'files': files}


def write_map(payload: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, 'wt', encoding='utf-8') as handle:
        json.dump(payload, handle, separators=(',', ':'))


def load_map(path: Path) -> CoverageMap | None:
    """Read a map, or return ``None`` when it is missing, unreadable, or another schema."""

    try:
        with gzip.open(path, 'rt', encoding='utf-8') as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get('schema') != SCHEMA:
        return None
    tests = payload['tests']
    files: dict[str, FileCoverage] = {}
    for relative, entry in payload['files'].items():
        files[relative] = FileCoverage(
            statements=frozenset(entry['statements']),
            all_tests=frozenset(tests[i] for i in entry['all']),
            tests_by_line={
                int(line): frozenset(tests[i] for i in ids) for line, ids in entry['lines'].items()
            },
        )
    return CoverageMap(commit=str(payload['commit']), files=files)


def _relative(measured: str, root: Path) -> str | None:
    try:
        relative = Path(measured).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None
    return relative if relative.startswith('backend/') else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', default='.coverage', help='combined coverage data file')
    parser.add_argument('--commit', required=True, help='commit the full suite ran on')
    parser.add_argument('--out', required=True, help='gzip JSON output path')
    args = parser.parse_args()

    import coverage

    root = Path.cwd()
    cov = coverage.Coverage(data_file=args.data)
    cov.load()
    data = cov.get_data()
    statements: dict[str, Iterable[int]] = {}
    for measured in data.measured_files():
        relative = _relative(measured, root)
        if relative is not None:
            statements[relative] = cov.analysis2(measured)[1]
    payload = build_map(args.commit, root, data, statements)
    write_map(payload, Path(args.out))
    files = payload['files']
    assert isinstance(files, dict)
    print(f'Wrote {args.out}: {len(files)} backend files, {len(payload["tests"])} test files.')  # type: ignore[arg-type]
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
