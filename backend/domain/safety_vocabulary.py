"""Shared word roots; callers retain their distinct safety/candidate grammars."""

INJURY_ROOT = r'injur'
HURT_ROOT = r'hurt'
DANGER_ROOT = r'danger'
UNSAFE_ROOT = r'unsafe'

INJURY_STATE_PATTERN = rf'(?:{INJURY_ROOT}ed|{HURT_ROOT}|bleeding|trapped|unconscious)'
PAIN_SYMPTOM_PATTERN = r'(?:sore\s+(?:neck|back|head|arm|leg)|(?:neck|back|chest)\s+pain)'
INJURY_NOUN_PATTERN = rf'(?:{INJURY_ROOT}(?:y|ies)|{PAIN_SYMPTOM_PATTERN})'
DANGER_STATE_PATTERN = rf'(?:{DANGER_ROOT}|{DANGER_ROOT}ous|{UNSAFE_ROOT})'
WEAK_SAFETY_PATTERN = (
    rf'(?:{INJURY_ROOT}(?:y|ed)|{HURT_ROOT}|{PAIN_SYMPTOM_PATTERN}|'
    rf'{DANGER_ROOT}|{UNSAFE_ROOT}|emergency)'
)
WEAK_SAFETY_NEGATION_PATTERN = rf'(?:{INJURY_ROOT}ed|{HURT_ROOT}|in {DANGER_ROOT})'
