import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.corpus.tools import corpus_integrity


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding='utf-8')


def _corpus(tmp_path: Path, families: dict[str, str] | None = None) -> Path:
    """A corpus of minimal packs whose files all name their case ID, with a matching manifest."""
    families = families or {'CTL-M-001': 'motor', 'CTL-H-001': 'home'}
    corpus = tmp_path / 'controlled' / 'v9'
    packs = []
    for case_id, family in families.items():
        case_dir = corpus / 'cases' / case_id
        for relative in corpus_integrity.CASE_FILES:
            content: dict[str, Any] = {'case_id': case_id}
            if relative == 'oracle/labels.json':
                content.update(family=family, scenario_category='M1', condition='normal')
            _write(case_dir / relative, content)
        files = [
            {
                'path': f'cases/{case_id}/{relative}',
                'sha256': hashlib.sha256((case_dir / relative).read_bytes()).hexdigest(),
            }
            for relative in corpus_integrity.CASE_FILES
        ]
        packs.append({'case_id': case_id, 'files': files})
    _write(corpus / 'manifest.json', {'corpus_version': 'v9', 'corpus_files': [], 'packs': packs})
    return corpus


def _plan(corpus: Path, rows: list[dict[str, str]]) -> None:
    _write(corpus.parent / 'plan' / 'corpus-plan-v9.json', rows)


def test_a_corpus_that_matches_its_manifest_has_no_problems(tmp_path: Path) -> None:
    assert corpus_integrity.manifest_problems(str(_corpus(tmp_path))) == []


def test_a_missing_manifest_fails_the_corpus(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path)
    (corpus / 'manifest.json').unlink()

    problems = corpus_integrity.manifest_problems(str(corpus))

    assert problems == [
        'manifest: manifest.json is missing or unreadable; the corpus cannot be checked'
    ]


def test_a_removed_pack_is_reported_even_though_every_remaining_pack_is_fine(
    tmp_path: Path,
) -> None:
    corpus = _corpus(tmp_path)
    shutil.rmtree(corpus / 'cases' / 'CTL-H-001')

    problems = corpus_integrity.manifest_problems(str(corpus))

    assert 'manifest: 1 listed pack(s) missing: CTL-H-001' in problems
    assert any(p.startswith('manifest: 6 listed file(s) missing') for p in problems)


@pytest.mark.parametrize(
    ('change', 'expected'),
    [
        ('extra pack', 'manifest: 1 pack(s) not in the manifest: CTL-C-001'),
        ('extra file', 'manifest: 1 file(s) not in the manifest: cases/CTL-M-001/input/extra.txt'),
        ('edited file', 'manifest: 1 file(s) differ from their hash: cases/CTL-M-001/setup.json'),
    ],
)
def test_anything_the_manifest_does_not_record_is_reported(
    tmp_path: Path, change: str, expected: str
) -> None:
    corpus = _corpus(tmp_path)
    if change == 'extra pack':
        _write(corpus / 'cases' / 'CTL-C-001' / 'setup.json', {'case_id': 'CTL-C-001'})
    elif change == 'extra file':
        (corpus / 'cases' / 'CTL-M-001' / 'input' / 'extra.txt').write_text('x', encoding='utf-8')
    else:
        _write(corpus / 'cases' / 'CTL-M-001' / 'setup.json', {'case_id': 'CTL-M-001', 'x': 1})

    assert expected in corpus_integrity.manifest_problems(str(corpus))


def test_the_plan_is_matched_pack_by_pack(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path)
    _plan(
        corpus,
        [
            {'case_id': 'CTL-M-001', 'family': 'motor', 'category': 'M1', 'condition': 'normal'},
            {'case_id': 'CTL-H-001', 'family': 'home', 'category': 'H2', 'condition': 'normal'},
            {'case_id': 'CTL-C-001', 'family': 'contents', 'category': 'C1', 'condition': 'normal'},
        ],
    )

    problems, plan = corpus_integrity.plan_problems(str(corpus))

    assert plan is not None and plan.endswith('corpus-plan-v9.json')
    assert problems == [
        'plan: 1 planned pack(s) not in the corpus: CTL-C-001',
        "plan: CTL-H-001 scenario_category is 'M1', the plan says 'H2'",
    ]


def test_a_version_without_a_plan_is_not_checked_against_one(tmp_path: Path) -> None:
    assert corpus_integrity.plan_problems(str(_corpus(tmp_path))) == ([], None)


def test_every_file_of_a_pack_must_name_its_case_id(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path)
    case_dir = corpus / 'cases' / 'CTL-M-001'
    assert corpus_integrity.case_id_problems(str(case_dir)) == []
    _write(case_dir / 'setup.json', {'case_id': 'CTL-M-002'})

    problems = corpus_integrity.case_id_problems(str(case_dir))

    assert problems == ["case ID: setup.json names 'CTL-M-002', the folder is 'CTL-M-001'"]


def test_the_case_id_letter_must_match_the_family(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path, {'CTL-M-001': 'home'})

    problems = corpus_integrity.case_id_problems(str(corpus / 'cases' / 'CTL-M-001'))

    assert problems == ["case ID: CTL-M-001 is a motor ID, the family is 'home'"]


@pytest.mark.parametrize(
    ('transform', 'boundary', 'expected'),
    [
        # The material each boundary condition was made from is exempt from its own failure.
        ('truncate', {'corrupt_file'}, (True, False)),
        ('to_tiff', {'unsupported_format'}, (False, True)),
        # Another material in the same boundary pack is not: this is the case a pack-wide
        # exemption used to let through.
        (None, {'corrupt_file', 'unsupported_format'}, (False, False)),
        ('blur', {'illegible', 'corrupt_file'}, (False, False)),
        # A transform without its labelled condition earns no exemption either.
        ('truncate', {'normal'}, (False, False)),
    ],
)
def test_a_format_exemption_follows_the_material_not_the_pack(
    transform: str | None, boundary: set[str], expected: tuple[bool, bool]
) -> None:
    entry = {'inputs': {'transform': transform}} if transform else {'inputs': {}}

    assert corpus_integrity.format_exemption(entry, boundary) == expected
