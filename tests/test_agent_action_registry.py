import pytest
from pydantic import ValidationError

from backend.domain.agent_action_registry import (
    AGENT_ACTION_REGISTRY,
    ActionActorRole,
    ActionIdempotencyPolicy,
    ActionNamespace,
    ActionSideEffectClass,
    ActionStateEffect,
    ActionVisibility,
    AgentActionContract,
    ExecutionAuthority,
    action_contract,
    registered_actions,
)


def _contract_data(action_code: str, **updates: object) -> dict[str, object]:
    data = action_contract(action_code).model_dump()
    data.update(updates)
    return data


def test_registry_covers_all_target_namespaces_and_is_namespaced() -> None:
    assert {contract.namespace for contract in AGENT_ACTION_REGISTRY.values()} == set(
        ActionNamespace
    )
    assert all(code == contract.action_code for code, contract in AGENT_ACTION_REGISTRY.items())
    assert all('.' in code and not code.isupper() for code in AGENT_ACTION_REGISTRY)


def test_registry_exposes_expected_mvp_actions() -> None:
    for action_code in (
        'conversation.ask',
        'claim.propose_fact_patch',
        'human.create_handoff',
        'external.prepare_request',
        'runtime.fail_safe',
    ):
        assert action_contract(action_code).action_code == action_code


def test_every_published_entry_carries_complete_target_contract_fields() -> None:
    for contract in AGENT_ACTION_REGISTRY.values():
        assert contract.version == '1.0.0'
        assert contract.input_schema.additional_properties is False
        assert contract.input_schema.fields
        assert contract.allowed_actor_roles
        assert contract.allowed_lifecycle_states
        assert contract.precondition_rules
        assert contract.response_obligations
        assert contract.prohibited_outcomes


def test_proposal_role_is_separate_from_execution_authority() -> None:
    contract = action_contract('claim.create')
    assert ActionActorRole.MODEL in contract.allowed_actor_roles
    assert contract.authority_requirement is ExecutionAuthority.STAFF_OR_PUBLISHED_RULE
    assert contract.authority_requirement.value != ActionActorRole.MODEL.value


def test_unknown_action_is_rejected() -> None:
    with pytest.raises(ValueError, match='Unknown Agent action'):
        action_contract('claim.invent_authority')


def test_namespace_mismatch_is_rejected() -> None:
    with pytest.raises(ValidationError, match='namespace'):
        AgentActionContract(
            **_contract_data(
                'claim.apply_fact_patch',
                namespace=ActionNamespace.CONVERSATION,
            )
        )


def test_high_impact_action_requires_staff_or_rule_authority() -> None:
    with pytest.raises(ValidationError, match='High-impact'):
        AgentActionContract(
            **_contract_data(
                'human.record_decision',
                authority_requirement=ExecutionAuthority.RUNTIME_VALIDATION,
            )
        )


def test_external_write_requires_idempotency() -> None:
    with pytest.raises(ValidationError, match='idempotency'):
        AgentActionContract(
            **_contract_data(
                'external.submit_request',
                idempotency_policy=ActionIdempotencyPolicy.NOT_REQUIRED,
            )
        )


def test_published_external_retry_reconciles_before_retry() -> None:
    contract = action_contract('external.retry_request')
    assert contract.state_effect is ActionStateEffect.EXTERNAL_SIDE_EFFECT
    assert contract.side_effect_class is ActionSideEffectClass.EXTERNAL_WRITE
    assert contract.authority_requirement is ExecutionAuthority.STAFF_OR_PUBLISHED_RULE
    assert contract.idempotency_policy is ActionIdempotencyPolicy.RECONCILE_BEFORE_RETRY
    assert 'unknown_outcome_reconciled' in contract.precondition_rules


def test_published_claim_creation_is_an_idempotent_external_write() -> None:
    contract = action_contract('claim.create')
    assert contract.state_effect is ActionStateEffect.CLAIM_MUTATION
    assert contract.side_effect_class is ActionSideEffectClass.EXTERNAL_WRITE
    assert contract.idempotency_policy is ActionIdempotencyPolicy.REQUIRED
    assert contract.permitted_tools == ('claims_service.create_claim',)
    assert 'idempotency_key' in {field.name for field in contract.input_schema.fields}


def test_staff_decision_action_is_not_claimant_visible() -> None:
    contract = action_contract('human.record_decision')
    assert contract.visibility == (ActionVisibility.STAFF, ActionVisibility.INTERNAL)


def test_registered_actions_filter_by_namespace_without_mutating_registry() -> None:
    claim_actions = registered_actions(ActionNamespace.CLAIM)
    assert claim_actions
    assert all(name.startswith('claim.') for name in claim_actions)
    assert isinstance(claim_actions, tuple)
    before = len(AGENT_ACTION_REGISTRY)
    claim_actions += ('claim.fake',)
    assert len(AGENT_ACTION_REGISTRY) == before


def test_registry_contracts_and_input_schemas_are_immutable() -> None:
    contract = action_contract('conversation.answer')
    with pytest.raises(TypeError):
        AGENT_ACTION_REGISTRY['conversation.fake'] = contract  # type: ignore[index]
    with pytest.raises(ValidationError):
        contract.purpose = 'Changed outside the published registry'  # type: ignore[misc]
    with pytest.raises(ValidationError):
        contract.input_schema.fields = ()  # type: ignore[misc]
