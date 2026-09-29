"""Run one bounded P17 recovery worker cycle against the configured data profile."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime

from backend.core.config import Settings
from backend.core.runtime_profiles import build_data_runtime_bundle
from backend.services.recovery_worker import run_recovery_cycle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--limit',
        type=int,
        default=50,
        help='maximum due and expiry candidates processed in this cycle (1-100)',
    )
    args = parser.parse_args()

    settings = Settings.from_environment()
    bundle = build_data_runtime_bundle(settings)
    try:
        result = run_recovery_cycle(
            bundle.repository,
            bundle.evidence_storage,
            now=datetime.now(UTC),
            limit=args.limit,
        )
        print(json.dumps(asdict(result), sort_keys=True))
    finally:
        bundle.close()

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
