"""Ask the product's own vision model what it sees in each corpus image.

Usage:
  python -m tests.corpus.tools.model_check CORPUS_DIR [CASE_ID ...]

The system under test reads claimant photos with openai/gpt-4o through OpenRouter
(config/model-runtime-bindings.json, profile openrouter-gpt-4o). This script sends each image,
with the facts it is meant to show, to the same model and records its answers as `model_check` in
the pack's review.json. It shows whether the system's model can see what the pack assumes, and it
points the human reviewer at anything worth a closer look. It does not replace the human sign-off.

The API key is read, in order, from ~/.config/fnol/openrouter.key, from CORPUS_OPENROUTER_KEY, or
from the team development secrets bundle (the same GitHub-login flow scripts/start-dev.ps1 uses).
It is kept in memory only and never printed or written.
"""

import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

from tests.corpus.tools import image_review, review_tool

MODEL = 'openai/gpt-4o'
ENDPOINT = 'https://openrouter.ai/api/v1/chat/completions'
SECRETS_ENDPOINT = 'https://ysoseri.us/secret/northwind-dev'
KEY_FILE = os.path.join(os.path.expanduser('~'), '.config', 'fnol', 'openrouter.key')
IMAGE_KINDS = {'incident_photo', 'item_photo'}
FACT_HINTS = (
    'incident.description',
    'loss.description',
    'vehicle.damage_description',
    'theft.entry_context',
    'property.affected_areas',
    'contents.items',
)

QUESTION = (
    'You are checking a synthetic test photo for an insurance claims test set.\n'
    'The photo is meant to show: {purpose}\n'
    "The claimant's facts:\n"
    '{facts}\n'
    '\n'
    'Look only at the photo and answer in JSON with these keys:\n'
    '- "description": two or three sentences on what the photo shows.\n'
    '- "matches_facts": "yes", "partly" or "no".\n'
    '- "mismatches": list of specific ways the photo disagrees with the facts '
    '(object, colour, position, extent of damage). Empty list if none.\n'
    '- "damage_extent": your estimate of the size of the visible damage, with units, '
    'or "cannot tell".\n'
    '- "damage_identifiable": true if the damage described in the facts can be made out '
    'in this photo.\n'
    '- "licence_plate": "none", "partial" or "readable"; add where it is and whether it looks '
    'like a New Zealand plate.\n'
    '- "brand_logo": list any brand names or logos you can see. Empty list if none.\n'
    '- "people": list any people or faces you can see, with where they are. Empty list if none.\n'
    '- "readable_text": list any readable text. Empty list if none.\n'
    '- "notes": anything else a reviewer should look at closely, such as a part that '
    'contradicts the story.'
)


BLIND_QUESTION = (
    'This is a photo a person uploaded to an insurance claim. Describe only what you can see. '
    'Answer in JSON with these keys:\n'
    '- "description": two or three sentences on what the photo shows.\n'
    '- "what_is_damaged": the specific damaged part or item, as precisely as you can '
    '(for example "front bumper", "rear passenger door", "windscreen", "kitchen ceiling", '
    '"laptop screen"). Never answer only "car", "vehicle", "house" or "room". '
    'If no damage is visible, "nothing visible".\n'
    '- "damage": what the damage looks like (for example dent, scrape, crack, stain, '
    'bent part), and where on the object.\n'
    '- "damage_extent": your estimate of the size of the visible damage, with units, '
    'or "cannot tell".\n'
    '- "colours": the main colours of the damaged object and of any marks on it.\n'
    '- "setting": where the photo seems to be taken, and the light.\n'
    '- "licence_plate": "none", "partial" or "readable"; add where it is and whether it looks '
    'like a New Zealand plate.\n'
    '- "brand_logo": list any brand names or logos you can see. Empty list if none.\n'
    '- "people": list any people or faces you can see, with where they are. Empty list if none.\n'
    '- "readable_text": list any readable text. Empty list if none.'
)


def _ask_blind(key: str, image_path: str) -> tuple[dict[str, Any], dict[str, Any]]:
    data = base64.b64encode(Path(image_path).read_bytes()).decode()
    body = {
        'model': MODEL,
        'temperature': 0,
        'response_format': {'type': 'json_object'},
        'messages': [
            {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': BLIND_QUESTION},
                    {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{data}'}},
                ],
            }
        ],
    }
    response = httpx.post(
        ENDPOINT,
        json=body,
        timeout=120.0,
        headers={
            'Authorization': f'Bearer {key}',
            'X-Title': 'Northwind FNOL controlled corpus image check',
        },
    )
    if response.status_code != 200:
        raise RuntimeError(
            f'OpenRouter answered HTTP {response.status_code}: {response.text[:200]}'
        )
    reply = response.json()
    return json.loads(reply['choices'][0]['message']['content']), reply.get('usage', {})


def _secret_key() -> tuple[str, str]:
    if os.path.exists(KEY_FILE):
        return Path(KEY_FILE).read_text(encoding='utf-8').strip(), 'key file'
    if os.environ.get('CORPUS_OPENROUTER_KEY'):
        return os.environ['CORPUS_OPENROUTER_KEY'].strip(), 'environment'
    token = subprocess.run(
        ['gh', 'auth', 'token'], capture_output=True, text=True, timeout=10
    ).stdout.strip()
    if not token:
        sys.exit(
            'No key file, no CORPUS_OPENROUTER_KEY, and no gh login for the team secrets bundle.'
        )
    # Same client as backend/core/dev_secrets.py; the endpoint rejects urllib's default agent.
    response = httpx.get(
        SECRETS_ENDPOINT, headers={'Authorization': f'Bearer {token}'}, timeout=15.0
    )
    if response.status_code != 200:
        sys.exit(f'The team secrets endpoint answered HTTP {response.status_code}.')
    for line in response.text.splitlines():
        match = re.match(r'^NORTHWIND_MODEL_API_KEY=(.*)$', line)
        if match:
            return match.group(1).strip(), 'team development secrets'
    sys.exit('The team secrets bundle has no NORTHWIND_MODEL_API_KEY.')


def _ask(
    key: str, image_path: str, purpose: str, facts: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    data = base64.b64encode(Path(image_path).read_bytes()).decode()
    body = {
        'model': MODEL,
        'temperature': 0,
        'response_format': {'type': 'json_object'},
        'messages': [
            {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': QUESTION.format(purpose=purpose, facts=facts)},
                    {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{data}'}},
                ],
            }
        ],
    }
    response = httpx.post(
        ENDPOINT,
        json=body,
        timeout=120.0,
        headers={
            'Authorization': f'Bearer {key}',
            'X-Title': 'Northwind FNOL controlled corpus image check',
        },
    )
    if response.status_code != 200:
        raise RuntimeError(
            f'OpenRouter answered HTTP {response.status_code}: {response.text[:200]}'
        )
    reply = response.json()
    return json.loads(reply['choices'][0]['message']['content']), reply.get('usage', {})


BROKEN_TRANSFORMS = {'truncate', 'to_tiff'}


def _todo(record: dict[str, Any], key: str, sha: str, inputs_sha: str | None = None) -> bool:
    "True when this pass has no current result for the image (and facts), so it must be (re)run."
    item = record.get(key)
    if not item or item.get('sha256') != sha:
        return True
    return inputs_sha is not None and item.get('inputs_sha256') != inputs_sha


def _review_records(corpus: str, case_id: str) -> dict[str, dict[str, Any]]:
    path = os.path.join(corpus, 'cases', case_id, 'review.json')
    if not os.path.exists(path):
        return {}
    return {
        r['file']: r for r in json.loads(Path(path).read_text(encoding='utf-8')).get('images', [])
    }


def blind(corpus: str, only: set[str]) -> None:
    """Image only, no facts and no purpose, so the answers are not led by what the pack expects.

    The answers are stored as `model_blind` for a person (or the assistant) to compare with the
    fact sheet; this pass does not decide pass or fail by itself.
    """
    key, source = _secret_key()
    print(f'blind pass, model: {MODEL}; key from {source} (not shown)')
    for case_id in sorted(os.listdir(os.path.join(corpus, 'cases'))):
        if only and case_id not in only:
            continue
        case_dir = os.path.join(corpus, 'cases', case_id)
        provenance = json.loads(
            Path(os.path.join(case_dir, 'provenance.json')).read_text(encoding='utf-8')
        )['materials']
        for material in provenance:
            if material.get('evidence_kind') not in IMAGE_KINDS:
                continue
            path = os.path.join(case_dir, 'input', 'materials', material['file'])
            if material.get('inputs', {}).get('transform') in BROKEN_TRANSFORMS:
                print(
                    f'== {case_id} {material["file"]}: deliberately broken file, not sent; '
                    'a person checks it'
                )
                continue
            current = _review_records(corpus, case_id).get(material['file'], {})
            if (
                not _todo(current, 'model_blind', image_review.sha256(path))
                and current['model_blind'].get('question_version')
                == image_review.BLIND_QUESTION_VERSION
            ):
                continue
            try:
                answers, usage = _ask_blind(key, path)
            except (RuntimeError, httpx.HTTPError, ValueError) as error:
                print(f'== {case_id} {material["file"]}: FAILED {error}')
                continue
            review_tool._record(
                corpus,
                case_id,
                material['file'],
                'model_blind',
                {
                    'by': f'{MODEL} via OpenRouter, image only',
                    'result': 'described',
                    'question_version': image_review.BLIND_QUESTION_VERSION,
                    'answers': answers,
                    'tokens': usage.get('total_tokens'),
                },
            )
            print(f'== {case_id} {material["file"]}')
            for k in (
                'description',
                'what_is_damaged',
                'damage',
                'damage_extent',
                'colours',
                'setting',
                'licence_plate',
                'brand_logo',
                'people',
                'readable_text',
            ):
                print(f'   {k}: {answers.get(k)}')


def main() -> None:
    args = sys.argv[1:]
    if '--blind' in args:
        args.remove('--blind')
        return blind(args[0], set(args[1:]))
    corpus, only = args[0], set(args[1:])
    key, source = _secret_key()
    print(f'model: {MODEL}; key from {source} (not shown)')
    for case_id in sorted(os.listdir(os.path.join(corpus, 'cases'))):
        if only and case_id not in only:
            continue
        case_dir = os.path.join(corpus, 'cases', case_id)
        facts = json.loads(
            Path(os.path.join(case_dir, 'input', 'facts.json')).read_text(encoding='utf-8')
        )['facts']
        provenance = json.loads(
            Path(os.path.join(case_dir, 'provenance.json')).read_text(encoding='utf-8')
        )['materials']
        for material in provenance:
            if material.get('evidence_kind') not in IMAGE_KINDS:
                continue
            path = os.path.join(case_dir, 'input', 'materials', material['file'])
            if material.get('inputs', {}).get('transform') in BROKEN_TRANSFORMS:
                print(
                    f'  {case_id} {material["file"]}: deliberately broken file, not sent; '
                    'a person checks it'
                )
                continue
            inputs_sha = image_review.prompt_inputs_sha256(material['purpose'], facts)
            if not _todo(
                _review_records(corpus, case_id).get(material['file'], {}),
                'model_check',
                image_review.sha256(path),
                inputs_sha,
            ):
                continue
            try:
                answers, usage = _ask(key, path, material['purpose'], image_review.fact_text(facts))
            except (RuntimeError, httpx.HTTPError, ValueError) as error:
                print(f'  {case_id} {material["file"]}: FAILED {error}')
                continue
            # Whether the image goes to a person is decided by image_review.py
            # (`review_tool.py flags`), not here. The facts hash makes this pass stale when the
            # fact sheet changes.
            record = {
                'by': f'{MODEL} via OpenRouter',
                'result': 'recorded',
                'answers': answers,
                'inputs_sha256': image_review.prompt_inputs_sha256(material['purpose'], facts),
                'tokens': usage.get('total_tokens'),
            }
            review_tool._record(corpus, case_id, material['file'], 'model_check', record)
            print(
                f'  {case_id} {material["file"]}: matches={answers.get("matches_facts")} '
                f'| extent={answers.get("damage_extent")} | plate={answers.get("licence_plate")} '
                f'| people={answers.get("people")} | notes={answers.get("notes")}'
            )


if __name__ == '__main__':
    main()
