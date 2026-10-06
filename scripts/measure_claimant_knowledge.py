"""Measure synthetic claimant clause selection through the normal HTTP message API.

Stimuli use registration, login, claim creation and messages only. Internal evidence
is read from MongoDB because claimant APIs deliberately hide Runtime traces. This
script never writes MongoDB, changes infrastructure, or supplies model replies.
"""

import argparse
import json
import os
import re
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


def values_named(value: Any, key: str) -> list[Any]:
    """Find matching evidence fields in a JSON tree.

    Args:
        value: JSON-compatible evidence subtree.
        key: Field name to collect.

    Returns:
        Values associated with that name, including nested occurrences.
    """
    result: list[Any] = []
    if isinstance(value, dict):
        if key in value:
            result.append(value[key])
        for child in value.values():
            result.extend(values_named(child, key))
    elif isinstance(value, list):
        for child in value:
            result.extend(values_named(child, key))
    return result


def http(
    base: str,
    method: str,
    path: str,
    payload: Any = None,
    token: str = '',
    revision: int | None = None,
) -> dict[str, Any]:
    """Send one authenticated JSON request without exposing credentials.

    Args:
        base: Backend origin.
        method: HTTP method.
        path: API route.
        payload: Optional JSON body.
        token: Claimant bearer token.
        revision: Current claim revision for optimistic concurrency.

    Returns:
        Decoded JSON response.
    """
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    if method == 'POST':
        headers['Idempotency-Key'] = uuid4().hex
    if revision is not None:
        headers['If-Match'] = str(revision)
    request = Request(
        base.rstrip('/') + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=180) as response:
            result: dict[str, Any] = json.load(response)
            return result
    except HTTPError as error:
        # Never include response bodies, request headers or credentials in errors.
        try:
            code = json.load(error).get('error', {}).get('code')
        except (ValueError, AttributeError):
            code = None
        raise RuntimeError(f'{method} {path}: HTTP {error.code}, code={code}') from None


def arguments() -> argparse.Namespace:
    """Parse measurement controls.

    Returns:
        Validated command-line arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument(
        '--cases', type=Path, default=Path('config/claimant-knowledge-evaluation-cases.json')
    )
    parser.add_argument(
        '--output',
        type=Path,
        required=True,
        help='Untracked report directory, e.g. var/knowledge-measurement',
    )
    parser.add_argument(
        '--scenario',
        choices=['inventory', 'included', 'excluded', 'no-clause', 'unavailable'],
        default='inventory',
    )
    parser.add_argument('--case', help='Run one inventory case ID')
    parser.add_argument('--model-profile-id', help='Published claimant model profile to measure')
    parser.add_argument(
        '--repeats', type=int, help='Defaults to 1 for inventory, 5 for motor paths'
    )
    parser.add_argument('--motor-policy', default='NW-MTR-204518')
    parser.add_argument('--excluded-motor-policy', default='NW-MTR-204519')
    parser.add_argument('--home-policy', default='NW-HOM-204518')
    parser.add_argument('--contents-policy', default='NW-CON-204518')
    return parser.parse_args()


def main() -> int:
    """Run API scenarios and write local measurement evidence.

    Returns:
        Zero for completed requests, one if any run had an operational error.
        Retrieval misses remain report data rather than a transport failure.
    """
    args = arguments()
    from pymongo import MongoClient

    uri = os.environ.get('NORTHWIND_MONGODB_URI')
    database = os.environ.get('NORTHWIND_MONGODB_DATABASE')
    if not uri or not database:
        raise RuntimeError(
            'NORTHWIND_MONGODB_URI and NORTHWIND_MONGODB_DATABASE '
            'are required for read-only evidence'
        )
    repeats = (
        args.repeats if args.repeats is not None else (1 if args.scenario == 'inventory' else 5)
    )
    if repeats < 1:
        raise RuntimeError('--repeats must be positive')
    cases = json.loads(args.cases.read_text(encoding='utf-8'))['cases']
    if args.scenario != 'inventory':
        cases = [
            {
                'id': args.scenario,
                'product': 'motor',
                'question': (
                    'Does this policy pay for my pet parrot to attend university?'
                    if args.scenario == 'no-clause'
                    else 'Will my policy pay for a rental car while mine is repaired?'
                ),
                'expected': [] if args.scenario in ('no-clause', 'unavailable') else ['MTR-BEN-03'],
            }
        ]
    elif args.case:
        cases = [case for case in cases if case['id'] == args.case]
    if not cases:
        raise RuntimeError('No matching evaluation cases')
    client: MongoClient[dict[str, Any]] = MongoClient(uri, serverSelectionTimeoutMS=5000)
    collection = client[database][
        os.environ.get('NORTHWIND_MONGODB_COLLECTION', 'northwind_records')
    ]
    client.admin.command('ping')
    run_id = uuid4().hex
    credentials = {
        'email': f'knowledge-{run_id}@example.invalid',
        'password': secrets.token_urlsafe(24),
    }
    http(
        args.base_url,
        'POST',
        '/api/v1/auth/accounts',
        {**credentials, 'display_name': 'Synthetic Knowledge Tester'},
    )
    auth = http(args.base_url, 'POST', '/api/v1/auth/sessions', credentials)
    token = auth['access_token']
    capabilities = http(args.base_url, 'GET', '/api/v1/claims/capabilities', token=token)
    available_models = {
        model['id'] for model in capabilities.get('models', []) if model.get('runtime_ready')
    }
    if not available_models:
        raise RuntimeError(
            'No ready real model: controlled or unavailable runtime cannot be measured'
        )
    if args.model_profile_id and args.model_profile_id not in available_models:
        raise RuntimeError('Requested model profile is not ready')
    policies = {
        'motor': args.motor_policy,
        'home': args.home_policy,
        'contents': args.contents_policy,
    }
    report: dict[str, Any] = {
        'run_id': run_id,
        'created_at': datetime.now(UTC).isoformat(),
        'scenario': args.scenario,
        'model_profile_id': args.model_profile_id or capabilities.get('default_model_profile_id'),
        'capabilities': capabilities,
        'runs': [],
    }
    source_directory = Path('config/knowledge-source-corpus')
    report['source_directory_snapshot'] = {}
    for product in policies:
        source = source_directory / f'northwind-{product}-standard-policy-2026.2.md'
        report['source_directory_snapshot'][product] = re.findall(
            r'^## ([A-Z]+-[A-Z]+-\d+) - (.+)$',
            source.read_text(encoding='utf-8'),
            re.MULTILINE,
        )
    args.output.mkdir(parents=True, exist_ok=True)
    for case in cases:
        for repeat in range(repeats):
            record: dict[str, Any] = {'case': case, 'repeat': repeat + 1}
            report['runs'].append(record)
            try:
                created = http(
                    args.base_url,
                    'POST',
                    '/api/v1/claims',
                    {'model_profile_id': args.model_profile_id} if args.model_profile_id else {},
                    token,
                )
                if created['session'].get('model_profile_id') == 'controlled':
                    raise RuntimeError('Controlled runtime cannot supply real-model evidence')
                claim_id, session_id = (
                    created['claim']['claim_id'],
                    created['session']['session_id'],
                )
                record['claim_id'] = claim_id
                policy = (
                    args.excluded_motor_policy
                    if args.scenario == 'excluded'
                    else policies[case['product']]
                )
                path = f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages'
                setup = (
                    f'This is a {case["product"]} insurance claim. My policy number is {policy}. '
                    'Nobody is hurt or in danger.'
                )
                incidents = {
                    'motor': 'My parked car was hit yesterday at 2pm '
                    'at 18 Synthetic Lane, Auckland. '
                    'The front bumper is damaged and it cannot be driven safely. '
                    'I am the policyholder and have not arranged repairs yet.',
                    'home': 'A pipe suddenly burst yesterday at 2pm at my insured home, '
                    '18 Synthetic Lane, Auckland. The kitchen floor is water damaged. '
                    'The water is turned off and we can safely stay at home.',
                    'contents': 'A shelf fell yesterday at 2pm at my insured home, '
                    '18 Synthetic Lane, Auckland, damaging my laptop screen. '
                    'I own the laptop and can provide a photo later.',
                }
                setup += ' ' + incidents[case['product']]
                first = http(
                    args.base_url,
                    'POST',
                    path,
                    {'client_message_id': uuid4().hex, 'content': {'type': 'text', 'text': setup}},
                    token,
                    created['claim']['revision'],
                )
                record['setup_response'] = first
                setup_form = first['current_claim']['form']
                record['setup_confirmed'] = all(
                    setup_form.get(field, {}).get('status') == 'confirmed'
                    for field in ('claim.product_family', 'policy.policy_number')
                )
                if not record['setup_confirmed']:
                    record['setup_failure'] = (first.get('recovery') or {}).get('rule_id')
                    raise RuntimeError('Setup did not confirm product and policy number')
                response = http(
                    args.base_url,
                    'POST',
                    path,
                    {
                        'client_message_id': uuid4().hex,
                        'content': {'type': 'text', 'text': case['question']},
                    },
                    token,
                    first['current_claim_revision'],
                )
                record['response'] = response
                trigger = response['claimant_message']['message_id']
                scope = {'claim_id': claim_id, 'customer_id': auth['customer_id']}
                trace = collection.find_one(
                    {**scope, 'record_type': 'runtime_trace', 'trigger_message_id': trigger},
                    {'_id': 0},
                )
                stored_messages = list(
                    collection.find({**scope, 'record_type': 'message'}, {'_id': 0})
                )
                record['trace'] = trace
                agent_id = (response.get('agent_message') or {}).get('message_id')
                agent_message: dict[str, Any] = next(
                    (
                        message
                        for message in stored_messages
                        if message.get('message_id') == agent_id
                    ),
                    {},
                )
                record['turn_records'] = values_named(agent_message, 'turn_record')
                record['requested'] = (
                    (trace or {})
                    .get('tool_output', {})
                    .get(
                        'requested_clause_ids',
                        (trace or {}).get('tool_arguments', {}).get('clause_ids', []),
                    )
                )
                record['returned'] = (
                    (trace or {}).get('tool_output', {}).get('returned_clause_ids', [])
                )
                cited = values_named(record['turn_records'], 'cited_clauses')
                cited_ids: set[str] = set()
                for group in cited:
                    for item in group:
                        if isinstance(item, dict):
                            identity = str(item.get('section_path', ''))
                            cited_ids.update(re.findall(r'(?:MTR|HOM|CON)-[A-Z]+-\d+', identity))
                record['cited'] = sorted(cited_ids)
                record['public_citations'] = values_named(response, 'cited_sources')
                record['fetch_hit'] = bool(case['expected']) and set(case['expected']).issubset(
                    record['returned']
                )
                record['cite_hit'] = bool(case['expected']) and set(case['expected']).issubset(
                    record['cited']
                )
                record['context_resolve_completed'] = (trace or {}).get(
                    'tool_name'
                ) == 'context.resolve'
                record['runtime_action_code'] = (trace or {}).get('runtime_action_code')
                record['runtime_reason_codes'] = (trace or {}).get('reason_codes', [])
                events = list(
                    collection.find({**scope, 'record_type': 'realtime_event'}, {'_id': 0})
                )
                client_message_id = response['claimant_message']['client_message_id']
                record['progress_events'] = [
                    event for event in events if client_message_id in values_named(event, 'turn_id')
                ]
                record['context_resolve_ran'] = record['context_resolve_completed'] or any(
                    event.get('progress', {}).get('stage') == 'tool.running'
                    and event.get('progress', {}).get('safe_activity_code') == 'context.resolve'
                    for event in record['progress_events']
                )
                record['miss_stage'] = (
                    'none'
                    if record['fetch_hit']
                    else 'runtime_rejected'
                    if (trace or {}).get('runtime_action_code') == 'runtime.fail_safe'
                    else 'lookup_not_invoked'
                    if not record['context_resolve_ran']
                    else 'selection_or_fetch'
                )
                record['knowledge_querying_emitted'] = any(
                    'knowledge.querying' in values_named(event, 'stage')
                    for event in record['progress_events']
                )
                record['reply_schedule_agreement'] = (
                    'requires human assessment of recorded reply and policy schedule'
                )
                record['directory_seen'] = (
                    (trace or {}).get('tool_output', {}).get('policy_clause_directory')
                )
                record['directory_evidence'] = (
                    'exact Runtime directory'
                    if record['directory_seen'] is not None
                    else 'no directory recorded; inspect routing before attributing a '
                    'selection miss'
                )
            except Exception as error:
                record['error'] = type(error).__name__ + (
                    f': {error}' if isinstance(error, RuntimeError) else ''
                )
            (args.output / 'results.json').write_text(
                json.dumps(report, indent=2, default=str) + '\n', encoding='utf-8'
            )
            print(
                f'case={case["id"]} repeat={repeat + 1} completed error={"error" in record}',
                flush=True,
            )
    lines = [
        '# Claimant knowledge measurement',
        '',
        f'Scenario: {args.scenario}. Run: {run_id}.',
        '',
        '| Product | Runs | Fetch hits | Citation hits |',
        '| --- | --- | --- | --- |',
    ]
    for product in policies:
        runs = [
            record
            for record in report['runs']
            if record['case']['product'] == product and record['case']['expected']
        ]
        if runs:
            lines.append(
                f'| {product} | {len(runs)} | '
                f'{sum(bool(r.get("fetch_hit")) for r in runs)}/{len(runs)} | '
                f'{sum(bool(r.get("cite_hit")) for r in runs)}/{len(runs)} |'
            )
    lines.extend(['', '## Misses and unverified evidence', ''])
    for record in report['runs']:
        if not record.get('fetch_hit') or not record.get('cite_hit'):
            lines.append(
                f'- {record["case"]["id"]} run {record["repeat"]}: '
                f'requested {record.get("requested")}; fetched {record.get("returned")}; '
                f'cited {record.get("cited")}; stage {record.get("miss_stage")}; '
                f'setup {record.get("setup_failure", "confirmed")}; '
                f'runtime {record.get("runtime_action_code", "not reached")} '
                f'{record.get("runtime_reason_codes", [])}; '
                f'error {record.get("error", "none")}.'
            )
    lines.append(
        '\nPersisted progress events and the Runtime directory actually supplied to lookup turns '
        'are recorded in JSON. Missing directories are explicit. '
        'Reply/schedule agreement requires assessment of the recorded replies.'
    )
    (args.output / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    client.close()
    return 1 if any('error' in record for record in report['runs']) else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f'Measurement failed: {type(error).__name__}', file=sys.stderr)
        raise SystemExit(1) from None
