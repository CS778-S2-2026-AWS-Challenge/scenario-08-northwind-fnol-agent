"""Guard evidence-path anchoring and claimant/staff visibility on the live projections."""

import pytest

from backend.repositories.scenario_loader import EvidenceBusinessPath
from backend.services.evidence_visibility_check import (
    PathDefect,
    check_path_evidence,
    compare_claimant_projection,
    describe,
    paths_checked,
)


def _keys(defects: list[PathDefect]) -> set[tuple[str, str, str]]:
    return {(defect.business_path, defect.scenario_id, defect.code) for defect in defects}


def test_the_check_covers_every_business_path() -> None:
    assert paths_checked() == len(EvidenceBusinessPath)


def test_no_recorded_evidence_path_defect_reproduces() -> None:
    defects = check_path_evidence()

    assert _keys(defects) == set(), describe(defects)


def test_the_claimant_visibility_leak_no_longer_reproduces() -> None:
    defect_codes = {defect.code for defect in check_path_evidence()}

    assert 'INTERNAL_EVIDENCE_VISIBLE_TO_CLAIMANT' not in defect_codes


def test_path_fixtures_are_anchored_to_their_canonical_scenarios() -> None:
    defect_codes = {defect.code for defect in check_path_evidence()}

    assert 'PATH_FIXTURE_NOT_ANCHORED' not in defect_codes


def test_the_clean_report_is_explicit() -> None:
    assert describe(check_path_evidence()) == 'No evidence path defects found.'


@pytest.mark.parametrize(
    ('declared', 'projected', 'unexpected', 'missing'),
    [
        ({'a', 'b'}, {'a', 'b'}, set(), set()),
        ({'a'}, {'a', 'b'}, {'b'}, set()),
        ({'a', 'b'}, {'a'}, set(), {'b'}),
        ({'a', 'b'}, {'a', 'c'}, {'c'}, {'b'}),
    ],
)
def test_the_claimant_comparison_reports_both_directions(
    declared: set[str],
    projected: set[str],
    unexpected: set[str],
    missing: set[str],
) -> None:
    assert compare_claimant_projection(declared, projected) == (unexpected, missing)


def test_a_missing_claimant_visible_record_is_a_reportable_difference() -> None:
    unexpected, missing = compare_claimant_projection({'evd_expected'}, set())

    assert unexpected == set()
    assert missing == {'evd_expected'}
