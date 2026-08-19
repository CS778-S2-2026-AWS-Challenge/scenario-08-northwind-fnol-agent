import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.domain import evidence as evidence_domain
from backend.domain.evidence import (
    EvidenceLifecycleStage,
    UnregisteredEvidenceShape,
    is_registered_evidence_shape,
    lifecycle_stage_for,
)
from backend.domain.models import EvidenceFileStatus, EvidenceRecord, EvidenceSource, EvidenceStatus
from backend.repositories import scenario_loader
from backend.repositories.scenario_loader import (
    CANONICAL_SCENARIO_DIRECTORY,
    EvidenceBusinessPath,
    load_scenarios,
)
from backend.services.evidence_fixtures import (
    LIFECYCLE_FIXTURE_PATH,
    EvidenceFixtureService,
    check_paths,
    check_records,
    describe_paths,
)
from backend.services.support import now_utc

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PROFESSIONAL_REVIEW_DIRECTORY = REPOSITORY_ROOT / 'tests' / 'fixtures' / 'professional_review'


@pytest.fixture
def service() -> EvidenceFixtureService:
    return EvidenceFixtureService()


def test_one_service_answers_for_every_business_path(service: EvidenceFixtureService) -> None:
    paths = service.all_paths()

    assert {path.business_path for path in paths} == set(EvidenceBusinessPath)
    assert len(paths) == 5
    for path in paths:
        assert path.records, f'{path.business_path.value} has no evidence'
        assert len(path.stages) == len(path.records)
        # Derived state is recomputed from the records by the runtime rules, so
        # a path cannot state an evidence state its own records contradict.
        assert path.evidence_state is evidence_domain.evidence_state_for(list(path.records))
        assert path.evidence_summary == evidence_domain.evidence_summary_for(list(path.records))


def test_every_lifecycle_stage_is_reachable_through_the_service(
    service: EvidenceFixtureService,
) -> None:
    cases = service.lifecycle_cases()

    assert {case.lifecycle_stage for case in cases} == set(EvidenceLifecycleStage)
    for stage in EvidenceLifecycleStage:
        case = service.lifecycle_case(stage)
        # The catalogue's declared stage and the runtime rule must agree.
        assert lifecycle_stage_for(case.evidence) is stage


def test_the_fixture_loader_uses_the_shared_rule_rather_than_its_own_copy() -> None:
    """No path may carry a private copy of the state rules.

    The loader used to repeat the status/file-status mapping in its own
    validator. Declaring a stage the shared rule would not give the same record
    must now fail, which it can only do if the two are the same rule.
    """
    received_case = json.loads(LIFECYCLE_FIXTURE_PATH.read_text(encoding='utf-8'))
    case = next(item for item in received_case['fixtures'] if item['lifecycle_stage'] == 'received')
    relabelled = {**case, 'lifecycle_stage': 'unofficial'}

    with pytest.raises(ValidationError):
        scenario_loader.EvidenceLifecycleCase.model_validate(relabelled)

    # And the record itself still resolves to its true stage.
    parsed = scenario_loader.EvidenceLifecycleCase.model_validate(case)
    assert lifecycle_stage_for(parsed.evidence) is EvidenceLifecycleStage.RECEIVED


def _records_in(directory: Path) -> list[tuple[str, EvidenceRecord]]:
    found: list[tuple[str, EvidenceRecord]] = []
    for scenario in load_scenarios(directory):
        found.extend((scenario.scenario_id, record) for record in scenario.evidence)
    return found


def test_no_fixture_anywhere_introduces_a_private_evidence_model(
    service: EvidenceFixtureService,
) -> None:
    """Sweep every evidence-bearing fixture in the repository.

    Parsing already forces the domain `EvidenceRecord`, so a private model
    fails at load. This adds the subtler check: a structurally valid record in
    a status/file-status combination that no shared lifecycle stage covers.
    """
    collected: list[tuple[str, EvidenceRecord]] = []
    collected.extend(_records_in(CANONICAL_SCENARIO_DIRECTORY))
    collected.extend(_records_in(PROFESSIONAL_REVIEW_DIRECTORY))
    collected.extend(
        (f'lifecycle:{case.fixture_id}', case.evidence) for case in service.lifecycle_cases()
    )
    collected.extend(
        (f'path:{entry.business_path.value}', fixture.evidence)
        for entry in service.path_entries()
        for fixture in entry.evidence
    )

    assert len(collected) >= 15

    violations = [
        violation
        for origin, record in collected
        for violation in check_records([record], origin=origin)
    ]
    assert violations == []

    # Sources stay inside the registered vocabulary too.
    assert {record.source for _, record in collected} <= set(EvidenceSource)


def test_paths_are_clean_and_describable(service: EvidenceFixtureService) -> None:
    assert check_paths(service) == []

    lines = describe_paths(service)
    assert len(lines) == 5
    assert all(line.startswith('PASS ') for line in lines)
    for path in service.all_paths():
        assert any(path.scenario_id in line for line in lines)


def test_an_unregistered_state_combination_is_rejected_rather_than_guessed() -> None:
    """A record the shared rules do not cover must fail loudly.

    `received` with an `awaiting_upload` file would mean the claim holds a file
    it never received. Nothing may silently classify it.
    """
    record = EvidenceRecord(
        evidence_id='evd_invalid',
        claim_id='clm_invalid',
        kind='incident_image',
        status=EvidenceStatus.RECEIVED,
        file_status=EvidenceFileStatus.AWAITING_UPLOAD,
        source=EvidenceSource.CLAIMANT,
        created_at=now_utc(),
        updated_at=now_utc(),
    )

    with pytest.raises(UnregisteredEvidenceShape):
        lifecycle_stage_for(record)
    assert is_registered_evidence_shape(record) is False

    violations = check_records([record], origin='synthetic')
    assert len(violations) == 1
    assert violations[0].evidence_id == 'evd_invalid'
    assert 'awaiting_upload' in violations[0].reason


def test_a_conflict_is_registered_but_is_not_an_entry_stage() -> None:
    """`inconsistent` is reachable but has no entry stage, on purpose.

    Two settled records disagreeing on a material fact is a conflict, not a
    state a claim can start an evidence item in. It is registered so the
    professional-review path can use it, and excluded from the five-stage
    catalogue so nothing treats it as an ordinary entry.
    """
    settled = EvidenceRecord(
        evidence_id='evd_conflict',
        claim_id='clm_conflict',
        kind='claimant_statement',
        status=EvidenceStatus.INCONSISTENT,
        file_status=EvidenceFileStatus.READY,
        source=EvidenceSource.CLAIMANT,
        created_at=now_utc(),
        updated_at=now_utc(),
    )
    in_flight = settled.model_copy(
        update={'evidence_id': 'evd_conflict_pending', 'file_status': EvidenceFileStatus.UPLOADING}
    )

    assert is_registered_evidence_shape(settled) is True
    assert check_records([settled], origin='synthetic') == []
    with pytest.raises(UnregisteredEvidenceShape):
        lifecycle_stage_for(settled)

    # A conflict cannot be declared while the file is still arriving.
    assert is_registered_evidence_shape(in_flight) is False
    assert len(check_records([in_flight], origin='synthetic')) == 1
