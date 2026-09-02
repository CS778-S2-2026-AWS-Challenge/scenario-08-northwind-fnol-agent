from collections.abc import Iterator
from functools import partial

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import DataRuntimeProfile, IdentityMode, Settings
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import AgentTurnProvider, ControlledAgent


@pytest.fixture(autouse=True)
def explicit_direct_app_developer_identity(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep direct-app synthetic test suites explicit about developer identity mode.

    The data runtime profile is pinned for every test rather than inherited from the
    developer's shell. `Settings` reads `DATA_RUNTIME_PROFILE` from the environment,
    and the suites that build an app with injected dependencies are fixture-profile
    suites by construction: `backend/app.py` refuses individual data dependency
    injection under any other profile. Without this pin the same commit passes or
    fails depending on who runs it, which is not a property a regression suite may
    have. A test that needs another profile sets it in its own body, which runs
    after this fixture and therefore still wins.
    """

    monkeypatch.setenv('DATA_RUNTIME_PROFILE', DataRuntimeProfile.FIXTURE.value)
    filename = request.node.nodeid.split('::', 1)[0].rsplit('/', 1)[-1]
    if filename in {'test_integrations.py', 'test_claimant_external_service.py'}:
        monkeypatch.setenv('NORTHWIND_ENVIRONMENT', 'test')
        monkeypatch.setenv('NORTHWIND_IDENTITY_MODE', 'developer')
    if filename == 'test_model_gateway.py' and request.module is not None:
        monkeypatch.setattr(
            request.module,
            'Settings',
            partial(Settings, environment='test', identity_mode=IdentityMode.DEVELOPER),
        )


@pytest.fixture
def repository() -> FixtureRepository:
    return FixtureRepository()


@pytest.fixture
def agent_turn_provider() -> AgentTurnProvider:
    return ControlledAgent()


@pytest.fixture
def app(
    repository: FixtureRepository,
    agent_turn_provider: AgentTurnProvider,
) -> FastAPI:
    return create_app(
        Settings(environment='test', identity_mode=IdentityMode.DEVELOPER),
        repository,
        agent_turn_provider,
    )


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {'Authorization': 'Bearer synthetic-claimant'}


@pytest.fixture
def staff_auth_headers() -> dict[str, str]:
    return {'Authorization': 'Bearer synthetic-staff'}
