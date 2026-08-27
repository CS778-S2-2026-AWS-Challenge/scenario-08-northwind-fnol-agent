from typing import Any

import pytest

from scripts.verify_local_rag import evaluate_case


def evaluation_case(**overrides: Any) -> dict[str, Any]:
    case: dict[str, Any] = {
        'case_id': 'RAG-E2E-TEST',
        'expected_citations': ['document#expected'],
    }
    case.update(overrides)
    return case


def test_exact_expected_citations_pass() -> None:
    assert evaluate_case(evaluation_case(), {'document#expected'}) == []


def test_expected_and_unexpected_citation_fails() -> None:
    failures = evaluate_case(evaluation_case(), {'document#expected', 'document#unexpected'})

    assert failures == ["RAG-E2E-TEST returned unexpected evidence ['document#unexpected']"]


def test_empty_expected_citations_reject_any_result() -> None:
    failures = evaluate_case(evaluation_case(expected_citations=[]), {'document#unexpected'})

    assert failures == ["RAG-E2E-TEST returned unexpected evidence ['document#unexpected']"]


@pytest.mark.parametrize(
    'required_structured_data',
    [[], 'policy_schedule.excesses', ['policy_schedule.unknown'], [1]],
)
def test_invalid_required_structured_data_fails(required_structured_data: object) -> None:
    failures = evaluate_case(
        evaluation_case(required_structured_data=required_structured_data),
        {'document#expected'},
    )

    assert failures


def test_supported_required_structured_data_passes() -> None:
    case = evaluation_case(
        required_structured_data=[
            'policy_schedule.excesses',
            'policy_schedule.endorsements.hidden_water_damage',
        ]
    )

    assert evaluate_case(case, {'document#expected'}) == []
