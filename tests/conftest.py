from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import AgentTurnProvider, ControlledAgent


@pytest.fixture(autouse=True)
def explicit_direct_app_developer_identity(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep legacy direct-app test suites explicit about synthetic identity mode."""
    filename = request.node.nodeid.split('::', 1)[0].rsplit('/', 1)[-1]
    if filename in {'test_integrations.py', 'test_claimant_external_service.py'}:
        monkeypatch.setenv('NORTHWIND_ENVIRONMENT', 'test')
        monkeypatch.setenv('NORTHWIND_IDENTITY_MODE', 'developer')


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
