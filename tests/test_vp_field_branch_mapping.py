from pathlib import Path

from backend.domain.branch_registry import COMMON_FIELDS, FAMILY_FIELDS, build_default_registry
from backend.domain.field_registry import REGISTERED_FIELD_CODES

MAPPING_DOCUMENT = Path(__file__).parents[1] / 'docs' / 'vp-field-branch-mapping.md'


def test_vp_mapping_document_covers_every_executable_field_once() -> None:
    text = MAPPING_DOCUMENT.read_text(encoding='utf-8')
    registry = build_default_registry()
    mapped_codes = [
        line.split('|')[1].strip().strip('`')
        for line in text.splitlines()
        if line.startswith('| `') and line.count('|') >= 8
    ]

    assert registry.field_codes == REGISTERED_FIELD_CODES
    assert len(mapped_codes) == len(REGISTERED_FIELD_CODES)
    assert set(mapped_codes) == REGISTERED_FIELD_CODES
    assert COMMON_FIELDS | FAMILY_FIELDS['motor'] | FAMILY_FIELDS['home'] == REGISTERED_FIELD_CODES
    assert FAMILY_FIELDS['contents'] == frozenset()


def test_contents_mapping_declares_independent_record_boundary() -> None:
    text = MAPPING_DOCUMENT.read_text(encoding='utf-8')

    assert '`WorkingClaim.contents_items`' in text
    assert 'not by flattened form fields' in text
    assert 'ClaimantContentsItem' in text
