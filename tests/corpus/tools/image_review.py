"""Image review rules agreed with the maintainer on 2026-09-30 (review-ysoseri-0.2-reply.md).

1. A fixed rule decides which images a person must look at. An image is flagged when:
   - the image-only model pass names a damaged object that is not one of the pack's expected
     object names;
   - either model pass reports, or fails to report, a licence plate, a person, a logo or readable
     text;
   - the model pass with facts does not answer matches_facts = yes (deliberately unreadable images
     are exempt from this point only; the image-only point still applies, so they always reach a
     person).
   Size estimates are never used. A model pass counts only for the image and, for the pass with
   facts, the facts it was shown.
2. Of the images that are not flagged, at least 10 % are sampled at random, with at least one per
   scenario category. If a person rejects a sampled image, the model missed a problem, and every
   image in that category must be signed off one by one. That escalation is permanent.
   A corpus version has one draw. `sampling.json` is never rewritten; escalations and rejected
   slots are read from the sign-off records themselves, so no edit or new draw can clear them.
3. An image hash is signed once; the sign-off covers every pack that uses the same image.
4. Every sign-off records its method: `per_image` (a person looked at it) or
   `model_check_with_sampling` (released after the model check and a clean sample).

Decisions are made per image hash: a hash is flagged if any pack copy of it is flagged, and it
belongs to every scenario category it appears in.
"""

import hashlib
import json
import math
import os
import random
import re
from collections.abc import Iterable
from typing import Any, cast

IMAGE_KINDS = {'incident_photo', 'item_photo'}
UNREADABLE_TRANSFORMS = {'blur'}
BROKEN_TRANSFORMS = {'truncate', 'to_tiff'}
METHODS = {'per_image', 'model_check_with_sampling'}
SAMPLE_SHARE = 0.10
SAMPLING_FILE = 'sampling.json'
PRIVACY_LISTS = ('people', 'brand_logo', 'readable_text')
FACT_HINTS = (
    'incident.description',
    'loss.description',
    'vehicle.damage_description',
    'theft.entry_context',
    'property.affected_areas',
    'contents.items',
)


def sha256(path: str) -> str:
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def fact_text(facts: dict[str, Any]) -> str:
    return '\n'.join(
        f'- {k}: {json.dumps(facts[k], ensure_ascii=False)}' for k in FACT_HINTS if k in facts
    )


def prompt_inputs_sha256(purpose: str, facts: dict[str, Any]) -> str:
    """Hash of what the pass with facts was shown, so an edited fact sheet makes that pass stale."""
    return hashlib.sha256(
        json.dumps([purpose, fact_text(facts)], ensure_ascii=False).encode()
    ).hexdigest()


def corpus_images(corpus: str) -> list[dict[str, Any]]:
    (
        """Every image copy in the corpus with its pack, category, provenance entry, review """
        """record and hash."""
    )
    images: list[dict[str, Any]] = []
    for case_id in sorted(os.listdir(os.path.join(corpus, 'cases'))):
        case_dir = os.path.join(corpus, 'cases', case_id)
        with open(os.path.join(case_dir, 'oracle', 'labels.json'), encoding='utf-8') as f:
            oracle = json.load(f)
        with open(os.path.join(case_dir, 'input', 'facts.json'), encoding='utf-8') as f:
            facts = json.load(f)['facts']
        with open(os.path.join(case_dir, 'provenance.json'), encoding='utf-8') as f:
            provenance = json.load(f)['materials']
        review_path = os.path.join(case_dir, 'review.json')
        reviews: dict[str, Any] = {}
        if os.path.exists(review_path):
            with open(review_path, encoding='utf-8') as f:
                reviews = {r['file']: r for r in json.load(f).get('images', [])}
        for entry in provenance:
            if entry.get('evidence_kind') not in IMAGE_KINDS:
                continue
            path = os.path.join(case_dir, 'input', 'materials', entry['file'])
            images.append(
                {
                    'case_id': case_id,
                    'file': entry['file'],
                    'category': oracle.get('scenario_category'),
                    'entry': entry,
                    'review': reviews.get(entry['file'], {}),
                    'sha256': sha256(path),
                    'inputs_sha256': prompt_inputs_sha256(entry.get('purpose', ''), facts),
                    'material_id': entry['id'],
                }
            )
    return images


def _current(record: dict[str, Any], key: str, sha: str) -> dict[str, Any] | None:
    item = record.get(key)
    return item if item and item.get('sha256') == sha else None


# The image-only question asks for the specific damaged part (version 2). An answer to the older
# question ("what object is damaged") often named just "car", so it no longer counts as current.
BLIND_QUESTION_VERSION = 2

# New Zealand and American names for the same part, so the model's wording does not decide a flag.
SYNONYMS = [
    {'windscreen', 'windshield'},
    {'bonnet', 'hood'},
    {'guard', 'fender', 'wing'},
    {'tyre', 'tire'},
    {'boot', 'trunk', 'tailgate'},
    {'spouting', 'gutter', 'guttering', 'downpipe', 'downspout'},
    {'lamp post', 'lamppost', 'light pole', 'street light', 'streetlight'},
    {'wheel', 'rim'},
    {'television', 'tv'},
    {'wing mirror', 'side mirror', 'door mirror'},
    {'ute', 'pickup'},
    {
        'heat pump',
        'heat pump unit',
        'outdoor unit',
        'air conditioner',
        'air conditioning unit',
        'ac unit',
    },
    {'barbecue', 'bbq', 'grill'},
    {'phone', 'smartphone', 'mobile phone', 'cell phone'},
]

# Words that name a region or component of something rather than the thing itself. For
# "smartphone screen" or "door edge" the word before them is what gets compared.
COMPONENT_WORDS = {
    'screen',
    'lid',
    'cover',
    'casing',
    'case',
    'housing',
    'panel',
    'glass',
    'edge',
    'corner',
    'frame',
    'surface',
    'area',
    'top',
    'side',
    'base',
    'front',
    'back',
    'section',
    'part',
}


def _expand(names: Iterable[str]) -> set[str]:
    out = {n.lower() for n in names}
    for group in SYNONYMS:
        for name in list(out):
            for word in group:
                if name == word or name.endswith(' ' + word):
                    out.update(name[: len(name) - len(word)] + other for other in group)
    return out


def _names_object(seen: str, names: Iterable[str]) -> bool:
    """True when a damaged-part phrase ends with one of the accepted names, as whole words.

    English puts the head noun last, so 'tv cabinet' names a cabinet, 'car bumper' a bumper. An
    answer listing parts ('gutter and downspout') is split, 'front bumper of a car' is read as
    'front bumper', and a trailing component word ('smartphone screen', 'door lock area') is
    also tried without it.
    """
    accepted = _expand(names)
    phrase = re.sub(r'[^a-z0-9 ,/-]', ' ', seen.lower())
    for part in re.split(r',|/|\band\b|\bor\b|\bwith\b', phrase):
        part = re.sub(r'\s+(of|on|in|at|near)\s+.*$', '', part.strip())
        part = re.sub(r'^(the|a|an)\s+', '', re.sub(r'\s+', ' ', part).strip())
        candidates = [part]
        words = part.split(' ')
        while len(words) > 1 and words[-1] in COMPONENT_WORDS:
            words = words[:-1]
            candidates.append(' '.join(words))
        for candidate in candidates:
            if candidate and any(
                re.search(r'(?:^|\s)' + re.escape(name) + r'$', candidate) for name in accepted
            ):
                return True
    return False


def _privacy_reasons(name: str, answers: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    plate = answers.get('licence_plate')
    if not isinstance(plate, str) or plate.strip().lower().rstrip('.') != 'none':
        reasons.append(f'{name} pass: licence plate is {plate!r}, not exactly "none"')
    for key in PRIVACY_LISTS:
        value = answers.get(key)
        if not isinstance(value, list):
            reasons.append(f'{name} pass: {key} is missing or not a list ({value!r})')
        elif value:
            reasons.append(f'{name} pass: {key} {value}')
    return reasons


def copy_flag_reasons(image: dict[str, Any]) -> list[str]:
    (
        """The reasons a person must look at this copy of an image; empty means the model check """
        """passed."""
    )
    sha, entry, record = image['sha256'], image['entry'], image['review']
    if entry.get('inputs', {}).get('transform') in BROKEN_TRANSFORMS:
        # A deliberately corrupt or unsupported file is not sent to the model at all.
        return ['deliberately broken file (corrupt or unsupported format); a person checks it']
    unreadable = entry.get('inputs', {}).get('transform') in UNREADABLE_TRANSFORMS
    blind_record = _current(record, 'model_blind', sha)
    if blind_record and blind_record.get('question_version') != BLIND_QUESTION_VERSION:
        blind_record = None
    blind = (blind_record or {}).get('answers')
    led_record = _current(record, 'model_check', sha)
    if led_record and led_record.get('inputs_sha256') != image['inputs_sha256']:
        led_record = None
    led = (led_record or {}).get('answers')
    reasons: list[str] = []
    if blind is None:
        reasons.append('no current image-only model pass')
    if led is None:
        reasons.append(
            'no current model pass with facts (missing, or the image or facts changed since)'
        )
    if blind is not None:
        seen = str(blind.get('what_is_damaged', ''))
        names = entry.get('expect_object', [])
        if unreadable:
            reasons.append(
                f'deliberately unreadable image; the image-only pass names {seen!r}, '
                'which cannot match the facts, so a person checks it'
            )
        elif not names:
            reasons.append('the pack gives no expect_object for this image')
        elif not _names_object(seen, names):
            reasons.append(f'image-only pass names {seen!r}, expected one of {names}')
        reasons.extend(_privacy_reasons('image-only', blind))
    if led is not None:
        reasons.extend(_privacy_reasons('with-facts', led))
        if not unreadable and led.get('matches_facts') != 'yes':
            reasons.append(f'with-facts pass: matches_facts is {led.get("matches_facts")!r}')
    return reasons


def by_hash(images: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Group copies by hash: categories, copies, and the flag reasons of every copy."""
    groups: dict[str, dict[str, Any]] = {}
    for image in images:
        group = groups.setdefault(
            image['sha256'],
            {'sha256': image['sha256'], 'copies': [], 'categories': set(), 'reasons': []},
        )
        group['copies'].append(image)
        group['categories'].add(image['category'])
        group['reasons'].extend(
            f'{image["case_id"]}/{image["file"]}: {r}' for r in copy_flag_reasons(image)
        )
    return groups


def flag_reasons(
    image: dict[str, Any], groups: dict[str, dict[str, Any]] | None = None
) -> list[str]:
    """Hash-level flag: a hash is flagged if any copy of it is flagged."""
    groups = groups or by_hash([image])
    return cast(list[str], groups[image['sha256']]['reasons'])


def signoffs_by_hash(images: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Rule 3: every current human sign-off per image hash, wherever it was recorded."""
    found: dict[str, list[dict[str, Any]]] = {}
    for image in images:
        item = _current(image['review'], 'human_signoff', image['sha256'])
        if item:
            found.setdefault(image['sha256'], []).append(item)
    return found


def all_review_entries(corpus: str) -> list[tuple[str, dict[str, Any]]]:
    (
        """Every review.json entry of every pack, including entries whose file is no longer """
        """in the pack."""
    )
    entries: list[tuple[str, dict[str, Any]]] = []
    for case_id in sorted(os.listdir(os.path.join(corpus, 'cases'))):
        path = os.path.join(corpus, 'cases', case_id, 'review.json')
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                for entry in json.load(f).get('images', []):
                    entries.append((case_id, entry))
    return entries


def rejection_state(
    corpus: str, images: Iterable[dict[str, Any]]
) -> tuple[set[str], set[tuple[str, str]]]:
    """Escalated categories and rejected material slots, from every sign-off ever recorded.

    Escalation follows only a rejected *sampled* image (rule 2); the categories are those recorded
    at sign time for the whole hash. A slot (pack and material id) that ever held a rejected image
    must be signed per image from then on, whatever its file name.
    """
    material_ids = {(i['case_id'], i['file']): i['material_id'] for i in images}
    escalated: set[str]
    slots: set[tuple[str, str]]
    escalated, slots = set(), set()
    for case_id, entry in all_review_entries(corpus):
        for item in [entry.get('human_signoff')] + entry.get('signoff_history', []):  # noqa: RUF005  unpacking would also accept a non-list history
            if not item or item.get('result') != 'rejected':
                continue
            slots.add(
                (
                    case_id,
                    item.get('material_id')
                    or material_ids.get((case_id, entry['file']), entry['file']),
                )
            )
            if item.get('sampled'):
                escalated.update(item.get('categories', []))
    return escalated, slots


def orphan_entries(corpus: str, images: Iterable[dict[str, Any]]) -> list[tuple[str, str]]:
    present = {(i['case_id'], i['file']) for i in images}
    return [
        (case_id, entry['file'])
        for case_id, entry in all_review_entries(corpus)
        if (case_id, entry['file']) not in present
    ]


def draw_sha256(sampling: dict[str, Any]) -> str:
    """Hash of the draw itself (seed, population, sample), which never changes after `sample`."""
    core = {k: sampling[k] for k in ('seed', 'population', 'sample')}
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()


def load_sampling(corpus: str) -> dict[str, Any] | None:
    path = os.path.join(corpus, SAMPLING_FILE)
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        return cast(dict[str, Any], json.load(f))


def draw_rows(population: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    (
        """Rule 2 on population rows: at least 10 % of hashes, at least one per category, """
        """reproducible."""
    )
    population = sorted(population, key=lambda r: r['sha256'])
    rng = random.Random(seed)
    chosen: dict[str, dict[str, Any]] = {}
    for category in sorted({c for r in population for c in r['categories']}):
        if any(category in chosen[h]['categories'] for h in chosen):
            continue
        members = [r for r in population if category in r['categories']]
        pick = rng.choice(members)
        chosen[pick['sha256']] = pick
    target = max(len(chosen), math.ceil(SAMPLE_SHARE * len(population)))
    rest = [r for r in population if r['sha256'] not in chosen]
    rng.shuffle(rest)
    for row in rest[: max(0, target - len(chosen))]:
        chosen[row['sha256']] = row
    return sorted(chosen.values(), key=lambda r: r['sha256'])


def population_rows(
    images: Iterable[dict[str, Any]], signoffs: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    """Unflagged image hashes with no sign-off yet: the images a draw may release."""
    groups = by_hash(images)
    rows: list[dict[str, Any]] = []
    for sha, group in sorted(groups.items()):
        if group['reasons'] or sha in signoffs:
            continue
        first = group['copies'][0]
        rows.append(
            {
                'sha256': sha,
                'categories': sorted(group['categories']),
                'copies': [f'{c["case_id"]}/{c["file"]}' for c in group['copies']],
                'case_id': first['case_id'],
                'file': first['file'],
            }
        )
    return rows


def category_status(
    sampling: dict[str, Any], signoffs: dict[str, list[dict[str, Any]]], escalated: set[str]
) -> dict[str, str]:
    """'escalated', 'pending' (a sampled hash has no accepted per-image sign-off) or 'clean'."""
    status = {c: 'escalated' for c in escalated}
    for row in sampling['sample']:
        items = signoffs.get(row['sha256'], [])
        for category in row['categories']:
            if status.get(category) == 'escalated':
                continue
            if any(i.get('result') == 'rejected' for i in items):
                status[category] = 'escalated'
            elif not any(
                i.get('method') == 'per_image' and i.get('result') == 'accepted' for i in items
            ):
                status[category] = 'pending'
            else:
                status.setdefault(category, 'clean')
    return status


def sampling_problems(
    sampling: dict[str, Any] | None, groups: dict[str, dict[str, Any]]
) -> list[str]:
    """Freeze check on sampling.json itself."""
    if sampling is None:
        return []
    problems: list[str] = []
    if sampling.get('draw_sha256') != draw_sha256(sampling):
        problems.append('sampling.json: the draw has been edited since it was made')
    redrawn = draw_rows(sampling['population'], sampling['seed'])
    if [r['sha256'] for r in redrawn] != sorted(r['sha256'] for r in sampling['sample']):
        problems.append(
            'sampling.json: the recorded sample is not the draw its seed and population give'
        )
    for row in sampling['population']:
        group = groups.get(row['sha256'])
        if group and sorted(group['categories']) != sorted(row['categories']):
            problems.append(
                f'sampling.json: {row["case_id"]}/{row["file"]} is recorded with categories '
                f'{row["categories"]} but the corpus has {sorted(group["categories"])}'
            )
    return problems


def release_problem(
    image: dict[str, Any],
    groups: dict[str, dict[str, Any]],
    signoffs: dict[str, list[dict[str, Any]]],
    sampling: dict[str, Any] | None,
    escalated: set[str],
    rejected_slots: set[tuple[str, str]],
) -> str | None:
    """Why this image copy does not meet the freeze rule, or None when it does."""
    items = signoffs.get(image['sha256'], [])
    if not items:
        return 'no human sign-off'
    if len(items) > 1:
        return f'{len(items)} current sign-offs for one image hash; a hash is signed once'
    item = items[0]
    if item.get('result') != 'accepted':
        return f'human sign-off is {item.get("result")} ({item.get("note")})'
    method = item.get('method')
    if method not in METHODS:
        return f'sign-off has no valid method ({method!r})'
    if method == 'per_image':
        return None
    group = groups[image['sha256']]
    if group['reasons']:
        return 'released by sampling, but the model check flags it: ' + '; '.join(group['reasons'])
    if any((c['case_id'], c['material_id']) in rejected_slots for c in group['copies']):
        return (
            'this image fills a slot that held a rejected image, so it must be signed off per image'
        )
    if sampling is None:
        return 'released by sampling, but the corpus has no sampling.json'
    if item.get('draw_sha256') != sampling.get('draw_sha256') or sampling.get(
        'draw_sha256'
    ) != draw_sha256(sampling):
        return 'released by sampling, but not by the draw recorded in sampling.json'
    if image['sha256'] not in {r['sha256'] for r in sampling['population']}:
        return 'released by sampling, but the image was not in the sampled population'
    if image['sha256'] in {r['sha256'] for r in sampling['sample']}:
        return 'a sampled image must be signed off per image'
    status = category_status(sampling, signoffs, escalated)
    for category in sorted(group['categories']):
        if status.get(category) != 'clean':
            return (
                f'released by sampling, but category {category} is '
                f'{status.get(category) or "not sampled"}'
            )
    return None
