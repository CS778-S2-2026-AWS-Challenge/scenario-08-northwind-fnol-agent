"""Pin the evidence path defects that are currently open.

This is a record, not a gate. The defects below are real and belong to their
named stacks, so the suite must not fail while they are open — but it must also
not let them change silently. When one is fixed, this test fails and the fixer
updates `docs/day4-evidence-visibility-defects.md` in the same change.
"""

from backend.repositories.scenario_loader import EvidenceBusinessPath
from backend.services.evidence_visibility_check import (
    PathDefect,
    check_path_evidence,
    describe,
    paths_checked,
)

# (business_path, scenario_id, code) for every defect recorded on 2026-08-19.
KNOWN_DEFECTS = {
    ('fast', 'AT-01-clear-motor', 'PATH_FIXTURE_NOT_ANCHORED'),
    ('professional_review', 'AT-02-coverage-ambiguity', 'PATH_FIXTURE_NOT_ANCHORED'),
    ('urgent', 'AT-04-urgent', 'PATH_FIXTURE_NOT_ANCHORED'),
    ('human_request', 'AT-05-human-request', 'PATH_FIXTURE_NOT_ANCHORED'),
    ('pending_evidence', 'AT-06-pending-evidence', 'PATH_FIXTURE_NOT_ANCHORED'),
    ('pending_evidence', 'AT-06-pending-evidence', 'INTERNAL_EVIDENCE_VISIBLE_TO_CLAIMANT'),
}


def _keys(defects: list[PathDefect]) -> set[tuple[str, str, str]]:
    return {(defect.business_path, defect.scenario_id, defect.code) for defect in defects}


def test_the_check_covers_every_business_path() -> None:
    assert paths_checked() == len(EvidenceBusinessPath)


def test_the_recorded_defect_set_has_not_changed() -> None:
    """Fails in both directions, on purpose.

    A new defect must be recorded and assigned. A fixed defect must be removed
    from the record, so the document cannot keep describing a problem that no
    longer exists.
    """
    found = _keys(check_path_evidence())

    newly_appeared = found - KNOWN_DEFECTS
    assert not newly_appeared, (
        'New evidence path defects appeared. Record them in '
        f'docs/day4-evidence-visibility-defects.md and assign an owner: {sorted(newly_appeared)}'
    )

    resolved = KNOWN_DEFECTS - found
    assert not resolved, (
        'Recorded defects no longer reproduce. Remove them from '
        f'docs/day4-evidence-visibility-defects.md and from KNOWN_DEFECTS: {sorted(resolved)}'
    )


def test_every_defect_names_path_expected_actual_and_stack() -> None:
    """Issue #140 requires each defect to carry all four facts."""
    defects = check_path_evidence()
    assert defects

    for defect in defects:
        assert defect.business_path
        assert defect.scenario_id
        assert defect.expected and defect.actual
        assert defect.expected != defect.actual
        assert defect.responsible_stack
        rendered = defect.render()
        for label in ('expected:', 'actual:', 'stack:'):
            assert label in rendered


def test_the_claimant_leak_is_reported_against_the_evidence_stack() -> None:
    """The one defect that is not a fixture problem.

    `EvidenceRecord` carries no visibility field, so the claimant evidence list
    cannot filter and returns records the claimant never provided. That belongs
    to the evidence API and domain model, and must not be papered over by
    editing the fixture.
    """
    leak = next(
        defect
        for defect in check_path_evidence()
        if defect.code == 'INTERNAL_EVIDENCE_VISIBLE_TO_CLAIMANT'
    )

    assert 'evidence API and domain model' in leak.responsible_stack
    assert 'evd_fixture_at06_internal' in leak.actual
    assert 'source=staff' in leak.actual


def test_the_report_is_readable_when_clean_and_when_not() -> None:
    assert describe([]) == 'No evidence path defects found.'
    assert 'DEFECT' in describe(check_path_evidence())
