from hashlib import sha256
from secrets import token_hex


def new_id(prefix: str) -> str:
    return f'{prefix}_{token_hex(10)}'


def stable_operation_id(prefix: str, identity: str) -> str:
    """Preserve a durable operation identity across replay and worker restart.

    The v1 24-digit digest is retained for existing P17 and retention records.
    Inputs contain authoritative coordinates, never retry wall-clock time.
    """
    return f'{prefix}_{sha256(identity.encode()).hexdigest()[:24]}'
