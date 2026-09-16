"""Versioned claimant-facing action contracts for browser presentation."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

CLAIMANT_ACTION_REGISTRY_VERSION = '1.0.0'

ClaimantActionType = Literal['claim_creation', 'external_service', 'conversation']
ClaimantExecutionBoundary = Literal['claimant_api', 'external_service', 'conversation']
ClaimantActionHandler = Literal[
    'create_claim',
    'review_details',
    'request_assessment',
    'none',
]


@dataclass(frozen=True)
class ClaimantActionContract:
    """One browser-safe action identity and its fixed execution meaning."""

    action_code: str
    action_type: ClaimantActionType
    execution_boundary: ClaimantExecutionBoundary
    handler: ClaimantActionHandler
    required_inputs: tuple[str, ...] = ()


def _contract(
    action_code: str,
    action_type: ClaimantActionType,
    execution_boundary: ClaimantExecutionBoundary,
    handler: ClaimantActionHandler,
    required_inputs: tuple[str, ...] = (),
) -> ClaimantActionContract:
    if not action_code.startswith('claimant.'):
        raise ValueError('Claimant action codes must use the claimant namespace.')
    return ClaimantActionContract(
        action_code=action_code,
        action_type=action_type,
        execution_boundary=execution_boundary,
        handler=handler,
        required_inputs=required_inputs,
    )


CLAIMANT_ACTION_REGISTRY = MappingProxyType(
    {
        contract.action_code: contract
        for contract in (
            _contract(
                'claimant.create_claim',
                'claim_creation',
                'claimant_api',
                'create_claim',
            ),
            _contract(
                'claimant.review_details',
                'conversation',
                'conversation',
                'review_details',
            ),
            _contract(
                'claimant.request_assessment',
                'external_service',
                'external_service',
                'request_assessment',
                ('claimant_consent',),
            ),
            _contract(
                'claimant.retry_assessment',
                'external_service',
                'external_service',
                'request_assessment',
            ),
            _contract(
                'claimant.track_assessment',
                'external_service',
                'external_service',
                'none',
            ),
            _contract(
                'claimant.await_staff_review',
                'external_service',
                'external_service',
                'none',
            ),
            _contract(
                'claimant.await_reconciliation',
                'external_service',
                'external_service',
                'none',
            ),
            _contract(
                'claimant.continue_conversation',
                'conversation',
                'conversation',
                'none',
            ),
        )
    }
)


def claimant_action_contract(action_code: str) -> ClaimantActionContract:
    """Return the canonical claimant action contract or reject an unknown code."""

    try:
        return CLAIMANT_ACTION_REGISTRY[action_code]
    except KeyError as exc:
        raise ValueError(f'Unknown claimant action: {action_code}.') from exc
