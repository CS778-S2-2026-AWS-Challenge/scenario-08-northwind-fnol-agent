from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import Settings
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import AgentTurnProvider, ControlledAgent


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
    return create_app(Settings(), repository, agent_turn_provider)


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
