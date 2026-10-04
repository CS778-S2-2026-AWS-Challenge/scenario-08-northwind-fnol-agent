"""Provision the committed Workbench staff accounts and print their sign-in details.

Staff cannot register themselves and the Control Plane is not used to manage accounts, so
the Workbench is usable only through these seeded accounts. Every normal-identity start
provisions them from config/staff-seed.json (resetting an existing seeded account) and
prints the email and password of each, so the printed details always sign in.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from backend.repositories.staff_identity import StaffIdentityRepository

STAFF_SEED_PATH = 'config/staff-seed.json'


class StaffSeedAccount(BaseModel):
    model_config = ConfigDict(extra='forbid')

    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=1, max_length=120)
    roles: tuple[str, ...] = Field(min_length=1)


class StaffSeed(BaseModel):
    """The seeded accounts and the one password they all sign in with."""

    model_config = ConfigDict(extra='forbid')

    password: str = Field(min_length=1, max_length=256)
    accounts: tuple[StaffSeedAccount, ...] = Field(min_length=1)


def load_staff_seed(path: str | Path) -> StaffSeed:
    """Read the committed staff seed list."""

    return StaffSeed.model_validate(json.loads(Path(path).read_text(encoding='utf-8')))


def provision_staff_seed(repository: StaffIdentityRepository, seed: StaffSeed) -> None:
    """Create each seeded account, or reset it to the seed values when it exists."""

    for account in seed.accounts:
        repository.provision_account(
            account.email, seed.password, account.display_name, account.roles
        )


def staff_seed_banner(seed: StaffSeed) -> str:
    """Return the startup text listing each Workbench account and its password."""

    width = max(len(account.email) for account in seed.accounts)
    lines = [f'Workbench accounts ({STAFF_SEED_PATH}):']
    lines.extend(
        f'  {account.email.ljust(width)}  password: {seed.password}  '
        f'roles: {", ".join(account.roles)}'
        for account in seed.accounts
    )
    return '\n'.join(lines)
