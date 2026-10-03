from pathlib import Path
from typing import Any

import pytest

from scripts.backend_test_map import CoverageMap, FileCoverage, build_map, context_test_file
from scripts.select_backend_tests import (
    BackendSelection,
    ImportGraph,
    changed_python_files,
    needs_audit_contract_check,
    needs_openapi_check,
    parse_hunks,
    select_tests,
)

CLAIMS = 'backend/services/claims.py'
CLAIM_API = 'tests/test_claim_api.py'
EVIDENCE_API = 'tests/test_evidence_api.py'
REPOSITORY = 'tests/test_repository.py'


def _map(commit: str = 'abc') -> CoverageMap:
    return CoverageMap(
        commit=commit,
        files={
            CLAIMS: FileCoverage(
                # 1 is a def line run at import; 2-3 run inside tests; 4 is a comment.
                statements=frozenset({1, 2, 3, 10}),
                all_tests=frozenset({CLAIM_API, EVIDENCE_API, REPOSITORY}),
                tests_by_line={2: frozenset({CLAIM_API}), 3: frozenset({EVIDENCE_API})},
            ),
        },
    )


def _select(
    changed: list[str],
    hunks: dict[str, list[tuple[int, int]]] | None = None,
    *,
    test_map: CoverageMap | None | str = 'default',
    **kwargs: Any,
) -> BackendSelection:
    chosen = _map() if test_map == 'default' else test_map
    assert not isinstance(chosen, str)
    return select_tests(changed, hunks=hunks or {}, test_map=chosen, **kwargs)


def test_docs_and_frontend_changes_skip_backend_pytest() -> None:
    selection = _select(['docs/README.md', 'customer/src/App.jsx'])

    assert selection.mode == 'skip'
    assert selection.tests == ()


def test_changed_lines_select_only_the_test_files_that_executed_them() -> None:
    selection = _select([CLAIMS], {CLAIMS: [(2, 1)]})

    assert selection.mode == 'scoped'
    assert selection.tests == (CLAIM_API,)


def test_comment_only_change_selects_no_tests() -> None:
    assert _select([CLAIMS], {CLAIMS: [(4, 1)]}).tests == ()


def test_import_time_line_selects_every_test_covering_the_file() -> None:
    selection = _select([CLAIMS], {CLAIMS: [(1, 1)]})

    assert set(selection.tests) == {CLAIM_API, EVIDENCE_API, REPOSITORY}


def test_insertion_uses_the_neighbouring_lines() -> None:
    # `-2,0` inserts after line 2, between lines covered by two different test files.
    assert set(_select([CLAIMS], {CLAIMS: [(2, 0)]}).tests) == {CLAIM_API, EVIDENCE_API}


def test_file_changed_since_the_map_commit_selects_every_test_covering_it() -> None:
    selection = _select([CLAIMS], {CLAIMS: [(2, 1)]}, stale_paths=[CLAIMS])

    assert set(selection.tests) == {CLAIM_API, EVIDENCE_API, REPOSITORY}


def test_new_backend_module_selects_tests_that_import_it_or_its_importers() -> None:
    graph = ImportGraph(
        {
            'backend.services.claims': frozenset({'backend.services.new_rule'}),
            'tests.test_config': frozenset({'backend.services.new_rule'}),
        }
    )

    selection = _select(['backend/services/new_rule.py'], graph=graph)

    assert set(selection.tests) == {'tests/test_config.py', CLAIM_API, EVIDENCE_API, REPOSITORY}


def test_changed_test_file_is_selected_and_support_module_selects_its_importers() -> None:
    graph = ImportGraph(
        {
            'tests.journey_runs.engine': frozenset(),
            'tests.journey_runs.motor_collision': frozenset({'tests.journey_runs.engine'}),
            'tests.test_journey_runs': frozenset({'tests.journey_runs.motor_collision'}),
        }
    )

    assert _select([REPOSITORY]).tests == (REPOSITORY,)
    assert _select(['tests/journey_runs/engine.py'], graph=graph).tests == (
        'tests/test_journey_runs.py',
    )


@pytest.mark.parametrize(
    'path',
    ['tests/conftest.py', 'pyproject.toml', 'backend/requirements-dev.txt', '.circleci/config.yml'],
)
def test_shared_test_infrastructure_runs_the_full_suite(path: str) -> None:
    assert _select([path]).mode == 'full'


def test_backend_change_without_a_map_runs_the_full_suite() -> None:
    assert _select([CLAIMS], test_map=None).mode == 'full'


def test_forced_full_run_ignores_the_change() -> None:
    assert _select(['docs/README.md'], force_full=True).mode == 'full'


def test_parse_hunks_reads_merge_base_ranges() -> None:
    diff = '\n'.join(
        [
            'diff --git a/backend/x.py b/backend/x.py',
            '--- a/backend/x.py',
            '+++ b/backend/x.py',
            '@@ -12,3 +12,4 @@ def f():',
            '@@ -40 +41 @@',
            '@@ -50,0 +52,2 @@',
            'diff --git a/backend/new.py b/backend/new.py',
            '--- /dev/null',
            '+++ b/backend/new.py',
            '@@ -0,0 +1,3 @@',
        ]
    )

    assert parse_hunks(diff) == {'backend/x.py': [(12, 3), (40, 1), (50, 0)]}


def test_map_build_attributes_lines_to_test_files() -> None:
    class Data:
        def measured_files(self) -> list[str]:
            return [str(Path('backend/x.py').resolve()), str(Path('scripts/y.py').resolve())]

        def contexts_by_lineno(self, _path: str) -> dict[int, list[str]]:
            return {
                1: [''],
                2: ['tests/test_a.py::test_one|run', 'tests/test_b.py::test_two|setup'],
            }

    payload = build_map('abc', Path.cwd(), Data(), {'backend/x.py': [1, 2, 3]})

    assert payload['tests'] == ['tests/test_a.py', 'tests/test_b.py']
    assert payload['files'] == {
        'backend/x.py': {'statements': [1, 2, 3], 'all': [0, 1], 'lines': {'2': [0, 1]}}
    }
    assert context_test_file('') is None


def test_static_check_helpers() -> None:
    assert changed_python_files(['scripts/select_backend_tests.py', 'gone.py']) == (
        'scripts/select_backend_tests.py',
    )
    assert needs_openapi_check(['backend/api/claims.py'])
    assert not needs_openapi_check(['backend/services/claims.py'])
    assert needs_audit_contract_check(['docs/contracts/audit-event.schema.json'])
