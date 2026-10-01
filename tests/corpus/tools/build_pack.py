"""Build controlled test packs from spec files.

Usage:
  python -m tests.corpus.tools.build_pack CORPUS_DIR SPEC.json [SPEC.json ...]

Each spec holds the fact sheet, the initial message, the material plan and the oracle. The script
writes CORPUS_DIR/cases/<case_id>/input/... and .../oracle/labels.json, then rewrites
CORPUS_DIR/manifest.json from every pack present.
"""

import contextlib
import glob
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tests.corpus.tools import imagegen, rules, templates, transforms

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_VERSION = '0.2'
USAGE_RIGHTS = 'Synthetic, created by the team for this project'


def sha256(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def generator_version() -> str:
    """Hash of the tool sources, the same on every checkout whatever its line endings."""
    digest = hashlib.sha256()
    for path in [*sorted(glob.glob(os.path.join(HERE, '*.py'))), imagegen.GRAPH]:
        digest.update(Path(path).read_bytes().replace(b'\r\n', b'\n'))
    return 'tools-sha256:' + digest.hexdigest()[:16]


def now() -> str:
    return datetime.now(UTC).isoformat(timespec='seconds')


def clear_dir(path: str, attempts: int = 5) -> None:
    """Empty a folder but keep it. OneDrive can lock a folder briefly, so retry file removal."""
    os.makedirs(path, exist_ok=True)
    for root, dirs, files in os.walk(path, topdown=False):
        for name in files:
            target = os.path.join(root, name)
            for attempt in range(attempts):
                try:
                    os.remove(target)
                    break
                except PermissionError:
                    if attempt == attempts - 1:
                        raise
                    time.sleep(1)
        for name in dirs:
            with contextlib.suppress(OSError):
                os.rmdir(os.path.join(root, name))


def build(corpus_dir: str, spec_path: str) -> None:
    with open(spec_path, encoding='utf-8') as handle:
        spec: dict[str, Any] = json.load(handle)
    case_dir = os.path.join(corpus_dir, 'cases', spec['case_id'])
    input_dir = os.path.join(case_dir, 'input')
    materials_dir = os.path.join(input_dir, 'materials')
    oracle_dir = os.path.join(case_dir, 'oracle')
    review_path = os.path.join(case_dir, 'review.json')
    review = Path(review_path).read_bytes() if os.path.exists(review_path) else None
    clear_dir(case_dir)
    os.makedirs(materials_dir, exist_ok=True)
    os.makedirs(oracle_dir, exist_ok=True)
    if review is not None:
        Path(review_path).write_bytes(review)
    scratch = tempfile.mkdtemp(prefix='pack-')
    produced: dict[str, str] = {}
    entries: list[dict[str, Any]] = []
    for material in spec['materials']:
        target_dir = materials_dir if material.get('include', True) else scratch
        path = os.path.join(target_dir, material['file'])
        entry: dict[str, Any] = {
            'id': material['id'],
            'file': material['file'],
            'evidence_kind': material.get('evidence_kind'),
            'method': material['method'],
            'generator_version': generator_version(),
            'created_utc': now(),
            'purpose': material['purpose'],
            **({'expect_object': material['expect_object']} if 'expect_object' in material else {}),
            'available_from': material.get('available_from', 'start'),
            'synthetic': True,
            'usage_rights': USAGE_RIGHTS,
        }
        if material['method'] == 'image_model':
            width, height = material.get('size', [1216, 896])
            details: dict[str, Any] = imagegen.generate(
                material['prompt'], material['seed'], width, height, path
            )
            entry['model'] = details['model']
            entry['inputs'] = {
                k: details[k]
                for k in ('prompt', 'seed', 'width', 'height', 'remote_prompt_id', 'cache_key')
            }
        elif material['method'] == 'template':
            printed: dict[str, Any] = templates.RENDERERS[material['template']](
                material['data'], path
            )
            # Kept for the checker: the issuer against the business list, and a schedule's period
            # and excess against the policy the runner puts into the system.
            for key in ('issuer', 'period', 'excess'):
                if material['data'].get(key):
                    printed[key] = material['data'][key]
            entry['model'] = None
            entry['inputs'] = {'template': material['template']}
            entry['printed_fields'] = printed
            entry['fact_links'] = material.get('fact_links', {})
        elif material['method'] == 'transform':
            source = produced[material['source']]
            details = transforms.TRANSFORMS[material['transform']](
                source, path, **material.get('params', {})
            )
            entry['model'] = None
            entry['inputs'] = {'source': material['source'], **details}
            entry['fact_links'] = material.get('fact_links', {})
            source_entry = next((e for e in entries if e['id'] == material['source']), None)
            if source_entry and 'printed_fields' in source_entry:
                printed = dict(source_entry['printed_fields'])
                if material['transform'] == 'keep_pages':
                    kept = {index + 1 for index in material['params']['pages']}
                    pages = templates.FIELD_PAGES.get(source_entry['inputs'].get('template'), {})
                    printed = {k: v for k, v in printed.items() if pages.get(k, 1) in kept}
                entry['printed_fields'] = printed
        else:
            raise ValueError('unknown method ' + material['method'])
        produced[material['id']] = path
        if material.get('include', True):
            entry['sha256'] = sha256(path)
            entry['bytes'] = os.path.getsize(path)
            entries.append(entry)
        else:
            entry['included'] = False
            entries.append(entry)
    shutil.rmtree(scratch, ignore_errors=True)

    with open(os.path.join(input_dir, 'initial_message.txt'), 'w', encoding='utf-8') as handle:
        handle.write(spec['initial_message'].strip() + '\n')
    facts = {
        'case_id': spec['case_id'],
        'persona': spec['persona'],
        'answer_policy': spec.get(
            'answer_policy',
            'Answer only what is asked, from these facts. Say "I don\'t know" for unknown facts.',
        ),
        'facts': spec['facts'],
    }
    with open(os.path.join(input_dir, 'facts.json'), 'w', encoding='utf-8') as handle:
        json.dump(facts, handle, indent=1, ensure_ascii=False)
    included = [e for e in entries if e.get('included', True)]
    # input/materials.json is model-visible, so it lists only what a claimant would know about each
    # file. Purposes, prompts, printed fields and intermediate sources stay in provenance.json,
    # which only the checker and the scorer read.
    visible = [
        {
            'file': e['file'],
            'evidence_kind': e['evidence_kind'],
            'available_from': e['available_from'],
        }
        for e in included
    ]
    materials_doc = {'case_id': spec['case_id'], 'materials': visible}
    with open(os.path.join(input_dir, 'materials.json'), 'w', encoding='utf-8') as handle:
        json.dump(materials_doc, handle, indent=1, ensure_ascii=False)
    provenance = {
        'case_id': spec['case_id'],
        'materials': included,
        'intermediate_sources': [e for e in entries if not e.get('included', True)],
    }
    with open(os.path.join(case_dir, 'provenance.json'), 'w', encoding='utf-8') as handle:
        json.dump(provenance, handle, indent=1, ensure_ascii=False)
    oracle: dict[str, Any] = {
        'case_id': spec['case_id'],
        'schema_version': SCHEMA_VERSION,
        'rules_ref': rules.RULES_REF,
        **spec['oracle'],
    }
    oracle['design'] = {'message_style': spec['message_style'], **spec['oracle'].get('design', {})}
    with open(os.path.join(oracle_dir, 'labels.json'), 'w', encoding='utf-8') as handle:
        json.dump(oracle, handle, indent=1, ensure_ascii=False)
    # The runner reads setup.json to prepare the environment before the run. It is not model input.
    setup = {'case_id': spec['case_id'], **spec['setup']}
    with open(os.path.join(case_dir, 'setup.json'), 'w', encoding='utf-8') as handle:
        json.dump(setup, handle, indent=1, ensure_ascii=False)
    print(f'built {spec["case_id"]}: {len(included)} materials')


def write_manifest(corpus_dir: str, quiet: bool = False) -> None:
    packs: list[dict[str, Any]] = []
    for case_dir in sorted(glob.glob(os.path.join(corpus_dir, 'cases', '*'))):
        files: list[dict[str, Any]] = []
        for path in sorted(glob.glob(os.path.join(case_dir, '**', '*'), recursive=True)):
            if os.path.isfile(path):
                files.append(
                    {
                        'path': os.path.relpath(path, corpus_dir).replace('\\', '/'),
                        'sha256': sha256(path),
                        'bytes': os.path.getsize(path),
                    }
                )
        packs.append({'case_id': os.path.basename(case_dir), 'files': files})
    corpus_files = [
        {'path': name, 'sha256': sha256(os.path.join(corpus_dir, name))}
        for name in ('sampling.json',)
        if os.path.exists(os.path.join(corpus_dir, name))
    ]
    manifest = {
        'corpus': 'controlled',
        'corpus_version': os.path.basename(os.path.abspath(corpus_dir)),
        'schema_version': SCHEMA_VERSION,
        'generator_version': generator_version(),
        'written_utc': now(),
        'corpus_files': corpus_files,
        'packs': packs,
    }
    with open(os.path.join(corpus_dir, 'manifest.json'), 'w', encoding='utf-8') as handle:
        json.dump(manifest, handle, indent=1)
    if not quiet:
        print(f'manifest: {len(packs)} packs')


if __name__ == '__main__':
    corpus = sys.argv[1]
    for spec_file in sys.argv[2:]:
        build(corpus, spec_file)
    write_manifest(corpus)
