"""Open, or comment on, the GitHub issue that tracks a failing full backend suite.

CircleCI runs this from the full-suite job on ``main`` and on the daily schedule when the
job fails. One open issue collects every failure until someone fixes ``main`` and closes it.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request

TITLE = 'Full backend suite fails on main'
API = 'https://api.github.com'


def issue_body(*, commit: str, build_url: str, trigger: str) -> str:
    """Return an issue body that satisfies the repository issue policy."""

    return f"""### Issue type

Regression validation

### Problem or reason

The full backend suite failed on `{commit}` ({trigger}). Failing job: {build_url}

Pull requests run only the tests that cover their changed lines, so a test broken by an
earlier merge can stay hidden until this run.

### Deliverable

Make the failing tests pass on `main`, or mark a test for a known product defect as
`xfail(strict=True)` with its issue.

### Acceptance criteria

- [ ] The next full backend suite run on `main` passes.

### Related issue or PR

#1191

### Dependencies

None

### Owned behavior

Whichever behaviour the failing tests cover.

### Expected impact area

The failing tests and the code they exercise; see the failing job.

### Non-goals

None - this issue only restores a passing full suite.

### Shared contracts

None

### Risk class

Standard

### Owner or responsible contributor

Author of the merge that introduced the failure; the maintainer assigns it otherwise.
"""


def _request(method: str, path: str, token: str, payload: object | None = None) -> object:
    request = urllib.request.Request(
        f'{API}{path}',
        method=method,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={
            'Accept': 'application/vnd.github+json',
            'Authorization': f'Bearer {token}',
            'User-Agent': 'northwind-full-suite-report',
            'X-GitHub-Api-Version': '2022-11-28',
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read() or b'null')


def report(repository: str, token: str, *, commit: str, build_url: str, trigger: str) -> str:
    """Comment on the open tracking issue, or open one; return the issue URL."""

    found = _request('GET', f'/repos/{repository}/issues?state=open&per_page=100', token)
    assert isinstance(found, list)
    existing = [item for item in found if item.get('title') == TITLE and 'pull_request' not in item]
    if existing:
        number = existing[0]['number']
        _request(
            'POST',
            f'/repos/{repository}/issues/{number}/comments',
            token,
            {'body': f'Failed again on `{commit}` ({trigger}): {build_url}'},
        )
        return str(existing[0]['html_url'])
    created = _request(
        'POST',
        f'/repos/{repository}/issues',
        token,
        {'title': TITLE, 'body': issue_body(commit=commit, build_url=build_url, trigger=trigger)},
    )
    assert isinstance(created, dict)
    return str(created['html_url'])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trigger', required=True, help='for example "merge to main"')
    parser.add_argument('--dry-run', action='store_true', help='print the issue body only')
    args = parser.parse_args()
    commit = os.environ.get('CIRCLE_SHA1', 'unknown')
    build_url = os.environ.get('CIRCLE_BUILD_URL', 'unknown')
    if args.dry_run:
        print(issue_body(commit=commit, build_url=build_url, trigger=args.trigger))
        return 0
    # Parallel shards can fail together; stagger them so one opens the issue and the
    # others comment on it.
    time.sleep(20 * int(os.environ.get('CIRCLE_NODE_INDEX', '0')))
    repository = f'{os.environ["CIRCLE_PROJECT_USERNAME"]}/{os.environ["CIRCLE_PROJECT_REPONAME"]}'
    print(
        report(
            repository,
            os.environ['GITHUB_TOKEN'],
            commit=commit,
            build_url=build_url,
            trigger=args.trigger,
        )
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
