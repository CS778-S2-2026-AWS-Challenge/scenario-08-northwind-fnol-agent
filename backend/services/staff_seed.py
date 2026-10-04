"""Provision the committed Workbench staff accounts and print their sign-in details.

Staff cannot register themselves and the Control Plane is not used to manage accounts, so
the Workbench is usable only through these seeded accounts. Every start provisions them
with NORTHWIND_STAFF_SEED_PASSWORD (resetting the password of an existing seeded account)
and prints the email and password of each, so the printed details always sign in.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from backend.repositories.staff_identity import StaffIdentityRepository


class StaffSeedAccount(BaseModel):
    model_config = ConfigDict(extra='forbid')

    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=1, max_length=120)
    roles: tuple[str, ...] = Field(min_length=1)


_SEED_ADAPTER = TypeAdapter(list[StaffSeedAccount])


def load_staff_seed(path: str | Path) -> list[StaffSeedAccount]:
    """Read the committed staff seed list."""

    accounts = _SEED_ADAPTER.validate_python(json.loads(Path(path).read_text(encoding='utf-8')))
    if not accounts:
        raise ValueError(f'The staff seed list {path} contains no accounts.')
    return accounts


def provision_staff_seed(
    repository: StaffIdentityRepository,
    accounts: list[StaffSeedAccount],
    password: str,
) -> None:
    """Create each seeded account, or reset it to the seed values when it exists."""

    for account in accounts:
        repository.provision_account(account.email, password, account.display_name, account.roles)


def staff_seed_banner(accounts: list[StaffSeedAccount], password: str) -> str:
    """Return the startup text listing each Workbench account and its password."""

    width = max(len(account.email) for account in accounts)
    lines = ['Workbench accounts (config/staff-seed.json):']
    lines.extend(
        f'  {account.email.ljust(width)}  password: {password}  roles: {", ".join(account.roles)}'
        for account in accounts
    )
    return '\n'.join(lines)
