import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from backend.domain.field_registry import REGISTERED_FIELD_CODES
from backend.repositories.scenario_loader import ScenarioFixture, load_scenarios

SCENARIO_DIRECTORY = Path(__file__).parent / 'fixtures' / 'scenarios'


def test_checked_in_scenarios_only_use_registered_form_field_codes() -> None:
    for scenario in load_scenarios(SCENARIO_DIRECTORY):
        assert set(scenario.claim.form) <= REGISTERED_FIELD_CODES
        for handoff in scenario.handoffs:
            assert set(handoff.packet.form_snapshot) <= REGISTERED_FIELD_CODES


def _at01_payload() -> dict[str, Any]:
    payload = json.loads((SCENARIO_DIRECTORY / 'AT-01-clear-motor.json').read_text())
    return copy.deepcopy(payload)


def test_scenario_loader_rejects_an_unregistered_claim_form_field() -> None:
    payload = _at01_payload()
    payload['claim']['form']['not_a_registered_field'] = payload['claim']['form'][
        'incident.description'
    ]

    with pytest.raises(ValidationError, match='not_a_registered_field'):
        ScenarioFixture.model_validate(payload)


def test_scenario_loader_rejects_an_unregistered_handoff_packet_field() -> None:
    payload = _at01_payload()
    field = payload['claim']['form']['incident.description']
    payload['handoffs'] = [
        {
            'handoff_id': 'hnd_fixture_invalid',
            'claim_id': payload['claim']['claim_id'],
            'type': 'human_support',
            'status': 'queued',
            'priority': 'standard',
            'queue': 'claimant_support',
            'support_need': 'human_requested',
            'preferred_channel': None,
            'reason_codes': ['HUMAN_SUPPORT_REQUESTED'],
            'reason': 'Synthetic reason.',
            'requested_action': 'Synthetic requested action.',
            'applied_rule': 'prototype_immediate_transfer',
            'packet': {
                'incident_summary': None,
                'form_revision': payload['claim']['revision'],
                'form_snapshot': {'not_a_registered_field': field},
                'evidence_refs': [],
                'missing_items': [],
                'pending_items': [],
                'conflicts': [],
                'low_confidence_items': [],
                'policy_citation_refs': [],
                'history_evidence_refs': [],
                'source_refs': [],
                'prior_customer_updates': [],
                'promised_next_step': 'Synthetic next step.',
            },
            'source_message_id': None,
            'assigned_to': None,
            'created_at': payload['claim']['created_at'],
            'accepted_at': None,
            'resolved_at': None,
        }
    ]

    with pytest.raises(ValidationError, match='not_a_registered_field'):
        ScenarioFixture.model_validate(payload)
