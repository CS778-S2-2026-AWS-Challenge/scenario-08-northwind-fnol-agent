"""Run journeys into an output directory.

    python -m tests.journey_runs --scenario motor --runs 50 --out DIR
    python -m tests.journey_runs --scenario home --runs 30 --out DIR
    python -m tests.journey_runs --scenario contents --runs 20 --out DIR

Each run writes one `<run_id>.json` record. Records are evidence of a run, not fixtures, so
write them outside the repository and summarise them on the delivery issue.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .engine import current_head
from .household import (
    SCENARIOS,
    HouseholdScenario,
    household_run_cases,
    household_scenario_cases,
    run_household,
)
from .motor_collision import (
    MOTOR_JOURNEY_FIXTURES,
    MotorRunCase,
    motor_run_cases,
    run_motor_journey,
)
from .record import JourneyRunRecord

_MOTOR_CHOICES = ['motor', *[f'motor:{name}' for name in MOTOR_JOURNEY_FIXTURES]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', choices=[*_MOTOR_CHOICES, *SCENARIOS], default='motor')
    parser.add_argument('--runs', type=int, default=1)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--schema', action='store_true', help='print the record JSON Schema')
    arguments = parser.parse_args(argv)
    if arguments.schema:
        print(json.dumps(JourneyRunRecord.model_json_schema(), indent=2))
        return 0
    if arguments.out is None:
        parser.error('--out is required unless --schema is given')
    if arguments.runs < 1:
        parser.error('--runs must be at least 1')
    arguments.out.mkdir(parents=True, exist_ok=True)
    head = current_head()
    classes: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    if arguments.scenario == 'motor' or arguments.scenario.startswith('motor:'):
        fixture_name = arguments.scenario.split(':', 1)[1] if ':' in arguments.scenario else None
        cases: tuple[MotorRunCase | HouseholdScenario, ...] = motor_run_cases(fixture_name)
    elif arguments.scenario in {'home', 'contents'}:
        cases = household_run_cases(arguments.scenario)
    else:
        cases = household_scenario_cases(SCENARIOS[arguments.scenario])
    if arguments.runs > len(cases):
        parser.error(
            f'--runs {arguments.runs} exceeds the {len(cases)} unique cases available '
            f'for {arguments.scenario}'
        )

    for case in cases[: arguments.runs]:
        if isinstance(case, MotorRunCase):
            record = run_motor_journey(
                case.fixture_name,
                head=head,
                pack=case.pack,
                pack_id=case.pack_id,
                input_variant=case.input_variant,
            )
        else:
            record = run_household(case, head=head).record
        (arguments.out / f'{record.run_id}.json').write_text(
            record.model_dump_json(indent=2), encoding='utf-8'
        )
        classes[record.result_class.value] += 1
        reasons[record.result_reason] += 1
    print(f'head {head}: {arguments.runs} {arguments.scenario} run(s) written to {arguments.out}')
    for result_class, count in classes.most_common():
        print(f'  {result_class}: {count}')
    for reason, count in reasons.most_common():
        print(f'  [{count}] {reason}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
