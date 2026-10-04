from scripts.ci_plan import AREAS, plan


def _enabled(parameters: dict[str, bool]) -> set[str]:
    return {name for name, value in parameters.items() if value and name != 'scheduled'}


def test_docs_only_pull_request_creates_only_the_docs_job() -> None:
    assert _enabled(plan(['docs/api.md'], branch='feature/x', scheduled=False)) == {'run-docs'}


def test_claimant_change_creates_customer_and_browser_jobs_but_no_backend_job() -> None:
    enabled = _enabled(plan(['customer/src/App.jsx'], branch='feature/x', scheduled=False))

    assert enabled == {'run-customer', 'run-browser-evidence'}


def test_backend_service_change_creates_backend_and_browser_jobs() -> None:
    enabled = _enabled(plan(['backend/services/claims.py'], branch='fix/x', scheduled=False))

    assert enabled == {'run-backend', 'run-browser-evidence'}


def test_policy_validator_change_runs_the_worker_checks() -> None:
    enabled = _enabled(plan(['.github/scripts/pr_policy.cjs'], branch='fix/x', scheduled=False))

    assert enabled == {'run-automation'}


def test_shared_frontend_tokens_run_every_frontend() -> None:
    enabled = _enabled(plan(['frontend/shared/design-tokens.css'], branch='fix/x', scheduled=False))

    assert enabled == {'run-customer', 'run-workbench', 'run-admin'}


def test_main_runs_every_job_and_the_full_backend_suite() -> None:
    assert _enabled(plan([], branch='main', scheduled=False)) == {*AREAS, 'backend-full'}


def test_schedule_runs_only_the_full_backend_suite() -> None:
    assert _enabled(plan([], branch='main', scheduled=True)) == {'run-backend', 'backend-full'}


def test_ci_definition_change_runs_everything() -> None:
    enabled = _enabled(plan(['.circleci/continue_config.yml'], branch='ci/x', scheduled=False))

    assert enabled == {*AREAS, 'backend-full'}


def test_shared_test_infrastructure_runs_the_parallel_full_suite() -> None:
    enabled = _enabled(plan(['tests/conftest.py'], branch='fix/x', scheduled=False))

    assert enabled == {'run-backend', 'backend-full'}


def test_only_the_schedule_is_marked_scheduled() -> None:
    assert plan([], branch='main', scheduled=True)['scheduled'] is True
    assert plan([], branch='main', scheduled=False)['scheduled'] is False
