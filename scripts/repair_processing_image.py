"""Preview or apply readiness validation to one explicitly selected stored image."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.config import DataRuntimeProfile, Settings
from backend.core.errors import ApiError
from backend.core.runtime_profiles import build_data_runtime_bundle
from backend.services import evidence


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError('Must be a positive integer.')
    return parsed


def _identifier(value: str) -> str:
    if not value.strip():
        raise argparse.ArgumentTypeError('An explicit non-empty identifier is required.')
    return value.strip()


def main(argv: Sequence[str] | None = None) -> int:
    """Run one operator-authorized repair using the configured persistent providers.

    Args:
        argv: Command arguments, or the process arguments when omitted.
    Returns:
        Zero for a completed preview/apply; one for a refused or failed operation.
    Raises:
        SystemExit: When argparse handles help or rejects incomplete arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--claim-id', required=True, type=_identifier)
    parser.add_argument('--evidence-id', required=True, type=_identifier)
    parser.add_argument('--revision', required=True, type=_positive_integer)
    parser.add_argument('--material-version', required=True, type=_positive_integer)
    parser.add_argument(
        '--apply', action='store_true', help='Persist the result; omitted means dry-run.'
    )
    arguments = parser.parse_args(argv)
    try:
        settings = Settings.from_environment()
        if settings.data_runtime_profile is DataRuntimeProfile.FIXTURE:
            print(
                'Repair refused: configure the persistent runtime used by the backend.',
                file=sys.stderr,
            )
            return 1
        bundle = build_data_runtime_bundle(settings)
        try:
            result = evidence.repair_processing_image(
                bundle.repository,
                bundle.evidence_storage,
                claim_id=arguments.claim_id,
                evidence_id=arguments.evidence_id,
                expected_revision=arguments.revision,
                material_version=arguments.material_version,
                apply=arguments.apply,
            )
        finally:
            bundle.close()
    except ApiError as error:
        print(
            json.dumps(
                {
                    'error': error.code,
                    'retryable': error.retryable,
                    'current_revision': error.current_revision,
                }
            ),
            file=sys.stderr,
        )
        return 1
    except Exception:
        # This operator boundary must not expose provider credentials or stored PII.
        print(
            'Repair failed: verify runtime configuration and provider availability.',
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                'mode': 'applied' if arguments.apply else 'dry-run',
                'file_status': result.evidence.file_status.value,
                'revision': result.revision,
            }
        )
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
