from datetime import UTC, datetime
from time import sleep
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.core.errors import ApiError
from backend.core.runtime_profiles import RuntimeProfileConfigurationError
from backend.domain.configuration import (
    ConfigurationImpact,
    ConfigurationRecord,
    ConfigurationState,
    IntegrationSourceValue,
)
from backend.domain.release import (
    ConfigurationReference,
    ReleaseSetRecord,
    ReleaseSetState,
)
from backend.repositories.configuration import ConfigurationRepository
from backend.repositories.release_set import ReleaseSetRepository
from backend.services.integration_registry import get_integration
from backend.services.runtime_configuration import RuntimeConfigurationResolver
from backend.services.runtime_integrations import RuntimeIntegrationPolicy


def _now() -> datetime:
    return datetime(2026, 9, 7, 10, tzinfo=UTC)


def _configuration(
    service_id: str,
    capability: str,
    *,
    source: IntegrationSourceValue = IntegrationSourceValue.FIXTURE,
    enabled: bool = True,
    timeout: float = 5.0,
) -> ConfigurationRecord:
    return ConfigurationRecord(
        configuration_id=f'cfg_{service_id}',
        domain='integration',
        configuration_key=service_id,
        revision=1,
        state=ConfigurationState.PUBLISHED,
        impact=ConfigurationImpact.NORMAL,
        values={
            'service_id': service_id,
            'capability': capability,
            'source': source.value,
            'enabled': enabled,
            'health_check_timeout_seconds': timeout,
        },
        author='adm_demo',
        reason='Exercise runtime Integration policy.',
        validation_evidence={'result': 'passed'},
        effective_time=_now(),
        updated_at=_now(),
    )


def _policy(
    configuration: ConfigurationRecord | None,
    *,
    actual_source: IntegrationSourceValue = IntegrationSourceValue.FIXTURE,
) -> RuntimeIntegrationPolicy:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    references: dict[str, ConfigurationReference] = {}
    if configuration is not None:
        configurations.create(configuration)
        service_id = str(configuration.values['service_id'])
        references[service_id] = ConfigurationReference(
            configuration_id=configuration.configuration_id,
            revision=configuration.revision,
        )
    releases.create(
        ReleaseSetRecord(
            release_set_id='rel_integrations',
            environment='test',
            runtime_profile='fixture',
            revision=1,
            state=ReleaseSetState.PUBLISHED,
            configuration_refs={},
            integration_refs=references,
            author='adm_demo',
            reason='Exercise runtime Integration policy.',
            effective_time=_now(),
            updated_at=_now(),
        )
    )
    resolver = RuntimeConfigurationResolver(
        configurations,
        releases,
        environment='test',
        runtime_profile='fixture',
    )
    sources = {'assessor_service': actual_source, 'policy': actual_source}
    return RuntimeIntegrationPolicy(resolver, sources)


def test_active_release_rejects_an_unselected_required_integration() -> None:
    policy = _policy(None)

    with pytest.raises(ApiError) as missing:
        policy.require('assessor_service')

    assert missing.value.status_code == 503
    assert missing.value.code == 'RELEASE_SET_INTEGRATION_NOT_SELECTED'


def test_disabled_integration_blocks_the_real_internal_route() -> None:
    configuration = _configuration('policy', 'policy_lookup', enabled=False)
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    configurations.create(configuration)
    releases.create(
        ReleaseSetRecord(
            release_set_id='rel_disabled_policy',
            environment='test',
            runtime_profile='fixture',
            revision=1,
            state=ReleaseSetState.PUBLISHED,
            configuration_refs={},
            integration_refs={
                'policy': ConfigurationReference(
                    configuration_id=configuration.configuration_id,
                    revision=configuration.revision,
                )
            },
            author='adm_demo',
            reason='Disable policy lookup.',
            effective_time=_now(),
            updated_at=_now(),
        )
    )
    app = create_app(
        Settings(environment='test', identity_mode=IdentityMode.DEVELOPER),
        configuration_repository=configurations,
        release_set_repository=releases,
    )

    with TestClient(app) as client:
        response = client.post(
            '/internal/v1/policy/search',
            headers={'Authorization': 'Bearer synthetic-integration'},
            json={'claim_id': 'clm_policy', 'policy_reference': 'POLICY-001'},
        )

    assert response.status_code == 503
    assert response.json()['error']['code'] == 'INTEGRATION_DISABLED'


def test_source_mismatch_refuses_runtime_composition() -> None:
    configuration = _configuration(
        'assessor_service',
        'assessor_routing',
        source=IntegrationSourceValue.CONFIGURED_SERVICE,
    )
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    configurations.create(configuration)
    releases.create(
        ReleaseSetRecord(
            release_set_id='rel_mismatched_assessor',
            environment='test',
            runtime_profile='fixture',
            revision=1,
            state=ReleaseSetState.PUBLISHED,
            configuration_refs={},
            integration_refs={
                'assessor_service': ConfigurationReference(
                    configuration_id=configuration.configuration_id,
                    revision=configuration.revision,
                )
            },
            author='adm_demo',
            reason='Exercise a source mismatch.',
            effective_time=_now(),
            updated_at=_now(),
        )
    )

    with pytest.raises(RuntimeProfileConfigurationError):
        create_app(
            Settings(environment='test', identity_mode=IdentityMode.DEVELOPER),
            configuration_repository=configurations,
            release_set_repository=releases,
        )


def test_health_check_uses_the_published_timeout() -> None:
    configuration = _configuration(
        'assessor_service',
        'assessor_routing',
        timeout=0.01,
    )
    policy = _policy(configuration).snapshot()

    class SlowFixtureAssessor:
        integration_source = IntegrationSourceValue.FIXTURE

        @staticmethod
        def connection_status() -> str:
            sleep(0.1)
            return 'using_fixture'

    projection = get_integration(
        SimpleNamespace(assessor_service_adapter=SlowFixtureAssessor()),
        policy,
        'assessor_service',
    )

    assert projection.health.value == 'unavailable'
    assert projection.failure_code == 'INTEGRATION_HEALTH_TIMEOUT'
