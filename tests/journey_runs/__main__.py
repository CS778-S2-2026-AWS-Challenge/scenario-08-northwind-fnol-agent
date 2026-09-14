"""Run journeys into an output directory: `python -m tests.journey_runs --runs 10 --out DIR`.

Each run writes one `<run_id>.json` record. Records are evidence of a run, not fixtures, so
write them outside the repository and summarise them on the delivery issue.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .motor_collision import current_head, run_motor_collision
from .record import JourneyRunRecord


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=int, default=1)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--schema', action='store_true', help='print the record JSON Schema')
    arguments = parser.parse_args(argv)
    if arguments.schema:
        print(json.dumps(JourneyRunRecord.model_json_schema(), indent=2))
        return 0
    if arguments.out is None:
        parser.error('--out is required unless --schema is given')
    arguments.out.mkdir(parents=True, exist_ok=True)
    head = current_head()
    classes: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    for _ in range(arguments.runs):
        record = run_motor_collision(head=head)
        (arguments.out / f'{record.run_id}.json').write_text(
            record.model_dump_json(indent=2), encoding='utf-8'
        )
        classes[record.result_class.value] += 1
        reasons[record.result_reason] += 1
    print(f'head {head}: {arguments.runs} run(s) written to {arguments.out}')
    for result_class, count in classes.most_common():
        print(f'  {result_class}: {count}')
    for reason, count in reasons.most_common():
        print(f'  [{count}] {reason}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
