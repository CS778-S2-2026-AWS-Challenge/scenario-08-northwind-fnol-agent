"""Bounded structural diagnostics for model-output validation failures."""

import re
from collections.abc import Iterable


def validation_path(errors: Iterable[object]) -> str | None:
    """Return the first structural path without exposing provider content.

    Args:
        errors: Pydantic validation details.
    Returns:
        A bounded field path, or None when no safe path exists.
    """

    first = next(iter(errors), None)
    if not isinstance(first, dict):
        return None
    location = first.get('loc')
    if not isinstance(location, tuple | list):
        return None
    if first.get('type') == 'extra_forbidden':
        location = location[:-1]
    parts: list[str] = []
    for item in location:
        if isinstance(item, int):
            parts.append(f'[{item}]')
        elif isinstance(item, str) and re.fullmatch(r'[A-Za-z0-9_-]+', item):
            parts.append(item)
        else:
            return None
    path = '.'.join(parts)
    return path if 0 < len(path) <= 120 else None
