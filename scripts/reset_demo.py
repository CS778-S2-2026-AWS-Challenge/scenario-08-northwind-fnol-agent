import argparse
import json
import os
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = 'http://127.0.0.1:8000'
DEFAULT_STAFF_TOKEN = 'synthetic-staff'


class ResetCommandError(Exception):
    pass


def reset_demo(base_url: str, token: str, timeout: float = 10.0) -> dict[str, Any]:
    url = f'{base_url.rstrip("/")}/api/v1/workbench/demo/reset'
    request = Request(
        url,
        data=b'',
        method='POST',
        headers={'Authorization': f'Bearer {token}', 'Accept': 'application/json'},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')
        raise ResetCommandError(
            f'Backend rejected demo reset with HTTP {exc.code}: {detail}'
        ) from exc
    except URLError as exc:
        raise ResetCommandError(f'Could not reach the backend at {url}: {exc.reason}') from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResetCommandError('Backend returned an invalid demo reset response.') from exc

    if not isinstance(payload, dict) or payload.get('status') != 'reset':
        raise ResetCommandError('Backend did not confirm that demo state was reset.')
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Reset the running Northwind synthetic demo state.'
    )
    parser.add_argument(
        '--base-url',
        default=os.getenv('NORTHWIND_API_BASE_URL', DEFAULT_BASE_URL),
        help='Running backend base URL (default: %(default)s).',
    )
    parser.add_argument(
        '--staff-token',
        default=os.getenv('NORTHWIND_SYNTHETIC_STAFF_TOKEN', DEFAULT_STAFF_TOKEN),
        help='Synthetic staff token; defaults to the local development token.',
    )
    parser.add_argument('--timeout', type=float, default=10.0)
    args = parser.parse_args(argv)

    try:
        result = reset_demo(args.base_url, args.staff_token, args.timeout)
    except ResetCommandError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1

    print('Demo state reset successfully.')
    cleared = result.get('cleared', {})
    if isinstance(cleared, dict):
        for name, count in sorted(cleared.items()):
            print(f'  {name}: {count}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
