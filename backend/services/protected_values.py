"""Authenticated encryption boundary for separately protected account values."""

import base64
import os
from hashlib import sha256
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken


class ProtectedValueError(ValueError):
    """A protected value cannot be sealed or resolved by the configured adapter."""


class ProtectedValueAdapter(Protocol):
    def seal(self, value: str) -> str: ...

    def resolve(self, protected_value: str) -> str: ...


class FernetProtectedValueAdapter:
    def __init__(self, key: bytes) -> None:
        try:
            self._fernet = Fernet(key)
        except (TypeError, ValueError) as error:
            raise ProtectedValueError('The protected-data key is invalid.') from error

    def seal(self, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ProtectedValueError('A protected value cannot be empty.')
        return self._fernet.encrypt(normalized.encode()).decode()

    def resolve(self, protected_value: str) -> str:
        try:
            return self._fernet.decrypt(protected_value.encode()).decode()
        except (InvalidToken, UnicodeError) as error:
            raise ProtectedValueError('The protected value could not be resolved.') from error


class UnavailableProtectedValueAdapter:
    """Fail-closed adapter used when a non-development key has not been configured."""

    def seal(self, value: str) -> str:
        del value
        raise ProtectedValueError('Protected account data is not configured.')

    def resolve(self, protected_value: str) -> str:
        del protected_value
        raise ProtectedValueError('Protected account data is not configured.')


def protected_value_adapter_for(environment: str) -> ProtectedValueAdapter:
    configured = os.getenv('NORTHWIND_PROTECTED_DATA_KEY', '').strip()
    if configured:
        return FernetProtectedValueAdapter(configured.encode())
    if environment in {'development', 'test'}:
        # Synthetic-only key keeps local persistence restart-safe without a checked-in secret.
        digest = sha256(b'northwind-synthetic-protected-data-v1').digest()
        return FernetProtectedValueAdapter(base64.urlsafe_b64encode(digest))
    return UnavailableProtectedValueAdapter()


def masked_value(value: str) -> str:
    compact = ''.join(character for character in value.strip() if character.isalnum())
    suffix = compact[-4:]
    return f'****{suffix}'
