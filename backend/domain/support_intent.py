"""Deterministic, provider-neutral classification of claimant support intent."""

from __future__ import annotations

import re
from enum import Enum

from backend.domain.models import SupportNeed


class SupportIntent(str, Enum):
    NONE = 'none'
    EXPLICIT_HUMAN_REQUEST = 'explicit_human_request'
    ACCESSIBILITY_NEED = 'accessibility_need'
    DISTRESS = 'distress'


_EXPLICIT_HUMAN_PATTERNS = (
    re.compile(
        r'\b(?:speak|talk)\s+(?:to|with)\s+(?:a\s+)?(?:person|human|representative)\b',
        re.IGNORECASE,
    ),
    re.compile(
        r'\b(?:want|need|request)\s+(?:a\s+)?(?:person|human|representative)\b',
        re.IGNORECASE,
    ),
    re.compile(r'\bhuman\s+(?:help|support)\b', re.IGNORECASE),
)
_NEGATED_HUMAN_PATTERNS = (
    re.compile(
        r"\b(?:do\s+not|don'?t|dont|no\s+longer)\s+(?:need|want|request)\s+"
        r'(?:to\s+)?(?:speak|talk)?\s*(?:to|with)?\s*(?:a\s+)?'
        r'(?:person|human|representative|human\s+(?:help|support))\b',
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:do\s+not|don'?t|dont)\s+need\s+human\s+(?:help|support)\b", re.I),
)
_ACCESSIBILITY_PATTERNS = (
    re.compile(
        r'\b(?:need|require|request)\s+(?:an?\s+)?'
        r'(?:interpreter|translator|accessibility\s+support|communication\s+assistance)\b',
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:i\s+am|i'?m)\s+(?:deaf|blind|hard\s+of\s+hearing)\b",
        re.IGNORECASE,
    ),
)
_NEGATED_ACCESSIBILITY_PATTERNS = (
    re.compile(
        r"\b(?:do\s+not|don'?t|dont|no\s+longer)\s+(?:need|require|request)\s+"
        r'(?:an?\s+)?(?:interpreter|translator|accessibility\s+support|'
        r'communication\s+assistance)\b',
        re.IGNORECASE,
    ),
)
_DISTRESS_PATTERNS = (
    re.compile(
        r"\b(?:i\s+am|i'?m|i\s+feel|i'?m\s+feeling)\s+"
        r'(?:overwhelmed|distressed|panicking|unable\s+to\s+cope)\b',
        re.IGNORECASE,
    ),
    re.compile(r"\bi\s+(?:cannot|can'?t|cant)\s+cope\b", re.IGNORECASE),
)
_NEGATED_DISTRESS_PATTERNS = (
    re.compile(
        r"\b(?:i\s+am|i'?m)\s+not\s+(?:overwhelmed|distressed|panicking)\b",
        re.IGNORECASE,
    ),
)


def _has_unnegated_signal(
    text: str,
    patterns: tuple[re.Pattern[str], ...],
    negations: tuple[re.Pattern[str], ...],
) -> bool:
    return any(pattern.search(text) for pattern in patterns) and not any(
        pattern.search(text) for pattern in negations
    )


def detect_support_intent(text: str) -> SupportIntent:
    """Classify a bounded claimant message without invoking a model.

    Args:
        text: The claimant-authored text from the current message.

    Returns:
        The highest-priority explicit support signal, or ``NONE``.
    """

    if _has_unnegated_signal(text, _ACCESSIBILITY_PATTERNS, _NEGATED_ACCESSIBILITY_PATTERNS):
        return SupportIntent.ACCESSIBILITY_NEED
    if _has_unnegated_signal(text, _DISTRESS_PATTERNS, _NEGATED_DISTRESS_PATTERNS):
        return SupportIntent.DISTRESS
    if _has_unnegated_signal(text, _EXPLICIT_HUMAN_PATTERNS, _NEGATED_HUMAN_PATTERNS):
        return SupportIntent.EXPLICIT_HUMAN_REQUEST
    return SupportIntent.NONE


def support_need_for_intent(intent: SupportIntent) -> SupportNeed | None:
    """Map a deterministic support signal to the persisted handoff contract.

    Args:
        intent: A signal returned by :func:`detect_support_intent`.

    Returns:
        The corresponding support need, or ``None`` when no support was requested.
    """

    return {
        SupportIntent.NONE: None,
        SupportIntent.EXPLICIT_HUMAN_REQUEST: SupportNeed.HUMAN_REQUESTED,
        SupportIntent.ACCESSIBILITY_NEED: SupportNeed.ACCESSIBILITY_REQUIRED,
        SupportIntent.DISTRESS: SupportNeed.DISTRESS,
    }[intent]


__all__ = ['SupportIntent', 'detect_support_intent', 'support_need_for_intent']
