"""Reset and seed the local start-dev stores for a controlled-corpus run (#1222).

Every full run starts from empty stores, because the journeys lodge real Claims and those
become the customers' history: a second run on the same data would count the first run's
Claims as earlier claims.

    python tests/corpus/runner/corpus_store.py reset
        Drops the start-dev MongoDB database and deletes the claimant identity file. The backend
        must be stopped first: start-dev provisions the packaged seed and the staff accounts
        again when it starts.

    python tests/corpus/runner/corpus_store.py seed <manifest.json>
        Provisions a manifest from ``runner.cjs seed``. This adds nothing of its own:
        ``load_business_seed`` from #1221 validates it, and ``provision_business_identities``,
        ``provision_business_policies`` and ``provision_business_claims`` insert the records
        that are absent, leaving existing ones untouched.

Run from the repository root with the backend's ``NORTHWIND_MONGODB_*`` settings. Both
commands refuse a MongoDB that is not on this machine.
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pymongo import MongoClient

from backend.adapters.identity import SQLiteIdentityRepository
from backend.repositories.mongodb import MongoDBConnectionConfig, connect_mongodb_repository
from backend.services.business_seed import (
    load_business_seed,
    provision_business_claims,
    provision_business_identities,
    provision_business_policies,
)

LOCAL_HOSTS = {'localhost', '127.0.0.1', '::1', '[::1]'}


def mongodb_hosts(uri: str) -> list[str]:
    """Return the host names in a MongoDB connection string, without ports or credentials."""
    hosts = urlsplit(uri).netloc.rsplit('@', 1)[-1]
    return [host.rsplit(':', 1)[0] if not host.endswith(']') else host for host in hosts.split(',')]


def local_mongodb() -> MongoDBConnectionConfig:
    config = MongoDBConnectionConfig.from_environment()
    hosts = mongodb_hosts(config.uri)
    if not hosts or any(host not in LOCAL_HOSTS for host in hosts):
        raise SystemExit(f'refusing a MongoDB that is not local: {", ".join(hosts)}')
    return config


def identity_path() -> Path:
    return Path(os.getenv('NORTHWIND_IDENTITY_DB_PATH', '.northwind-identity.sqlite3'))


def backend_answers(api_url: str) -> bool:
    try:
        with urllib.request.urlopen(f'{api_url}/health/ready', timeout=3):
            return True
    except urllib.error.HTTPError:
        return True
    except OSError:
        return False


def reset() -> int:
    config = local_mongodb()
    api_url = os.getenv('NORTHWIND_API_URL', 'http://127.0.0.1:8000')
    if backend_answers(api_url):
        raise SystemExit(f'the backend at {api_url} is running; stop it before a reset')
    client: MongoClient[Any] = MongoClient(
        config.uri, serverSelectionTimeoutMS=config.server_selection_timeout_ms
    )
    try:
        client.drop_database(config.database_name)
    finally:
        client.close()
    path = identity_path()
    path.unlink(missing_ok=True)
    print(f'dropped MongoDB database {config.database_name} and removed {path}')
    return 0


def seed(manifest: str) -> int:
    business_seed = load_business_seed(manifest)
    config = local_mongodb()
    repository = connect_mongodb_repository(config)
    provision_business_identities(SQLiteIdentityRepository(str(identity_path())), business_seed)
    provision_business_policies(repository, business_seed)
    provision_business_claims(repository, business_seed)
    print(
        f'seeded {len(business_seed.customers)} customers, '
        f'{len(business_seed.policies_in_system)} policies and '
        f'{len(business_seed.prior_submitted_claims)} earlier claims into {config.database_name}'
    )
    return 0


def main(argv: list[str]) -> int:
    if argv[1:2] == ['reset'] and len(argv) == 2:
        return reset()
    if argv[1:2] == ['seed'] and len(argv) == 3:
        return seed(argv[2])
    print('usage: corpus_store.py reset | seed <manifest.json>', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
