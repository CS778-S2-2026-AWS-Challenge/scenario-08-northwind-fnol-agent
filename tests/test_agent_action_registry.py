import pytest
from pydantic import ValidationError

from backend.domain.agent_action_registry import (
    AGENT_ACTION_REGISTRY,
    ActionAuthority,
    ActionNamespace,
    ActionStateEffect,
    AgentActionContract,
    action_contract,
    registered_actions,
)


def test_registry_covers_all_target_namespaces_and_is_namespaced() -> None:
    assert {contract.namespace for contract in AGENT_ACTION_REGISTRY.values()} == set(
        ActionNamespace
    )
    assert all(name == contract.name for name, contract in AGENT_ACTION_REGISTRY.items())
    assert all('.' in name and not name.isupper() for name in AGENT_ACTION_REGISTRY)


def test_registry_exposes_expected_mvp_actions() -> None:
    for name in (
        'conversation.ask',
        'claim.propose_fact_patch',
        'human.create_handoff',
        'external.prepare_request',
        'runtime.fail_safe',
    ):
        assert action_contract(name).name == name


def test_unknown_action_is_rejected() -> None:
    with pytest.raises(ValueError, match='Unknown Agent action'):
        action_contract('claim.invent_authority')


def test_namespace_mismatch_is_rejected() -> None:
    with pytest.raises(ValidationError, match='namespace'):
        AgentActionContract(
            name='claim.apply_fact_patch',
            namespace=ActionNamespace.CONVERSATION,
            purpose='Invalid test contract',
            authority=ActionAuthority.RUNTIME_VALIDATED,
            state_effect=ActionStateEffect.NONE,
            visibility=('claimant',),
            failure_policy='Reject safely.',
        )


def test_model_cannot_authorise_state_changes() -> None:
    with pytest.raises(ValidationError, match='cannot grant authority'):
        AgentActionContract(
            name='claim.unsafe_mutation',
            namespace=ActionNamespace.CLAIM,
            purpose='Invalid test contract',
            authority=ActionAuthority.MODEL_PROPOSAL,
            state_effect=ActionStateEffect.CLAIM_MUTATION,
            visibility=('internal',),
            failure_policy='Reject safely.',
        )


def test_external_side_effect_requires_idempotency() -> None:
    with pytest.raises(ValidationError, match='idempotent'):
        AgentActionContract(
            name='external.unsafe_submit',
            namespace=ActionNamespace.EXTERNAL,
            purpose='Invalid test contract',
            authority=ActionAuthority.STAFF_OR_RULE_REQUIRED,
            state_effect=ActionStateEffect.EXTERNAL_SIDE_EFFECT,
            visibility=('staff',),
            failure_policy='Reject safely.',
        )


def test_registered_actions_filter_by_namespace_without_mutating_registry() -> None:
    claim_actions = registered_actions(ActionNamespace.CLAIM)
    assert claim_actions
    assert all(name.startswith('claim.') for name in claim_actions)
    assert isinstance(claim_actions, tuple)
    before = len(AGENT_ACTION_REGISTRY)
    claim_actions += ('claim.fake',)
    assert len(AGENT_ACTION_REGISTRY) == before


def test_registry_contracts_are_immutable() -> None:
    contract = action_contract('conversation.answer')
    with pytest.raises(TypeError):
        AGENT_ACTION_REGISTRY['conversation.fake'] = contract  # type: ignore[index]
    with pytest.raises(ValidationError):
        contract.purpose = 'Changed outside the published registry'  # type: ignore[misc]
