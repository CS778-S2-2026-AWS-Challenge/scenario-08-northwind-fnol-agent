"""One evidence fixture service shared by every business path.

Before this, each path reached for whichever fixture file it happened to know
about, and the rule mapping an evidence record to a lifecycle stage was written
out again in the fixture model. A path could drift without anything failing.

Everything now resolves through this service, and every record resolves through
the one domain rule in `backend/domain/evidence.py`.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from backend.domain.evidence import (
    EvidenceLifecycleStage,
    evidence_state_for,
    evidence_summary_for,
    is_registered_evidence_shape,
    lifecycle_stage_for,
)
from backend.domain.models import (
    EvidenceRecord,
    EvidenceState,
    EvidenceStatus,
    EvidenceSummary,
)
from backend.repositories.scenario_loader import (
    CANONICAL_SCENARIO_DIRECTORY,
    EvidenceBusinessPath,
    EvidenceLifecycleCase,
    EvidencePathEntry,
    FixtureVisibility,
    load_evidence_lifecycle_fixtures,
    load_evidence_path_fixtures,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_FIXTURE_DIRECTORY = REPOSITORY_ROOT / 'tests' / 'fixtures' / 'evidence'
LIFECYCLE_FIXTURE_PATH = EVIDENCE_FIXTURE_DIRECTORY / 'evidence-lifecycle.json'
PATH_FIXTURE_PATH = EVIDENCE_FIXTURE_DIRECTORY / 'path-entry-visibility.json'

CLAIMANT_VISIBLE_CLASSES = frozenset({FixtureVisibility.CLAIMANT_VISIBLE, FixtureVisibility.SHARED})


@dataclass(frozen=True, slots=True)
class EvidenceConformanceViolation:
    """One record that does not use the shared evidence model or state rules."""

    origin: str
    evidence_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class PathEvidence:
    """The complete effective evidence set for one business path."""

    business_path: EvidenceBusinessPath
    scenario_id: str
    claim_id: str
    records: tuple[EvidenceRecord, ...]
    claimant_visible_records: tuple[EvidenceRecord, ...]
    stages: tuple[EvidenceLifecycleStage, ...]

    @property
    def evidence_state(self) -> EvidenceState:
        return evidence_state_for(self.records)

    @property
    def evidence_summary(self) -> EvidenceSummary:
        return evidence_summary_for(self.records)


class EvidenceFixtureService:
    """The one place a business path asks for evidence fixtures."""

    def __init__(
        self,
        lifecycle_path: Path = LIFECYCLE_FIXTURE_PATH,
        path_fixture_path: Path = PATH_FIXTURE_PATH,
        scenario_directory: Path = CANONICAL_SCENARIO_DIRECTORY,
    ) -> None:
        self._lifecycle = load_evidence_lifecycle_fixtures(lifecycle_path)
        self._paths = load_evidence_path_fixtures(path_fixture_path, scenario_directory)

    def lifecycle_cases(self) -> tuple[EvidenceLifecycleCase, ...]:
        return tuple(self._lifecycle.fixtures)

    def lifecycle_case(self, stage: EvidenceLifecycleStage) -> EvidenceLifecycleCase:
        return next(case for case in self._lifecycle.fixtures if case.lifecycle_stage is stage)

    def path_entries(self) -> tuple[EvidencePathEntry, ...]:
        return tuple(self._paths.entries)

    def evidence_for(self, business_path: EvidenceBusinessPath) -> PathEvidence:
        entry = next(item for item in self._paths.entries if item.business_path is business_path)
        records = tuple(fixture.evidence for fixture in entry.evidence)
        claimant_visible = tuple(
            fixture.evidence
            for fixture in entry.evidence
            if fixture.visibility in CLAIMANT_VISIBLE_CLASSES
        )
        return PathEvidence(
            business_path=entry.business_path,
            scenario_id=entry.scenario_id,
            claim_id=entry.claim_id,
            records=records,
            claimant_visible_records=claimant_visible,
            stages=tuple(
                lifecycle_stage_for(record)
                for record in records
                if record.status is not EvidenceStatus.INCONSISTENT
            ),
        )

    def all_paths(self) -> tuple[PathEvidence, ...]:
        return tuple(self.evidence_for(path) for path in EvidenceBusinessPath)


def check_records(
    records: Iterable[EvidenceRecord],
    *,
    origin: str,
) -> list[EvidenceConformanceViolation]:
    """Report records that do not use the shared evidence model.

    A record reaching this function has already parsed as the domain
    `EvidenceRecord`, so a private evidence model fails earlier, at load. This
    catches the subtler case: a structurally valid record in a status and file
    status combination no path is allowed to invent.
    """

    violations: list[EvidenceConformanceViolation] = []
    for record in records:
        if not is_registered_evidence_shape(record):
            violations.append(
                EvidenceConformanceViolation(
                    origin=origin,
                    evidence_id=record.evidence_id,
                    reason=(
                        f'{record.evidence_id}: status {record.status.value} with file '
                        f'status {record.file_status.value} is not a registered evidence '
                        'shape.'
                    ),
                )
            )
    return violations


def check_paths(service: EvidenceFixtureService) -> list[EvidenceConformanceViolation]:
    """Check every business path against the shared state and source rules."""

    violations: list[EvidenceConformanceViolation] = []
    for path_evidence in service.all_paths():
        violations.extend(
            check_records(
                path_evidence.records,
                origin=f'{path_evidence.business_path.value}:{path_evidence.scenario_id}',
            )
        )
    return violations


def describe_paths(service: EvidenceFixtureService) -> Sequence[str]:
    """Human-readable summary used by the repository verifier script."""

    lines = []
    for path_evidence in service.all_paths():
        stages = ','.join(stage.value for stage in path_evidence.stages)
        summary = path_evidence.evidence_summary
        lines.append(
            f'PASS {path_evidence.business_path.value}: '
            f'scenario={path_evidence.scenario_id} '
            f'state={path_evidence.evidence_state.value} '
            f'stages={stages} '
            f'received={summary.received} pending={summary.pending} '
            f'needs_attention={summary.needs_attention} '
            f'claimant_visible={len(path_evidence.claimant_visible_records)}'
            f'/{len(path_evidence.records)}'
        )
    return lines
