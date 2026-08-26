import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.repositories.mongodb import (
    MongoDBConnectionConfig,
    probe_mongodb_connectivity,
)
from scripts.check_runtime_profile import (
    inspect_environment,
    inspect_runtime,
    load_environment_example,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / 'deploy' / 'runtime'


def _runtime_result(filename: str) -> dict[str, object]:
    result, _ = inspect_runtime(EXAMPLES / filename)
    return result


def _local_minio_result(endpoint: str | None) -> dict[str, object]:
    values = load_environment_example(EXAMPLES / 'local-minio.env.example')
    if endpoint is not None:
        values['NORTHWIND_OBJECT_STORAGE_ENDPOINT'] = endpoint
    result, _ = inspect_environment(values)
    return result


def _mongodb_connectivity(probe: bool) -> str:
    if not probe:
        return 'not_checked'
    try:
        return probe_mongodb_connectivity(MongoDBConnectionConfig.from_environment())
    except ValueError:
        return 'unavailable'


def build_validation_report(
    *, minio_endpoint: str | None = None, probe_mongodb: bool = False
) -> tuple[dict[str, object], bool]:
    fixture = _runtime_result('fixture.env.example')
    local_minio = _local_minio_result(minio_endpoint)
    mongodb = _runtime_result('mongodb.env.example')
    cloudflare = _runtime_result('cloudflare.env.example')
    aws = _runtime_result('aws.env.example')
    mongodb_connectivity = _mongodb_connectivity(probe_mongodb)
    candidate_refusal = all(
        item.get('status') == 'startup_refused' for item in (mongodb, cloudflare, aws)
    )

    report: dict[str, object] = {
        'profiles': {
            'fixture': {
                'classification': (
                    'verified' if fixture.get('status') == 'startup_ready' else 'unavailable'
                ),
                'startup': fixture,
            },
            'local_minio': {
                'classification': (
                    'verified' if local_minio.get('status') == 'startup_ready' else 'unavailable'
                ),
                'startup': local_minio,
                'scope': 'fixture data bundle with explicit S3-compatible evidence storage',
            },
            'mongodb': {
                'classification': 'partial',
                'startup': mongodb,
                'connectivity': mongodb_connectivity,
                'scope': 'connection foundation only; complete runtime bundle is unavailable',
            },
            'cloudflare': {
                'classification': 'unavailable',
                'startup': cloudflare,
            },
            'aws': {
                'classification': 'unavailable',
                'startup': aws,
            },
        },
        'isolation': 'verified_fail_closed' if candidate_refusal else 'failed',
    }
    expected = fixture.get('status') == 'startup_ready' and candidate_refusal
    if minio_endpoint is not None:
        expected = expected and local_minio.get('status') == 'startup_ready'
    return report, expected


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Classify Northwind runtime profiles without printing provider secrets.'
    )
    parser.add_argument(
        '--minio-endpoint',
        help='Override only the local MinIO endpoint, for example http://localhost:9000.',
    )
    parser.add_argument(
        '--probe-mongodb',
        action='store_true',
        help='Probe MongoDB from NORTHWIND_MONGODB_* process settings; values are never printed.',
    )
    arguments = parser.parse_args()
    if arguments.minio_endpoint and '@' in arguments.minio_endpoint:
        raise SystemExit('The MinIO endpoint must not contain user-info credentials.')
    report, expected = build_validation_report(
        minio_endpoint=arguments.minio_endpoint,
        probe_mongodb=arguments.probe_mongodb,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if expected else 2)


if __name__ == '__main__':
    main()
