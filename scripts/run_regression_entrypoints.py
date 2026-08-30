"""One cross-stack regression entry point for the canonical and provider checks (issue #281).

The repository has many individual check scripts. Some run entirely against fixtures
and prove repository behaviour; others require a configured external provider and
prove nothing at all unless that provider is actually present. Running them ad hoc
makes it easy to read a clean terminal as "everything works", which it is not.

This entry point separates the two tiers and refuses to blur them:

- **fixture-backed** checks are executed. They are repeatable by anyone with the
  repository and a Python environment, and a failure here is a real regression.
- **provider-backed** checks are *not* executed unless their configuration is present.
  They are reported as ``not executed`` together with the exact variable required, and
  never as passing. A provider check that did not run is not evidence.

Exit status is non-zero when a fixture-backed check fails. A provider-backed check that
was not executed does not fail the run, because absence of a local provider is not a
regression; it is reported so the gap stays visible.

Usage:
    python scripts/run_regression_entrypoints.py
    python scripts/run_regression_entrypoints.py --list
"""

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Check:
    name: str
    script: str
    stack: str
    proves: str


@dataclass(frozen=True)
class ProviderCheck:
    name: str
    script: str
    stack: str
    requires: str
    proves: str


FIXTURE_CHECKS: tuple[Check, ...] = (
    Check(
        name='canonical scenarios',
        script='run_scenarios.py',
        stack='Evidence',
        proves='every canonical scenario loads and seeds with a consistent claim state',
    ),
    Check(
        name='evidence lifecycle fixtures',
        script='run_evidence_fixtures.py',
        stack='Evidence',
        proves='each evidence stage keeps its declared source and visibility',
    ),
    Check(
        name='evidence business paths',
        script='run_evidence_paths.py',
        stack='Evidence',
        proves='each business path reaches its declared evidence state',
    ),
    Check(
        name='evidence path defects',
        script='run_evidence_path_defects.py',
        stack='Evidence',
        proves='no evidence-path defect across the five business paths',
    ),
    Check(
        name='path entry visibility',
        script='run_evidence_visibility_fixtures.py',
        stack='Evidence',
        proves='each path entry matches its workflow, action, evidence and handoff baseline',
    ),
    Check(
        name='agent runtime mapping',
        script='check_agent_runtime_mapping.py',
        stack='Agent runtime',
        proves='the documented agent runtime ledger matches the implemented values',
    ),
    Check(
        name='runtime profile composition',
        script='validate_runtime_profiles.py',
        stack='Data platform',
        proves='each runtime profile composes and reports its own readiness honestly',
    ),
)

PROVIDER_CHECKS: tuple[ProviderCheck, ...] = (
    ProviderCheck(
        name='MinIO object storage smoke',
        script='run_minio_fastapi_smoke.py',
        stack='Data platform',
        requires='NORTHWIND_OBJECT_STORAGE_ADAPTER=s3_compatible and a reachable MinIO endpoint',
        proves='object storage addressing and presigned access against a live S3-compatible store',
    ),
    ProviderCheck(
        name='MinIO/RAG provider failure',
        script='verify_minio_rag_provider_failure.py',
        stack='Data platform',
        requires='NORTHWIND_OBJECT_STORAGE_ADAPTER=s3_compatible and a reachable MinIO endpoint',
        proves='retrieval degrades explicitly when the object store is unavailable',
    ),
    ProviderCheck(
        name='knowledge retrieval query',
        script='query_knowledge.py',
        stack='Knowledge/RAG',
        requires='an ingested knowledge store and its configured adapter',
        proves='filtered retrieval returns citations from real ingested sources',
    ),
)


def _configured(check: ProviderCheck) -> bool:
    if 'NORTHWIND_OBJECT_STORAGE_ADAPTER=s3_compatible' in check.requires:
        return os.getenv('NORTHWIND_OBJECT_STORAGE_ADAPTER') == 's3_compatible'
    return False


def _run(script: str) -> tuple[int, str]:
    completed = subprocess.run(
        [sys.executable, str(REPOSITORY_ROOT / 'scripts' / script)],
        capture_output=True,
        text=True,
        cwd=REPOSITORY_ROOT,
        env={**os.environ, 'PYTHONPATH': str(REPOSITORY_ROOT)},
    )
    output = (completed.stdout or completed.stderr or '').strip().splitlines()
    return completed.returncode, output[-1] if output else ''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--list',
        action='store_true',
        help='describe every entry point and its tier without executing anything',
    )
    arguments = parser.parse_args()

    if arguments.list:
        print('Fixture-backed checks (executed; a failure is a real regression):')
        for check in FIXTURE_CHECKS:
            print(f'  {check.script:<38} [{check.stack}] {check.proves}')
        print('\nProvider-backed checks (executed only when configured; never assumed):')
        for provider in PROVIDER_CHECKS:
            print(f'  {provider.script:<38} [{provider.stack}] requires {provider.requires}')
        return 0

    failures: list[str] = []

    print('Fixture-backed checks')
    for check in FIXTURE_CHECKS:
        code, last_line = _run(check.script)
        status = 'PASS' if code == 0 else 'FAIL'
        print(f'  {status}  {check.name:<32} {last_line[:70]}')
        if code != 0:
            failures.append(f'{check.script} exited {code}')

    print('\nProvider-backed checks')
    executed = 0
    for provider in PROVIDER_CHECKS:
        if not _configured(provider):
            print(f'  NOT EXECUTED  {provider.name:<28} requires {provider.requires}')
            continue
        executed += 1
        code, last_line = _run(provider.script)
        status = 'PASS' if code == 0 else 'FAIL'
        print(f'  {status}  {provider.name:<32} {last_line[:70]}')
        if code != 0:
            failures.append(f'{provider.script} exited {code}')

    print(
        f'\n{len(FIXTURE_CHECKS)} fixture-backed checks executed, '
        f'{executed} of {len(PROVIDER_CHECKS)} provider-backed checks executed.'
    )
    if executed < len(PROVIDER_CHECKS):
        print(
            'Provider-backed capability is NOT demonstrated by this run. A check that did not '
            'execute is not evidence; report those capabilities as unavailable or '
            'fixture-dependent rather than verified.'
        )
    if failures:
        print('\nFailures:')
        for failure in failures:
            print(f'  - {failure}')
        return 1
    print('No fixture-backed regression detected.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
