"""Compare declared path evidence against what the runtime actually projects.

The existing verifiers check each fixture family against itself, so a fixture
can agree with its own schema while disagreeing with the API a claimant or a
staff member really calls. This walks the five business paths, seeds the
canonical scenario each one names, and compares the declared evidence set and
visibility against the live claimant and staff projections.

It reports rather than repairs. A defect found here names the responsible stack
so it can be fixed at its source, instead of being smoothed over in fixture
data.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.repositories.fixture import FixtureRepository
from backend.repositories.scenario_loader import (
    CANONICAL_SCENARIO_DIRECTORY,
    EvidenceBusinessPath,
    ScenarioFixture,
    load_mvp_journey_scenarios,
    seed_scenario,
)
from backend.services.evidence_fixtures import (
    CLAIMANT_VISIBLE_CLASSES,
    EvidenceFixtureService,
)

CLAIMANT_AUTH = {'Authorization': 'Bearer synthetic-claimant'}
STAFF_AUTH = {'Authorization': 'Bearer synthetic-staff'}

# A record the claimant did not provide and cannot act on. Used to describe a
# leak precisely rather than asserting on one fixture's identifiers.
INTERNAL_SOURCES = frozenset({'staff', 'external_system'})


@dataclass(frozen=True, slots=True)
class PathDefect:
    """One reproducible difference between declared and runtime behaviour."""

    business_path: str
    scenario_id: str
    code: str
    expected: str
    actual: str
    responsible_stack: str

    def render(self) -> str:
        return (
            f'DEFECT {self.code} [{self.business_path}/{self.scenario_id}]\n'
            f'  expected: {self.expected}\n'
            f'  actual:   {self.actual}\n'
            f'  stack:    {self.responsible_stack}'
        )


def compare_claimant_projection(
    declared: set[str],
    projected: set[str],
) -> tuple[set[str], set[str]]:
    """Compare the declared and projected claimant sets in both directions.

    Returns (unexpected, missing). A one-directional check would report a
    projection that shows too much but stay silent on one that hides a record
    the claimant is entitled to, and would miss a mixed mismatch entirely.
    """

    return projected - declared, declared - projected


def _projections(scenario: ScenarioFixture) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    repository = FixtureRepository()
    seed_scenario(repository, scenario)
    claim_id = scenario.claim.claim_id
    settings = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)
    with TestClient(create_app(settings, repository)) as client:
        claimant = client.get(f'/api/v1/claims/{claim_id}/evidence', headers=CLAIMANT_AUTH)
        staff = client.get(
            f'/api/v1/workbench/claims/{claim_id}/evidence',
            headers=STAFF_AUTH,
        )
    claimant.raise_for_status()
    staff.raise_for_status()
    claimant_items: list[dict[str, Any]] = claimant.json()['items']
    staff_items: list[dict[str, Any]] = staff.json()['items']
    return claimant_items, staff_items


def check_path_evidence(
    service: EvidenceFixtureService | None = None,
    scenario_directory: Path = CANONICAL_SCENARIO_DIRECTORY,
) -> list[PathDefect]:
    """Walk every business path and report declared/runtime differences."""

    resolved = service or EvidenceFixtureService()
    scenarios = {item.scenario_id: item for item in load_mvp_journey_scenarios(scenario_directory)}
    defects: list[PathDefect] = []

    for entry in resolved.path_entries():
        scenario = scenarios[entry.scenario_id]
        declared = {fixture.evidence.evidence_id: fixture for fixture in entry.evidence}
        declared_claimant = {
            evidence_id
            for evidence_id, fixture in declared.items()
            if fixture.visibility in CLAIMANT_VISIBLE_CLASSES
        }
        scenario_ids = {record.evidence_id for record in scenario.evidence}
        claimant_items, staff_items = _projections(scenario)
        claimant_ids = {item['evidence_id'] for item in claimant_items}
        staff_ids = {item['evidence_id'] for item in staff_items}

        if set(declared) != scenario_ids:
            defects.append(
                PathDefect(
                    business_path=entry.business_path.value,
                    scenario_id=entry.scenario_id,
                    code='PATH_FIXTURE_NOT_ANCHORED',
                    expected=(
                        'the path entry describes the evidence of the canonical scenario '
                        f'it names: {sorted(scenario_ids) or "none"}'
                    ),
                    actual=f'the path entry declares unrelated records: {sorted(declared)}',
                    responsible_stack='evidence fixtures (bdfa123)',
                )
            )

        leaked = [
            item
            for item in claimant_items
            if item.get('source') in INTERNAL_SOURCES and item['evidence_id'] in scenario_ids
        ]
        if leaked:
            defects.append(
                PathDefect(
                    business_path=entry.business_path.value,
                    scenario_id=entry.scenario_id,
                    code='INTERNAL_EVIDENCE_VISIBLE_TO_CLAIMANT',
                    expected=(
                        'the claimant evidence list excludes records the claimant did not '
                        'provide and cannot act on'
                    ),
                    actual=(
                        'the claimant list returns '
                        + ', '.join(
                            f'{item["evidence_id"]} (kind={item["kind"]}, source={item["source"]})'
                            for item in leaked
                        )
                    ),
                    responsible_stack='evidence API and domain model (liyang6620, bdfa123)',
                )
            )

        if scenario_ids and staff_ids != scenario_ids:
            defects.append(
                PathDefect(
                    business_path=entry.business_path.value,
                    scenario_id=entry.scenario_id,
                    code='STAFF_PROJECTION_INCOMPLETE',
                    expected=f'staff see every persisted record: {sorted(scenario_ids)}',
                    actual=f'the Workbench returns {sorted(staff_ids)}',
                    responsible_stack='workbench projection (LLL263)',
                )
            )

        # Only meaningful once the entry describes the scenario's own records.
        # While PATH_FIXTURE_NOT_ANCHORED is open the two sets name different
        # universes, so comparing them would report noise rather than a defect.
        anchored = bool(scenario_ids) and set(declared) == scenario_ids
        if anchored and not leaked:
            unexpected, missing = compare_claimant_projection(declared_claimant, claimant_ids)
            if unexpected or missing:
                defects.append(
                    PathDefect(
                        business_path=entry.business_path.value,
                        scenario_id=entry.scenario_id,
                        code='CLAIMANT_PROJECTION_DIFFERS_FROM_DECLARED',
                        expected=f'the claimant sees exactly {sorted(declared_claimant)}',
                        actual=(
                            f'unexpected: {sorted(unexpected) or "none"}; '
                            f'missing: {sorted(missing) or "none"}'
                        ),
                        responsible_stack='evidence API (liyang6620)',
                    )
                )

    return defects


def describe(defects: list[PathDefect]) -> str:
    if not defects:
        return 'No evidence path defects found.'
    return '\n\n'.join(defect.render() for defect in defects)


def paths_checked(service: EvidenceFixtureService | None = None) -> int:
    resolved = service or EvidenceFixtureService()
    assert {entry.business_path for entry in resolved.path_entries()} == set(EvidenceBusinessPath)
    return len(resolved.path_entries())
