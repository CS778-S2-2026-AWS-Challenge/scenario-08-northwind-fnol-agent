from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.core.errors import ApiError
from backend.domain.agent_action_registry import registered_actions
from backend.domain.configuration import (
    ConfigurationImpact,
    ConfigurationRecord,
    ConfigurationState,
)
from backend.domain.knowledge import KnowledgeChunk, KnowledgeSearch
from backend.domain.models import (
    AgentAction,
    Channel,
    CustomerNextStep,
    ResponsibleParty,
    WorkingClaim,
)
from backend.domain.release import ConfigurationReference, ReleaseSetRecord, ReleaseSetState
from backend.repositories.configuration import ConfigurationRepository
from backend.repositories.fixture import FixtureRepository
from backend.repositories.release_set import ReleaseSetRepository
from backend.services.agent import (
    AgentProposal,
    AgentTurnContext,
    FeatureControlledAgent,
)
from backend.services.model_agent import KnowledgeGroundedAgent
from backend.services.runtime_agent_policy import (
    RuntimeAgentPolicyResolver,
    enforce_agent_proposal,
    parse_agent_configuration,
    registered_agent_tool_names,
)
from backend.services.runtime_configuration import (
    RuntimeConfigurationResolutionError,
    RuntimeConfigurationResolver,
)

FIXED_TIME = datetime(2026, 9, 7, 10, 0, tzinfo=UTC)


def _values(domain: str, version: str) -> dict[str, object]:
    values: dict[str, dict[str, object]] = {
        'agent_instruction': {
            'prompt_version': 'northwind-fnol-motor-claimant-v4',
            'purpose': 'claimant_agent',
            'system_prompt': 'Follow the published Northwind claimant instruction.',
        },
        'agent_tool_policy': {
            'policy_version': version,
            'allowed_action_codes': list(registered_actions()),
            'allowed_tool_names': list(registered_agent_tool_names()),
        },
        'agent_rule': {
            'rules_version': version,
            'disabled_rule_ids': [],
            'observation_rule_ids': [],
        },
        'feature': {
            'feature_version': version,
            'model_assisted_turns': True,
            'knowledge_retrieval': True,
        },
    }
    return values[domain]


def _configuration(domain: str, version: str = 'policy-v1') -> ConfigurationRecord:
    return ConfigurationRecord(
        configuration_id=f'cfg_{domain}_{version}',
        domain=domain,
        revision=1,
        state=ConfigurationState.PUBLISHED,
        impact=ConfigurationImpact.HIGH,
        values=_values(domain, version),
        author='admin-1',
        reason='Publish a complete Agent runtime policy.',
        updated_at=FIXED_TIME,
    )


def _release(
    configurations: ConfigurationRepository,
    releases: ReleaseSetRepository,
    *,
    version: str = 'policy-v1',
    omitted_domain: str | None = None,
    value_overrides: dict[str, dict[str, object]] | None = None,
    updated_at: datetime = FIXED_TIME,
) -> ReleaseSetRecord:
    records: dict[str, ConfigurationRecord] = {}
    for domain in ('agent_instruction', 'agent_tool_policy', 'agent_rule', 'feature'):
        if domain == omitted_domain:
            continue
        record = _configuration(domain, version)
        if value_overrides is not None and domain in value_overrides:
            record = record.model_copy(update={'values': value_overrides[domain]})
        records[domain] = record
    for record in records.values():
        configurations.create(record)
    release = ReleaseSetRecord(
        release_set_id=f'rel_{version}',
        environment='test',
        runtime_profile='fixture',
        revision=1,
        state=ReleaseSetState.PUBLISHED,
        configuration_refs={
            domain: ConfigurationReference(
                configuration_id=record.configuration_id,
                revision=record.revision,
            )
            for domain, record in records.items()
        },
        author='admin-1',
        reason='Activate one coherent Agent policy.',
        effective_time=FIXED_TIME,
        updated_at=updated_at,
    )
    releases.create(release)
    return release


def _resolver(
    configurations: ConfigurationRepository,
    releases: ReleaseSetRepository,
) -> RuntimeAgentPolicyResolver:
    return RuntimeAgentPolicyResolver(
        RuntimeConfigurationResolver(
            configurations,
            releases,
            environment='test',
            runtime_profile='fixture',
        )
    )


def _proposal(action: AgentAction = AgentAction.ASK) -> AgentProposal:
    return AgentProposal(
        action=action,
        reason_codes=['TEST_PROPOSAL'],
        customer_reason='A bounded test proposal.',
        customer_response='Please provide the next required detail.',
        customer_next_step=CustomerNextStep(
            status='provide_detail',
            summary='Provide the next required detail.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        form_changes=[],
        state_changes=[],
        proposed_signals=[],
        required_tools=[],
        next_action_requirements=[],
    )


class _RecordingAgent:
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        self.calls = 0
        self.last_context: AgentTurnContext | None = None

    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        self.calls += 1
        self.last_context = context
        return replace(_proposal(), reason_codes=[self.reason_code])


class _UnexpectedRetriever:
    def connection_status(self) -> str:
        return 'available'

    def search(self, _query: KnowledgeSearch) -> list[KnowledgeChunk]:
        raise AssertionError('Knowledge retrieval must not run when the feature is disabled.')


def test_agent_configuration_rejects_unregistered_permissions_and_protected_rule_changes() -> None:
    with pytest.raises(ValueError):
        parse_agent_configuration(
            'agent_tool_policy',
            {
                'policy_version': 'invalid-policy',
                'allowed_action_codes': ['claim.unregistered_write'],
                'allowed_tool_names': [],
            },
        )
    with pytest.raises(ValueError):
        parse_agent_configuration(
            'agent_rule',
            {
                'rules_version': 'invalid-rules',
                'disabled_rule_ids': ['BR-SAFETY-001'],
                'observation_rule_ids': [],
            },
        )


def test_active_release_requires_every_typed_agent_policy_domain() -> None:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    _release(configurations, releases, omitted_domain='agent_tool_policy')

    with pytest.raises(RuntimeConfigurationResolutionError):
        _resolver(configurations, releases).resolve_for_turn()


def test_controlled_rule_overlay_changes_only_the_declared_branch() -> None:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    _release(
        configurations,
        releases,
        value_overrides={
            'agent_rule': {
                'rules_version': 'policy-v1',
                'disabled_rule_ids': ['BR-PARTICIPANT-WITNESS-001'],
                'observation_rule_ids': [],
            }
        },
    )
    policy = _resolver(configurations, releases).resolve_for_turn()
    assert policy is not None
    claim = WorkingClaim(
        claim_id='clm_policy',
        customer_id='synthetic-claimant',
        revision=1,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        incident_type='motor',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Describe the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )

    result = policy.branch_evaluator().evaluate(
        claim,
        latest_message='A witness spoke to police after the collision.',
    )

    branches = {item.branch_id: item for item in result.branch_results}
    assert branches['participant.witness'].status == 'exited'
    assert branches['authority.police'].status == 'candidate'
    assert result.branch_rules_version == 'policy-v1'


def test_tool_policy_can_remove_but_cannot_grant_runtime_permissions() -> None:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    _release(
        configurations,
        releases,
        value_overrides={
            'agent_tool_policy': {
                'policy_version': 'restricted-policy',
                'allowed_action_codes': [
                    'conversation.acknowledge',
                    'conversation.state_limitation',
                    'human.create_handoff',
                    'runtime.fail_safe',
                    'runtime.interrupt_urgent',
                ],
                'allowed_tool_names': ['handoff_store.create'],
            }
        },
    )
    policy = _resolver(configurations, releases).resolve_for_turn()
    assert policy is not None

    with pytest.raises(ApiError) as blocked:
        enforce_agent_proposal(policy, _proposal())

    assert blocked.value.code == 'AGENT_ACTION_NOT_PERMITTED'


def test_feature_setting_disables_model_assistance_without_disabling_runtime_safety() -> None:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    _release(
        configurations,
        releases,
        value_overrides={
            'feature': {
                'feature_version': 'restricted-features',
                'model_assisted_turns': False,
                'knowledge_retrieval': True,
            }
        },
    )
    policy = _resolver(configurations, releases).resolve_for_turn()
    assert policy is not None
    claim = WorkingClaim(
        claim_id='clm_feature',
        customer_id='cus_demo',
        revision=1,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        incident_type='motor',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Describe the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )
    primary = _RecordingAgent('MODEL_USED')
    fallback = _RecordingAgent('CONTROLLED_USED')
    provider = FeatureControlledAgent(primary, fallback)

    proposal = provider.propose_turn(
        AgentTurnContext(
            claim=claim,
            session_id='ses_feature',
            trigger_message_id='msg_feature',
            message_text='A routine report.',
            evidence_refs=[],
            runtime_configuration_snapshot=policy.runtime_snapshot,
            runtime_policy=policy,
        )
    )

    assert proposal.reason_codes == ['CONTROLLED_USED']
    assert primary.calls == 0
    assert fallback.calls == 1


def test_feature_setting_disables_knowledge_retrieval_before_provider_io() -> None:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    _release(
        configurations,
        releases,
        value_overrides={
            'feature': {
                'feature_version': 'no-retrieval',
                'model_assisted_turns': True,
                'knowledge_retrieval': False,
            }
        },
    )
    policy = _resolver(configurations, releases).resolve_for_turn()
    assert policy is not None
    claim = WorkingClaim(
        claim_id='clm_knowledge_feature',
        customer_id='cus_demo',
        revision=1,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        incident_type='motor',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Describe the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )
    provider = _RecordingAgent('NO_RETRIEVAL')
    grounded = KnowledgeGroundedAgent(provider, _UnexpectedRetriever())

    grounded.propose_turn(
        AgentTurnContext(
            claim=claim,
            session_id='ses_knowledge_feature',
            trigger_message_id='msg_knowledge_feature',
            message_text='What does my policy say?',
            evidence_refs=[],
            runtime_configuration_snapshot=policy.runtime_snapshot,
            runtime_policy=policy,
        )
    )

    assert provider.last_context is not None
    assert provider.last_context.knowledge_status == 'disabled'
    assert provider.last_context.knowledge_results == ()


def test_next_turn_uses_the_next_complete_release_without_mutating_the_prior_snapshot() -> None:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    first_release = _release(configurations, releases, version='policy-v1')
    resolver = _resolver(configurations, releases)
    first = resolver.resolve_for_turn()
    assert first is not None

    releases.save(
        first_release.model_copy(
            update={
                'revision': 2,
                'state': ReleaseSetState.SUPERSEDED,
                'updated_at': FIXED_TIME + timedelta(seconds=1),
            }
        ),
        expected_revision=1,
    )
    _release(
        configurations,
        releases,
        version='policy-v2',
        updated_at=FIXED_TIME + timedelta(seconds=2),
    )
    second = resolver.resolve_for_turn()
    assert second is not None

    assert first.runtime_snapshot.release_set_id == 'rel_policy-v1'
    assert first.controlled_rules.rules_version == 'policy-v1'
    assert second.runtime_snapshot.release_set_id == 'rel_policy-v2'
    assert second.controlled_rules.rules_version == 'policy-v2'


def test_fixture_active_queries_ignore_historical_published_revisions() -> None:
    configurations = ConfigurationRepository()
    feature = _configuration('feature')
    configurations.create(feature)
    configurations.save(
        feature.model_copy(
            update={
                'revision': 2,
                'state': ConfigurationState.WITHDRAWN,
                'updated_at': FIXED_TIME + timedelta(seconds=1),
            }
        ),
        expected_revision=1,
    )
    assert configurations.active('feature') is None

    releases = ReleaseSetRepository()
    release = _release(ConfigurationRepository(), releases)
    releases.save(
        release.model_copy(
            update={
                'revision': 2,
                'state': ReleaseSetState.SUPERSEDED,
                'updated_at': FIXED_TIME + timedelta(seconds=1),
            }
        ),
        expected_revision=1,
    )
    assert releases.active('test', 'fixture') is None


def test_message_turn_persists_exact_release_and_configuration_versions() -> None:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    release = _release(configurations, releases)
    claims = FixtureRepository()
    app = create_app(
        Settings(environment='test', identity_mode=IdentityMode.DEVELOPER),
        repository=claims,
        configuration_repository=configurations,
        release_set_repository=releases,
    )
    headers = {'Authorization': 'Bearer synthetic-claimant'}
    with TestClient(app) as client:
        created = client.post(
            '/api/v1/claims',
            headers={**headers, 'Idempotency-Key': 'runtime-policy-claim'},
            json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
        )
        assert created.status_code == 201, created.text
        claim = created.json()['claim']
        session = created.json()['session']
        turn = client.post(
            f'/api/v1/claims/{claim["claim_id"]}/sessions/{session["session_id"]}/messages',
            headers={
                **headers,
                'Idempotency-Key': 'runtime-policy-turn',
                'If-Match': str(claim['revision']),
            },
            json={
                'client_message_id': 'runtime-policy-message',
                'content': {'type': 'text', 'text': 'My parked car was damaged.'},
                'evidence_refs': [],
            },
        )
        assert turn.status_code == 200, turn.text

    decisions = claims.list_agent_decisions(claim['claim_id'], 'cus_demo')
    assert len(decisions) == 1
    provenance = decisions[0].runtime_configuration
    assert provenance is not None
    assert provenance.release_set_id == release.release_set_id
    assert set(provenance.configurations) == {
        'agent_instruction',
        'agent_tool_policy',
        'agent_rule',
        'feature',
    }
    assert all(reference.revision == 1 for reference in provenance.configurations.values())
