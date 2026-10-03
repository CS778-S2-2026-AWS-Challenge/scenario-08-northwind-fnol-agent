import re
from pathlib import Path

from scripts.ci_plan import plan

CONTINUE = Path('.circleci/continue_config.yml').read_text(encoding='utf-8')
SETUP = Path('.circleci/config.yml').read_text(encoding='utf-8')


def _job(name: str) -> str:
    match = re.search(rf'^  {re.escape(name)}:\n(.*?)(?=^  \S|^\S)', CONTINUE, re.M | re.S)
    assert match is not None, name
    return match.group(1)


def test_setup_config_plans_before_continuing() -> None:
    assert re.search(r'^setup: true$', SETUP, re.M)
    assert 'python -m scripts.ci_plan' in SETUP
    assert 'continuation/continue:' in SETUP
    assert 'configuration_path: .circleci/continue_config.yml' in SETUP


def test_every_planned_parameter_is_declared_by_the_continuation() -> None:
    parameters = CONTINUE.split('\nexecutors:', 1)[0]

    for name in plan([], branch='main', scheduled=False):
        assert re.search(rf'^  {re.escape(name)}:\n    type: boolean$', parameters, re.M), name


def test_pull_requests_and_full_runs_both_check_changed_line_coverage() -> None:
    check = 'check_diff_coverage.py --coverage coverage.json --base origin/main --min 85'

    assert check in _job('backend-quality')
    assert check in _job('backend-full-report')


def test_full_suite_runs_in_parallel_with_test_contexts_and_stored_results() -> None:
    job = _job('backend-full-tests')

    assert re.search(r'parallelism: [2-9]', job)
    assert '--cov-context=test' in job
    assert 'split-by=timings' in job
    assert 'store_test_results' in job
    assert 'report_full_suite_failure.py' in job


def test_full_report_refreshes_the_map_that_pull_requests_restore() -> None:
    assert 'scripts.backend_test_map' in _job('backend-full-report')
    assert 'v2-backend-test-map-{{ .Branch }}-{{ .Revision }}' in _job('backend-full-report')
    assert 'v2-backend-test-map-main-' in _job('backend-quality')
