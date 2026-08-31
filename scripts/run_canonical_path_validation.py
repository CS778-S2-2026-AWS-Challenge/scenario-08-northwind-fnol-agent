"""Repeatable Day-4 validation of the five canonical MVP business paths (issue #271).

For each canonical scenario assigned to an MVP business path this seeds a fresh
fixture repository, then reads the claim through the public claimant API and the
authorised Workbench API and compares the two projections.

It complements the existing runners rather than repeating them:

- ``run_evidence_visibility_fixtures.py`` checks each path's declared entry baseline;
- ``run_evidence_path_defects.py`` checks evidence-path defects;
- this script checks that staff see the complete canonical record set while no
  internal identifier reaches the claimant.

Three identifier classes must never appear in a claimant response: retrieval record
ids, ``internal_only`` message ids, and the id of a handoff that carries no
``support_need``. The last distinction is deliberate. ``ClaimantHandoff`` is a
customer-safe projection of a support request the claimant made themselves, so its
id is exposed on purpose, and ``claimant_handoff()`` raises rather than project an
internal routing handoff. AT-02 exercises the internal case and AT-04/AT-05 the
claimant-requested case.

All records are synthetic. This proves projection boundaries against the fixture
repository; it is not evidence of live provider behaviour.

Usage:
    python scripts/run_canonical_path_validation.py
"""

import sys
from pathlib import Path

from fastapi.testclient import TestClient

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.app import create_app  # noqa: E402
from backend.core.config import IdentityMode, Settings  # noqa: E402
from backend.repositories.fixture import FixtureRepository  # noqa: E402
from backend.repositories.scenario_loader import (  # noqa: E402
    CANONICAL_SCENARIO_DIRECTORY,
    load_mvp_journey_scenarios,
    seed_scenario,
)

CLAIMANT_AUTH = {'Authorization': 'Bearer synthetic-claimant'}
STAFF_AUTH = {'Authorization': 'Bearer synthetic-staff'}
DEVELOPER_SETTINGS = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)


def main() -> int:
    failures: list[str] = []
    rows: list[tuple[str, ...]] = []

    for scenario in load_mvp_journey_scenarios(CANONICAL_SCENARIO_DIRECTORY):
        repository = FixtureRepository()
        seed_scenario(repository, scenario)
        claim_id = scenario.claim.claim_id
        session_id = scenario.claim.active_session_id

        with TestClient(create_app(DEVELOPER_SETTINGS, repository)) as client:
            claim = client.get(f'/api/v1/claims/{claim_id}', headers=CLAIMANT_AUTH)
            evidence = client.get(f'/api/v1/claims/{claim_id}/evidence', headers=CLAIMANT_AUTH)
            messages = client.get(
                f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
                headers=CLAIMANT_AUTH,
            )
            detail = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=STAFF_AUTH)

        scenario_id = scenario.scenario_id
        for name, response in (
            ('claimant claim', claim),
            ('claimant evidence', evidence),
            ('claimant messages', messages),
            ('staff detail', detail),
        ):
            if response.status_code != 200:
                failures.append(f'{scenario_id}: {name} returned {response.status_code}')

        claimant_text = claim.text + evidence.text + messages.text
        staff = detail.json()

        internal_ids = [record.retrieval_id for record in scenario.retrievals]
        internal_ids += [
            message.message_id
            for message in scenario.messages
            if message.visibility.value == 'internal_only'
        ]
        internal_ids += [
            handoff.handoff_id for handoff in scenario.handoffs if handoff.support_need is None
        ]
        leaked = sorted({identifier for identifier in internal_ids if identifier in claimant_text})
        if leaked:
            failures.append(f'{scenario_id}: internal identifiers reached the claimant: {leaked}')

        own_requests = [
            handoff.handoff_id for handoff in scenario.handoffs if handoff.support_need is not None
        ]
        missing = [identifier for identifier in own_requests if identifier not in claimant_text]
        if missing:
            failures.append(
                f'{scenario_id}: the claimant cannot see their own support request {missing}'
            )

        staff_evidence = len(staff.get('evidence', []))
        if staff_evidence != len(scenario.evidence):
            failures.append(
                f'{scenario_id}: staff evidence {staff_evidence} does not match the '
                f'canonical {len(scenario.evidence)}'
            )

        rows.append(
            (
                scenario_id,
                scenario.business_path.value,
                f'{len(evidence.json().get("items", []))} / {staff_evidence}',
                f'{len(staff.get("retrievals", []))} / {len(staff.get("handoffs", []))}',
                f'{len(own_requests)} / {len(internal_ids)}',
            )
        )

    header = (
        'scenario',
        'business path',
        'claimant/staff evidence',
        'staff ret/handoff',
        'own/internal ids',
    )
    widths = [max(len(header[i]), *(len(row[i]) for row in rows)) + 2 for i in range(len(header))]
    print(''.join(text.ljust(width) for text, width in zip(header, widths, strict=True)))
    for row in rows:
        print(''.join(text.ljust(width) for text, width in zip(row, widths, strict=True)))

    print(f'\nChecked {len(rows)} business paths.')
    if failures:
        print('Projection defects found:')
        for failure in failures:
            print(f'  - {failure}')
        return 1
    print(
        'No projection defects found: staff see the complete canonical set and no internal '
        'identifier reaches the claimant.'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
