"""Select backend checks from the files and lines changed by a pull request.

Pull requests run the test files that executed their changed backend lines in the latest
full-suite run on ``main`` (see ``scripts/backend_test_map.py``), plus the test files they
change and the test files that import changed test-support or script modules. The whole
suite runs on ``main``, on the daily schedule, when shared test infrastructure changes, and
when no coverage map is available.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

try:
    from scripts.backend_test_map import CoverageMap, load_map
except ModuleNotFoundError:  # run as `python scripts/select_backend_tests.py`
    from backend_test_map import CoverageMap, load_map  # type: ignore[import-not-found,no-redef]

DEFAULT_MAP_PATH = Path('.ci/backend-test-map.json.gz')

# Changing any of these can change the outcome of every test, so the whole suite runs.
FULL_SUITE_PATHS = frozenset(
    {
        'backend/requirements.txt',
        'backend/requirements-dev.txt',
        'pyproject.toml',
        'scripts/backend_test_map.py',
        'scripts/ci_plan.py',
        'scripts/select_backend_tests.py',
        'tests/__init__.py',
        'tests/conftest.py',
    }
)
FULL_SUITE_PREFIXES = ('.circleci/',)
OPENAPI_PATHS = frozenset({'backend/app.py', 'backend/main.py', 'scripts/export_openapi.py'})
AUDIT_CONTRACT_PATHS = frozenset(
    {
        'backend/domain/audit.py',
        'scripts/export_audit_contract.py',
        'docs/contracts/audit-event.schema.json',
    }
)
_HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@')


@dataclass(frozen=True)
class BackendSelection:
    """Selected pytest paths and the reason for the selection."""

    mode: str
    tests: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class ImportGraph:
    """Static imports among repository Python modules, keyed by module name."""

    imports: Mapping[str, frozenset[str]]

    def importers_of(self, module: str) -> set[str]:
        return {
            name
            for name, imported in self.imports.items()
            if any(item == module or item.startswith(f'{module}.') for item in imported)
        }


def select_tests(
    changed: Sequence[str],
    *,
    hunks: Mapping[str, Sequence[tuple[int, int]]],
    test_map: CoverageMap | None,
    stale_paths: Iterable[str] = (),
    graph: ImportGraph | None = None,
    force_full: bool = False,
) -> BackendSelection:
    """Select backend tests for repository-relative changed paths.

    Args:
        changed: Paths changed relative to the merge base.
        hunks: Merge-base ``(start, length)`` line ranges changed in each backend file.
        test_map: The latest full-suite coverage map, or ``None`` when unavailable.
        stale_paths: Backend files that differ between the map commit and the merge base;
            their line numbers cannot be trusted, so every test covering the file is selected.
        graph: Static import graph used for files the map does not cover.
        force_full: Run the whole suite regardless of the change.
    """

    paths = sorted({_normalise(path) for path in changed})
    if force_full:
        return BackendSelection('full', (), 'main, schedule, or explicit full run')
    for path in paths:
        if path in FULL_SUITE_PATHS or path.startswith(FULL_SUITE_PREFIXES):
            return BackendSelection('full', (), f'shared test infrastructure changed: {path}')

    python = [path for path in paths if path.endswith('.py')]
    backend = [path for path in python if path.startswith('backend/')]
    others = [path for path in python if not path.startswith('backend/')]
    if not backend and not others:
        return BackendSelection('skip', (), 'no backend, test, or script Python changed')
    if backend and test_map is None:
        return BackendSelection('full', (), 'no coverage map from main is available')

    graph = graph or ImportGraph({})
    stale = {_normalise(path) for path in stale_paths}
    selected: set[str] = set()
    for path in others:
        if path.startswith('tests/') and _is_test_module(path):
            if Path(path).is_file():
                selected.add(path)
            continue
        selected.update(_test_importers(_module_name(path), graph))
    for path in backend:
        assert test_map is not None
        selected.update(_tests_for_backend_file(path, hunks.get(path, ()), test_map, stale, graph))

    tests = tuple(sorted(test for test in selected if Path(test).is_file()))
    return BackendSelection('scoped', tests, f'{len(tests)} test files cover the changed lines')


def _tests_for_backend_file(
    path: str,
    ranges: Sequence[tuple[int, int]],
    test_map: CoverageMap,
    stale: set[str],
    graph: ImportGraph,
) -> set[str]:
    coverage = test_map.files.get(path)
    if coverage is None:
        # New or never-executed module: use the tests that import it, directly or through
        # the backend modules that import it.
        module = _module_name(path)
        selected = _test_importers(module, graph)
        for importer in graph.importers_of(module):
            importer_path = _module_path(importer)
            if importer_path in test_map.files:
                selected.update(test_map.files[importer_path].all_tests)
        return selected
    if path in stale or not Path(path).is_file() or not ranges:
        return set(coverage.all_tests)

    selected = set()
    for start, length in ranges:
        lines = range(start, start + length) if length else range(start, start + 2)
        executable = [line for line in lines if line in coverage.statements]
        if not executable:
            continue  # comments, blank lines, or docstrings only
        covering = set().union(
            *(coverage.tests_by_line.get(line, frozenset()) for line in executable)
        )
        # Lines run only at import time (signatures, class bodies, module constants) have
        # no test context; any test using the module may depend on them.
        selected.update(covering or coverage.all_tests)
    return selected


def _test_importers(module: str, graph: ImportGraph) -> set[str]:
    """Return test modules that import ``module`` directly or through test-support modules."""

    found: set[str] = set()
    pending = [module]
    seen = {module}
    while pending:
        for importer in graph.importers_of(pending.pop()):
            if importer in seen:
                continue
            seen.add(importer)
            path = _module_path(importer)
            if path.startswith('tests/') and _is_test_module(path):
                found.add(path)
            elif importer.startswith('tests.'):
                pending.append(importer)
    return found


def build_import_graph(roots: Sequence[str] = ('backend', 'scripts', 'tests')) -> ImportGraph:
    """Parse imports of every Python file under ``roots``."""

    imports: dict[str, frozenset[str]] = {}
    for root in roots:
        for file in Path(root).rglob('*.py'):
            relative = file.as_posix()
            if '/fixtures/' in relative:
                continue
            try:
                tree = ast.parse(file.read_text(encoding='utf-8'))
            except (SyntaxError, UnicodeDecodeError):
                continue
            imports[_module_name(relative)] = frozenset(_imported_names(tree))
    return ImportGraph(imports)


def _imported_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
            names.update(f'{node.module}.{alias.name}' for alias in node.names)
    return names


def _module_name(path: str) -> str:
    module = PurePosixPath(path).with_suffix('').as_posix().replace('/', '.')
    return module.removesuffix('.__init__')


def _module_path(module: str) -> str:
    candidate = module.replace('.', '/')
    return f'{candidate}.py' if Path(f'{candidate}.py').is_file() else f'{candidate}/__init__.py'


def _normalise(path: str) -> str:
    return PurePosixPath(path.replace('\\', '/')).as_posix()


def _is_test_module(path: str) -> bool:
    name = PurePosixPath(path).name
    return name.startswith('test_') or name.endswith('_test.py')


def parse_hunks(diff_text: str) -> dict[str, list[tuple[int, int]]]:
    """Return merge-base line ranges from ``git diff -U0`` output, per backend file."""

    hunks: dict[str, list[tuple[int, int]]] = {}
    current: str | None = None
    for line in diff_text.splitlines():
        if line.startswith('--- '):
            source = line[4:]
            current = source[2:] if source.startswith('a/') else None
        elif current and (match := _HUNK.match(line)):
            start = int(match.group(1))
            length = int(match.group(2)) if match.group(2) is not None else 1
            hunks.setdefault(current, []).append((start, length))
    return hunks


def changed_python_files(changed: Sequence[str]) -> tuple[str, ...]:
    """Return changed Python files that still exist, for scoped static checks.

    Files under docs/archive/ are historical and never imported, so they are not checked.
    """

    paths = {_normalise(item) for item in changed}
    return tuple(
        sorted(
            path
            for path in paths
            if path.endswith('.py')
            and not path.startswith('docs/archive/')
            and Path(path).is_file()
        )
    )


def needs_openapi_check(changed: Sequence[str]) -> bool:
    """Return whether the changed paths can alter the generated OpenAPI schema."""

    paths = {_normalise(path) for path in changed}
    return bool(
        paths & OPENAPI_PATHS
        or any(path.startswith(('backend/api/', 'backend/domain/')) for path in paths)
        or 'docs/openapi.snapshot.json' in paths
    )


def needs_audit_contract_check(changed: Sequence[str]) -> bool:
    """Return whether the AuditEvent contract or its snapshot changed."""

    return bool({_normalise(path) for path in changed} & AUDIT_CONTRACT_PATHS)


def _git(*args: str) -> str:
    return subprocess.run(['git', *args], check=True, capture_output=True, text=True).stdout


def merge_base() -> str:
    return _git('merge-base', 'origin/main', 'HEAD').strip()


def changed_paths(base: str) -> tuple[str, ...]:
    output = _git('diff', '--name-only', '--diff-filter=ACMRD', base, 'HEAD')
    return tuple(line for line in output.splitlines() if line)


def stale_backend_paths(map_commit: str, base: str) -> tuple[str, ...]:
    """Return backend files whose content differs between the map commit and the merge base."""

    try:
        output = _git('diff', '--name-only', map_commit, base, '--', 'backend')
    except subprocess.CalledProcessError:
        return ('backend/',)
    return tuple(line for line in output.splitlines() if line)


def running_full() -> bool:
    """Return whether CI asked for the whole suite (main, schedule, or full workflow)."""

    if os.getenv('BACKEND_FULL_SUITE') == 'true':
        return True
    github_main = (
        os.getenv('GITHUB_REF') == 'refs/heads/main'
        and os.getenv('GITHUB_EVENT_NAME') != 'pull_request'
    )
    circle_main = os.getenv('CIRCLE_BRANCH') == 'main' and not os.getenv('CIRCLE_PULL_REQUEST')
    return github_main or circle_main


def current_selection(map_path: Path) -> tuple[BackendSelection, tuple[str, ...]]:
    base = merge_base()
    paths = changed_paths(base)
    test_map = load_map(map_path)
    stale: tuple[str, ...] = ()
    if test_map is not None:
        stale = stale_backend_paths(test_map.commit, base)
        if stale == ('backend/',):
            stale = tuple(path for path in paths if path.startswith('backend/'))
    selection = select_tests(
        paths,
        hunks=parse_hunks(_git('diff', '-U0', '--diff-filter=MD', base, 'HEAD', '--', 'backend')),
        test_map=test_map,
        stale_paths=stale,
        graph=build_import_graph(),
        force_full=running_full(),
    )
    return selection, paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--map', type=Path, default=DEFAULT_MAP_PATH, help='coverage map path')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--mode', action='store_true', help='print only the selection mode')
    group.add_argument('--tests', action='store_true', help='print selected pytest paths')
    group.add_argument('--python-files', action='store_true', help='print changed Python files')
    group.add_argument('--needs-openapi', action='store_true', help='print OpenAPI check need')
    group.add_argument(
        '--needs-audit-contract', action='store_true', help='print AuditEvent check need'
    )
    args = parser.parse_args()
    selection, paths = current_selection(args.map)
    if args.mode:
        print(selection.mode)
    elif args.tests:
        print('\n'.join(selection.tests))
    elif args.python_files:
        print('\n'.join(changed_python_files(paths)))
    elif args.needs_openapi:
        print(str(needs_openapi_check(paths)).lower())
    elif args.needs_audit_contract:
        print(str(needs_audit_contract_check(paths)).lower())
    else:
        print(f'{selection.mode}: {selection.reason}')
        print('\n'.join(selection.tests))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
