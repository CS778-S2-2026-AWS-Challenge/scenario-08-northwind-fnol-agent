from hashlib import sha256
from secrets import token_hex


def new_id(prefix: str) -> str:
    return f'{prefix}_{token_hex(10)}'


def stable_digest(material: str, length: int = 24) -> str:
    """Return the deterministic hex digest used by replay-stable identities.

    Args:
        material: Authoritative coordinates that uniquely identify the record.
            Never include retry wall-clock time.
        length: Number of hex digits kept from the SHA-256 digest.

    Returns:
        The truncated digest. Equal material and length always yield the same value.

    Raises:
        ValueError: If ``length`` is outside 16-64 digits.
    """
    if not 16 <= length <= 64:
        raise ValueError('Stable identity digests keep 16 to 64 hex digits.')
    return sha256(material.encode()).hexdigest()[:length]


def stable_operation_id(prefix: str, identity: str) -> str:
    """Preserve a durable operation identity across replay and worker restart.

    The v1 24-digit digest is retained for existing P17 and retention records.
    Inputs contain authoritative coordinates, never retry wall-clock time.
    """
    return f'{prefix}_{stable_digest(identity)}'


def stable_record_id(prefix: str, material: str) -> str:
    """Return a deterministic 32-digit identity for an append-only record.

    Args:
        prefix: Registered record prefix from `docs/persistence-schema.md`.
        material: Authoritative coordinates that uniquely identify the record.

    Returns:
        The prefixed identity. Equal material always yields the same identity.
    """
    return f'{prefix}_{stable_digest(material, 32)}'
