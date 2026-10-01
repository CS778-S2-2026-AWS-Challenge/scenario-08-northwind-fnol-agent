"""Record image reviews and produce the sign-off sheet.

Usage:
  python -m tests.corpus.tools.review_tool sheet CORPUS_DIR OUT.html [--needed]
  python -m tests.corpus.tools.review_tool flags CORPUS_DIR
  python -m tests.corpus.tools.review_tool sample CORPUS_DIR --seed N
  python -m tests.corpus.tools.review_tool release CORPUS_DIR --by @github-login
  python -m tests.corpus.tools.review_tool assist CORPUS_DIR CASE_ID FILE accepted|rejected "note"
  python -m tests.corpus.tools.review_tool sign CORPUS_DIR CASE_ID FILE accepted|rejected "note"
      --by @github-login   (one command; the person who looked at the image)

Records per image in the pack's review.json, each with the image's SHA-256:
- model_blind, model_check: the two gpt-4o passes (model_check.py);
- model_flag: the result of the fixed flag rule;
- assistant_check: a first pass by the assistant;
- human_signoff: the decision of a named person, with its method, material slot, categories and
  whether it was sampled (image_review.py); a replaced sign-off moves to signoff_history, so a
  rejection is never lost.

Workflow for a bulk corpus: run both model passes, then `flags`, `sample`, sign every flagged and
every sampled image with `sign`, then `release` the rest of each clean category.
"""

import base64
import html
import json
import os
import sys
from datetime import UTC, datetime
from typing import Any, cast

from tests.corpus.tools import image_review

CHECKLIST = [
    'Shows what the fact sheet says: same object, colour, position and extent of damage',
    'No readable plate, no plate that looks non-New Zealand, no real brand logo',
    'No face, no real street sign, no readable text',
    'Looks like an ordinary phone photo a claimant could take',
]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec='seconds')


def _paths(corpus: str, case_id: str) -> tuple[str, str]:
    case_dir = os.path.join(corpus, 'cases', case_id)
    return case_dir, os.path.join(case_dir, 'review.json')


def _load(review_path: str, case_id: str) -> dict[str, Any]:
    if os.path.exists(review_path):
        with open(review_path, encoding='utf-8') as f:
            return cast(dict[str, Any], json.load(f))
    return {'case_id': case_id, 'images': []}


def _write_manifest(corpus: str) -> None:
    # Keep the manifest hash covering the review records and sampling.json.
    from tests.corpus.tools import build_pack

    build_pack.write_manifest(corpus, quiet=True)


def _record(
    corpus: str, case_id: str, file: str, key: str, record: dict[str, Any], quiet: bool = False
) -> None:
    case_dir, review_path = _paths(corpus, case_id)
    image_path = os.path.join(case_dir, 'input', 'materials', file)
    if not os.path.exists(image_path):
        sys.exit(f'no such image: {image_path}')
    review = _load(review_path, case_id)
    entry = next((i for i in review['images'] if i['file'] == file), None)
    if entry is None:
        entry = {'file': file}
        review['images'].append(entry)
    record['sha256'] = image_review.sha256(image_path)
    record['utc'] = _now()
    if key == 'human_signoff' and entry.get('human_signoff'):
        entry.setdefault('signoff_history', []).append(entry['human_signoff'])
    entry[key] = record
    with open(review_path, 'w', encoding='utf-8') as f:
        json.dump(review, f, indent=1, ensure_ascii=False)
    _write_manifest(corpus)
    if not quiet:
        print(f'{case_id} {file}: {key} = {record["result"]}')


def _answers_html(item: dict[str, Any] | None, current: str, keys: tuple[str, ...]) -> str:
    if not item:
        return 'none'
    stale = '' if item.get('sha256') == current else ' <b>(STALE: image changed since)</b>'
    answers = item.get('answers', {})
    parts = [f'{k}: {html.escape(json.dumps(answers.get(k), ensure_ascii=False))}' for k in keys]
    return f'{stale}<br>{html.escape(str(answers.get("description", "")))}<br>' + '<br>'.join(parts)


def sheet(corpus: str, out_path: str, needed_only: bool = False) -> None:
    images = image_review.corpus_images(corpus)
    groups = image_review.by_hash(images)
    sampling = image_review.load_sampling(corpus)
    sampled: set[str] = {r['sha256'] for r in sampling['sample']} if sampling else set()

    def rank(image: dict[str, Any]) -> int:
        # Flagged first, then sampled, then the images sampling may release; folder order within
        # each.
        return 0 if groups[image['sha256']]['reasons'] else 1 if image['sha256'] in sampled else 2

    ordered = sorted(images, key=rank)
    counts = [sum(1 for i in images if rank(i) == r) for r in range(3)]
    if needed_only:
        ordered = [i for i in ordered if rank(i) < 2]
    blocks, index = [], []
    for number, image in enumerate(ordered, 1):
        case_dir, _ = _paths(corpus, image['case_id'])
        with open(os.path.join(case_dir, 'input', 'facts.json'), encoding='utf-8') as f:
            facts = json.load(f)['facts']
        path = os.path.join(case_dir, 'input', 'materials', image['file'])
        with open(path, 'rb') as image_file:
            data = base64.b64encode(image_file.read()).decode()
        rec, current = image['review'], image['sha256']
        reasons = groups[current]['reasons']
        need = (
            'person must look: flagged'
            if reasons
            else 'person must look: sampled'
            if current in sampled
            else 'released by sampling if its category is clean'
        )
        if rank(image) < 2:
            index.append(
                f'<li><a href="#n{number}">#{number}</a> {image["case_id"]} / '
                f'{html.escape(image["file"])}'
                f' ({"flagged" if reasons else "sampled"})</li>'
            )
        hints = ''.join(
            f'<li><b>{html.escape(k)}</b>: '
            f'{html.escape(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))}</li>'
            for k, v in ((k, facts[k]) for k in image_review.FACT_HINTS if k in facts)
        )
        signoff = rec.get('human_signoff')
        signoff_html = (
            'none'
            if not signoff
            else (
                f'{signoff["result"]} by {html.escape(signoff["by"])}, '
                f'method {signoff.get("method")}'
                f'{"" if signoff.get("sha256") == current else " <b>(STALE)</b>"}'
                f' - {html.escape(signoff.get("note", ""))}'
            )
        )
        checks = ''.join(f'<li>{html.escape(c)}</li>' for c in CHECKLIST)
        reason_html = (
            '<ul>' + ''.join(f'<li>{html.escape(r)}</li>' for r in reasons) + '</ul>'
            if reasons
            else 'none'
        )
        blocks.append(
            '\n'
            f'<section id="n{number}">\n'
            f' <h2>#{number} {image["case_id"]} / {html.escape(image["file"])}'
            f' ({html.escape(str(image["category"]))})</h2>\n'
            f' <img src="data:image/jpeg;base64,{data}" alt="{html.escape(image["file"])}">\n'
            f' <p><b>Status:</b> {need}</p>\n'
            f' <p><b>Flag reasons:</b> {reason_html}</p>\n'
            f' <p><b>Purpose:</b> {html.escape(image["entry"].get("purpose", ""))}</p>\n'
            f' <p><b>SHA-256:</b> <code>{current[:16]}...</code></p>\n'
            f' <p><b>Relevant facts:</b></p><ul>{hints}</ul>\n'
            f' <p><b>Check:</b></p><ol>{checks}</ol>\n'
            f' <p><b>gpt-4o, image only:</b> {
                _answers_html(
                    rec.get("model_blind"),
                    current,
                    (
                        "what_is_damaged",
                        "damage",
                        "licence_plate",
                        "people",
                        "brand_logo",
                        "readable_text",
                    ),
                )
            }</p>\n'
            f' <p><b>gpt-4o, with facts:</b> {
                _answers_html(
                    rec.get("model_check"),
                    current,
                    (
                        "matches_facts",
                        "mismatches",
                        "licence_plate",
                        "people",
                        "brand_logo",
                        "readable_text",
                        "notes",
                    ),
                )
            }</p>\n'
            f' <p><b>Human sign-off:</b> {signoff_html}</p>\n'
            '</section>'
        )
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<title>Image sign-off sheet</title>\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<style>\n'
        ':root { --bg:#fff; --fg:#1a1a1a; --muted:#555; --line:#ddd; }\n'
        '@media (prefers-color-scheme: dark) '
        '{ :root { --bg:#161616; --fg:#eee; --muted:#aaa; --line:#333; } }\n'
        'body { background:var(--bg); color:var(--fg); font:15px/1.5 system-ui, sans-serif; '
        'margin:0 auto; max-width:900px; padding:16px; }\n'
        'section { border-top:1px solid var(--line); padding:12px 0 20px; }\n'
        'img { max-width:100%; height:auto; border:1px solid var(--line); }\n'
        'code { color:var(--muted); }\n'
        '</style></head><body>\n'
        '<h1>Image sign-off sheet</h1>\n'
        f'<p>Corpus: <code>{html.escape(os.path.abspath(corpus))}</code>. Generated {_now()}.</p>\n'
        '<p>For each image marked "person must look", check the four points against the facts, '
        'then tell the maintainer "accepted" or "rejected" with a reason, by number '
        '(for example "#3 rejected: plate readable").</p>\n'
        f'<p>{counts[0]} flagged, {counts[1]} sampled: {counts[0] + counts[1]} images need a '
        f'person. {counts[2]} more are released by sampling if no sampled image of their category '
        'is rejected'
        f'{" (not shown in this sheet)" if needed_only else " (listed after the numbered ones)"}'
        '.</p>\n'
        f'<ol style="list-style:none;padding:0">{"".join(index)}</ol>\n'
        f'{"".join(blocks)}\n'
        '</body></html>'
    )
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(page)
    print(f'sheet: {len(blocks)} images -> {out_path}')


def flags(corpus: str) -> None:
    """Rule 1: print and record which images a person must look at (decided per image hash)."""
    images = image_review.corpus_images(corpus)
    groups = image_review.by_hash(images)
    for image in images:
        reasons = groups[image['sha256']]['reasons']
        _record(
            corpus,
            image['case_id'],
            image['file'],
            'model_flag',
            {'result': 'flagged' if reasons else 'clean', 'reasons': reasons},
            quiet=True,
        )
        print(
            f'{"FLAGGED" if reasons else "clean  "} {image["case_id"]} {image["file"]}'
            + (': ' + '; '.join(reasons) if reasons else '')
        )


def sample(corpus: str, seed: int) -> None:
    """Rule 2: draw the one sample of this corpus version and record it in sampling.json."""
    path = os.path.join(corpus, image_review.SAMPLING_FILE)
    if os.path.exists(path):
        sys.exit(
            'sampling.json already exists: a corpus version has one draw. '
            'Images added later are signed per image.'
        )
    images = image_review.corpus_images(corpus)
    for _, entry in image_review.all_review_entries(corpus):
        for item in [entry.get('human_signoff')] + entry.get('signoff_history', []):  # noqa: RUF005  [x] + h raises TypeError on a non-list h; [x, *h] would not
            if item and (item.get('sampled') or item.get('method') == 'model_check_with_sampling'):
                sys.exit(
                    'an earlier draw was already used in this corpus (sign-offs refer to it); '
                    'start a new corpus version instead of drawing again'
                )
    population = image_review.population_rows(images, image_review.signoffs_by_hash(images))
    drawn: dict[str, Any] = {
        'rule': 'at least 10% of unflagged, unsigned image hashes, '
        'at least one per scenario category',
        'seed': seed,
        'population': population,
        'sample': image_review.draw_rows(population, seed),
        'created_utc': _now(),
    }
    drawn['draw_sha256'] = image_review.draw_sha256(drawn)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(drawn, f, indent=1)
    _write_manifest(corpus)
    print(f'sample: {len(drawn["sample"])} of {len(population)} unflagged image hashes')
    for row in drawn['sample']:
        print(f'  {",".join(row["categories"])} {row["case_id"]} {row["file"]}')


def release(corpus: str, by: str) -> None:
    """Rules 2 and 4: release the unsampled, unflagged images of every clean category."""
    images = image_review.corpus_images(corpus)
    sampling = image_review.load_sampling(corpus)
    if sampling is None:
        sys.exit('no sampling.json; run `sample` first')
    groups = image_review.by_hash(images)
    problems = image_review.sampling_problems(sampling, groups)
    if problems:
        sys.exit('; '.join(problems))
    signoffs = image_review.signoffs_by_hash(images)
    escalated, rejected_slots = image_review.rejection_state(corpus, images)
    status = image_review.category_status(sampling, signoffs, escalated)
    population = {r['sha256'] for r in sampling['population']}
    sampled = {r['sha256'] for r in sampling['sample']}
    released = set()
    for image in images:
        sha, group = image['sha256'], groups[image['sha256']]
        if (
            sha in signoffs
            or sha in released
            or sha in sampled
            or sha not in population
            or group['reasons']
            or any((c['case_id'], c['material_id']) in rejected_slots for c in group['copies'])
            or any(status.get(c) != 'clean' for c in group['categories'])
        ):
            continue
        _record(
            corpus,
            image['case_id'],
            image['file'],
            'human_signoff',
            {
                'by': by,
                'result': 'accepted',
                'method': 'model_check_with_sampling',
                'material_id': image['material_id'],
                'categories': sorted(group['categories']),
                'sampled': False,
                'note': 'Released: model check clean; the '
                f'{", ".join(sorted(group["categories"]))} '
                'sample was all accepted per image.',
                'draw_sha256': sampling['draw_sha256'],
            },
            quiet=True,
        )
        released.add(sha)
    print(f'released {len(released)} image hashes; category status: {status}')


def sign(corpus: str, case_id: str, file: str, result: str, note: str, by: str) -> None:
    images = image_review.corpus_images(corpus)
    target = next((i for i in images if i['case_id'] == case_id and i['file'] == file), None)
    if target is None:
        sys.exit(f'no such image: {case_id} {file}')
    signoffs = image_review.signoffs_by_hash(images)
    existing = signoffs.get(target['sha256'])
    if existing:
        sys.exit(
            f'this image hash is already signed off ({existing[0]["result"]} by '
            f'{existing[0]["by"]}); a hash is signed once'
        )
    group = image_review.by_hash(images)[target['sha256']]
    sampling = image_review.load_sampling(corpus)
    sampled = bool(sampling) and target['sha256'] in {
        r['sha256'] for r in cast(dict[str, Any], sampling)['sample']
    }
    # The record carries what the rules need later: the whole hash's categories, whether it was in
    # the sample (a rejected sampled image escalates those categories), and the material slot.
    _record(
        corpus,
        case_id,
        file,
        'human_signoff',
        {
            'by': by,
            'result': result,
            'note': note,
            'method': 'per_image',
            'material_id': target['material_id'],
            'categories': sorted(group['categories']),
            'sampled': sampled,
        },
    )
    if result == 'rejected' and sampled:
        print(
            f'categories {sorted(group["categories"])} escalated: '
            'every image in them is signed off per image'
        )


def main() -> None:
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    command = args[0]
    if command == 'sheet':
        sheet(args[1], args[2], needed_only='--needed' in args)
    elif command == 'flags':
        flags(args[1])
    elif command == 'sample':
        if '--seed' not in args:
            sys.exit('sample needs --seed N, recorded so the draw can be repeated')
        sample(args[1], int(args[args.index('--seed') + 1]))
    elif command == 'release':
        if '--by' not in args:
            sys.exit('release needs --by @github-login of the person who reviewed the sample')
        release(args[1], args[args.index('--by') + 1])
    elif command in ('assist', 'sign'):
        corpus, case_id, file, result, note = args[1:6]
        if result not in ('accepted', 'rejected'):
            sys.exit('result must be accepted or rejected')
        if command == 'assist':
            _record(
                corpus,
                case_id,
                file,
                'assistant_check',
                {'by': 'Claude (assistant)', 'result': result, 'note': note},
            )
        else:
            if '--by' not in args:
                sys.exit('sign needs --by @github-login of the person who looked at the image')
            sign(corpus, case_id, file, result, note, args[args.index('--by') + 1])
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
