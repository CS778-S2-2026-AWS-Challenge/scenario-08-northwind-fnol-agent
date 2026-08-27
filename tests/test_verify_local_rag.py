from typing import Any

import pytest

from scripts.verify_local_rag import evaluate_case, retrieval_limit


def evaluation_case(**overrides: Any) -> dict[str, Any]:
    case: dict[str, Any] = {
        'case_id': 'RAG-E2E-TEST',
        'expected_citations': ['document#expected'],
        'retrieval_limit': 1,
    }
    case.update(overrides)
    return case


def test_exact_expected_citations_pass() -> None:
    assert evaluate_case(evaluation_case(), {'document#expected'}) == []


def test_expected_and_unexpected_citation_fails() -> None:
    failures = evaluate_case(evaluation_case(), {'document#expected', 'document#unexpected'})

    assert failures == ["RAG-E2E-TEST returned unexpected evidence ['document#unexpected']"]


def test_explicitly_allowed_additional_citation_passes() -> None:
    case = evaluation_case(allowed_citations=['document#allowed'])

    assert evaluate_case(case, {'document#expected', 'document#allowed'}) == []


@pytest.mark.parametrize('allowed_citations', ['document#allowed', [''], [1]])
def test_invalid_allowed_citations_fail(allowed_citations: object) -> None:
    failures = evaluate_case(
        evaluation_case(allowed_citations=allowed_citations), {'document#expected'}
    )

    assert failures == ['RAG-E2E-TEST allowed_citations must be a list of non-empty strings']


def test_required_citation_cannot_also_be_allowed() -> None:
    failures = evaluate_case(
        evaluation_case(allowed_citations=['document#expected']), {'document#expected'}
    )

    assert failures == [
        "RAG-E2E-TEST duplicates required citations as allowed ['document#expected']"
    ]


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


@pytest.mark.parametrize('value', [None, True, 0, 6, '1'])
def test_retrieval_limit_rejects_missing_or_invalid_values(value: object) -> None:
    case = evaluation_case(retrieval_limit=value)

    with pytest.raises(ValueError, match='retrieval_limit'):
        retrieval_limit(case)


def test_retrieval_limit_returns_declared_top_n_depth() -> None:
    assert retrieval_limit(evaluation_case(retrieval_limit=2)) == 2
