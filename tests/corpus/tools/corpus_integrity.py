"""Corpus-level integrity checks that need only the standard library.

check_corpus.py calls these; they live apart so their tests run in CI, where the PDF libraries
check_corpus.py needs are not installed.

- manifest_problems: the corpus on disk is exactly what its committed manifest lists, file for
  file and hash for hash, so a PASS count covers every listed pack and nothing else.
- plan_problems: the packs match the distribution plan of their version, when one exists.
- case_id_problems: every file of a pack names the pack's own case ID.
- format_exemption: which format failure a material may show, decided by how that material
  was made, not by the pack's boundary conditions alone.
"""

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

MANIFEST = 'manifest.json'
CASE_ID = re.compile(r'^CTL-([MHC])-\d{3}$')
FAMILY_LETTER = {'M': 'motor', 'H': 'home', 'C': 'contents'}
CASE_FILES = (
    'input/facts.json',
    'input/materials.json',
    'oracle/labels.json',
    'setup.json',
    'provenance.json',
    'review.json',
)
EXAMPLES = 5


def _sha256(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _some(items: list[str]) -> str:
    shown = ', '.join(items[:EXAMPLES])
    return shown + (f' and {len(items) - EXAMPLES} more' if len(items) > EXAMPLES else '')


def load_manifest(corpus: str) -> dict[str, Any] | None:
    path = os.path.join(corpus, MANIFEST)
    try:
        manifest = _load(path)
    except (OSError, ValueError):
        return None
    return manifest if isinstance(manifest, dict) else None


def manifest_problems(corpus: str) -> list[str]:
    """The corpus must hold exactly the packs and files its manifest lists, with their hashes."""
    manifest = load_manifest(corpus)
    if manifest is None:
        return [f'manifest: {MANIFEST} is missing or unreadable; the corpus cannot be checked']
    problems: list[str] = []
    packs = manifest.get('packs', [])
    listed_ids = [str(pack.get('case_id')) for pack in packs]
    if len(listed_ids) != len(set(listed_ids)):
        problems.append('manifest: a case ID is listed more than once')
    cases_dir = os.path.join(corpus, 'cases')
    on_disk = sorted(os.listdir(cases_dir)) if os.path.isdir(cases_dir) else []
    missing_packs = sorted(set(listed_ids) - set(on_disk))
    unlisted_packs = sorted(set(on_disk) - set(listed_ids))
    if missing_packs:
        problems.append(
            f'manifest: {len(missing_packs)} listed pack(s) missing: {_some(missing_packs)}'
        )
    if unlisted_packs:
        problems.append(
            f'manifest: {len(unlisted_packs)} pack(s) not in the manifest: {_some(unlisted_packs)}'
        )
    listed: dict[str, str] = {}
    for entry in manifest.get('corpus_files', []):
        listed[str(entry.get('path'))] = str(entry.get('sha256'))
    for pack in packs:
        prefix = f'cases/{pack.get("case_id")}/'
        for entry in pack.get('files', []):
            path = str(entry.get('path'))
            if not path.startswith(prefix):
                problems.append(f'manifest: {path} is listed under pack {pack.get("case_id")}')
            listed[path] = str(entry.get('sha256'))
    present: set[str] = set()
    for folder, _, names in os.walk(corpus):
        for name in names:
            relative = os.path.relpath(os.path.join(folder, name), corpus).replace(os.sep, '/')
            if relative != MANIFEST:
                present.add(relative)
    absent = sorted(set(listed) - present)
    unlisted = sorted(present - set(listed))
    changed = sorted(
        path
        for path in set(listed) & present
        if _sha256(os.path.join(corpus, path)) != listed[path]
    )
    if absent:
        problems.append(f'manifest: {len(absent)} listed file(s) missing: {_some(absent)}')
    if unlisted:
        problems.append(f'manifest: {len(unlisted)} file(s) not in the manifest: {_some(unlisted)}')
    if changed:
        problems.append(
            f'manifest: {len(changed)} file(s) differ from their hash: {_some(changed)}'
        )
    return problems


def plan_path(corpus: str, manifest: dict[str, Any]) -> str:
    """The distribution plan of the corpus version, kept in the plan folder beside the corpora."""
    version = str(manifest.get('corpus_version', ''))
    return os.path.join(corpus, '..', 'plan', f'corpus-plan-{version}.json')


def plan_problems(corpus: str) -> tuple[list[str], str | None]:
    """Compare the packs with their version's plan: the same case IDs, families, categories and
    conditions. Returns the problems and the plan used, or None when the version has no plan."""
    manifest = load_manifest(corpus)
    if manifest is None:
        return [], None
    path = plan_path(corpus, manifest)
    if not os.path.exists(path):
        return [], None
    rows = {str(row['case_id']): row for row in _load(path)}
    packs = {str(pack.get('case_id')) for pack in manifest.get('packs', [])}
    problems: list[str] = []
    missing = sorted(set(rows) - packs)
    extra = sorted(packs - set(rows))
    if missing:
        problems.append(f'plan: {len(missing)} planned pack(s) not in the corpus: {_some(missing)}')
    if extra:
        problems.append(f'plan: {len(extra)} pack(s) not in the plan: {_some(extra)}')
    for case_id in sorted(set(rows) & packs):
        labels_path = os.path.join(corpus, 'cases', case_id, 'oracle', 'labels.json')
        if not os.path.exists(labels_path):
            continue  # reported by manifest_problems
        oracle = _load(labels_path)
        for plan_key, oracle_key in (
            ('family', 'family'),
            ('category', 'scenario_category'),
            ('condition', 'condition'),
        ):
            if rows[case_id].get(plan_key) != oracle.get(oracle_key):
                problems.append(
                    f'plan: {case_id} {oracle_key} is {oracle.get(oracle_key)!r}, '
                    f'the plan says {rows[case_id].get(plan_key)!r}'
                )
    return problems, os.path.normpath(path)


def case_id_problems(case_dir: str) -> list[str]:
    """The folder name is a valid case ID of the pack's family, and every file names it."""
    case_id = os.path.basename(os.path.normpath(case_dir))
    match = CASE_ID.match(case_id)
    if not match:
        return [f'case ID: folder {case_id!r} is not CTL-<M|H|C>-<three digits>']
    problems: list[str] = []
    for relative in CASE_FILES:
        path = os.path.join(case_dir, relative)
        if not os.path.exists(path):
            continue  # a missing required part is reported by the schema check
        try:
            recorded = _load(path).get('case_id')
        except (OSError, ValueError, AttributeError):
            problems.append(f'case ID: {relative} cannot be read')
            continue
        if recorded != case_id:
            problems.append(f'case ID: {relative} names {recorded!r}, the folder is {case_id!r}')
    labels = os.path.join(case_dir, 'oracle', 'labels.json')
    if os.path.exists(labels):
        try:
            family = _load(labels).get('family')
        except (OSError, ValueError, AttributeError):
            family = None
        id_family = FAMILY_LETTER[match.group(1)]
        if family is not None and id_family != family:
            problems.append(f'case ID: {case_id} is a {id_family} ID, the family is {family!r}')
    return problems


def format_exemption(entry: dict[str, Any], boundary: set[str]) -> tuple[bool, bool]:
    """(may fail to open, may have another format) for one material.

    Only the material a boundary condition was made from is exempt: a truncated file in a
    `corrupt_file` pack may fail to open, and a file converted to TIFF in an `unsupported_format`
    pack may be TIFF. Every other material in the same pack must open as its declared type.
    """
    transform = (entry.get('inputs') or {}).get('transform')
    return (
        transform == 'truncate' and 'corrupt_file' in boundary,
        transform == 'to_tiff' and 'unsupported_format' in boundary,
    )
