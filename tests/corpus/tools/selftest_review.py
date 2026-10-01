"""Walk every loophole the third and fourth audits found in the image sign-off rules, \
on copies of samples 0.2."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from typing import Any, cast

from tests.corpus.tools import corpus_paths, image_review

TOOLS = os.path.dirname(os.path.abspath(__file__))
# The 0.2 samples, fetched next to the tools; CORPUS_SAMPLES overrides the location.
SRC = os.environ.get('CORPUS_SAMPLES') or corpus_paths.SAMPLES
BASE = tempfile.mkdtemp(prefix='review-selftest-')

FAILURES: list[str] = []
COUNT = [0]


def fresh(strip_signoffs: bool = True) -> str:
    COUNT[0] += 1
    work = os.path.join(BASE, str(COUNT[0]))
    shutil.copytree(SRC, work)
    if strip_signoffs:
        for case in os.listdir(os.path.join(work, 'cases')):
            path = os.path.join(work, 'cases', case, 'review.json')
            with open(path) as f:
                data = json.load(f)
            for image in data['images']:
                image.pop('human_signoff', None)
            with open(path, 'w') as f:
                json.dump(data, f, indent=1)
    return work


def tool(*args: str) -> tuple[int, str]:
    out = subprocess.run(
        [sys.executable, '-m', 'tests.corpus.tools.review_tool', *args],
        cwd=corpus_paths.REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return out.returncode, out.stdout + out.stderr


def check(work: str) -> str:
    out = subprocess.run(
        [sys.executable, '-m', 'tests.corpus.tools.check_corpus', work, '--freeze'],
        cwd=corpus_paths.REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return out.stdout


def expect(name: str, condition: bool, detail: str = '') -> None:
    print(('OK     ' if condition else 'MISSED ') + name)
    if not condition:
        FAILURES.append(name)
        print(detail[:3000])


def sampled(work: str) -> list[dict[str, Any]]:
    with open(os.path.join(work, 'sampling.json')) as f:
        return cast(list[dict[str, Any]], json.load(f)['sample'])


def sign_sample(work: str, reject_category: str | None = None) -> None:
    for row in sampled(work):
        result = 'rejected' if reject_category in row['categories'] else 'accepted'
        tool('sign', work, row['case_id'], row['file'], result, 'selftest', '--by', '@tester')


def sign_flagged(work: str, result: str = 'accepted') -> None:
    images = image_review.corpus_images(work)
    groups = image_review.by_hash(images)
    for image in images:
        if groups[image['sha256']]['reasons']:
            tool(
                'sign', work, image['case_id'], image['file'], result, 'selftest', '--by', '@tester'
            )


def touch_image(path: str) -> None:
    with open(path, 'ab') as f:
        f.write(b'\x00')  # a different hash; the JPEG still decodes


def released(work: str, case_id: str, file: str) -> bool:
    for image in image_review.corpus_images(work):
        if image['case_id'] == case_id and image['file'] == file:
            item = image['review'].get('human_signoff')
            return bool(
                item
                and item.get('sha256') == image['sha256']
                and item.get('method') == 'model_check_with_sampling'
            )
    return False


def clone_pack(work: str, source: str, target: str, category: str | None = None) -> None:
    shutil.copytree(os.path.join(work, 'cases', source), os.path.join(work, 'cases', target))
    os.remove(os.path.join(work, 'cases', target, 'review.json'))
    if category:
        path = os.path.join(work, 'cases', target, 'oracle', 'labels.json')
        with open(path) as f:
            data = json.load(f)
        data['scenario_category'] = category
        with open(path, 'w') as f:
            json.dump(data, f, indent=1)
    with open(os.path.join(work, 'cases', source, 'review.json')) as f:
        src_review = json.load(f)
    for entry in src_review['images']:
        entry.pop('human_signoff', None)
    with open(os.path.join(work, 'cases', target, 'review.json'), 'w') as f:
        json.dump(src_review, f, indent=1)


# 1. Happy path.
w = fresh()
tool('sample', w, '--seed', '7')
sign_sample(w)
sign_flagged(w)
code, out = tool('release', w, '--by', '@tester')
report = check(w)
expect(
    'happy path passes the freeze review rules',
    'review:' not in report and 'FAIL sampling' not in report,
    out + report,
)

# 2. One draw per version: a second draw is refused, even after deleting sampling.json.
code, out = tool('sample', w, '--seed', '8')
expect('second draw is refused', code != 0 and 'one draw' in out, out)
os.remove(os.path.join(w, 'sampling.json'))
code, out = tool('sample', w, '--seed', '8')
expect(
    'a draw after deleting sampling.json is refused',
    code != 0 and 'earlier draw was already used' in out,
    out,
)

# 3. A rejected sampled image escalates its category; release skips it; freeze fails the rest.
w = fresh()
tool('sample', w, '--seed', '7')
sign_sample(w, reject_category='M1')
sign_flagged(w)
code, out = tool('release', w, '--by', '@tester')
report = check(w)
expect(
    'rejected sample escalates its category',
    "'M1': 'escalated'" in out and 'category M1 is' not in report and 'photo-' in report,
    out + report,
)

# 4. Regenerating the rejected image, even under a new file name, keeps its slot per image.
rejected_row = next(r for r in sampled(w) if 'M1' in r['categories'])
case_dir = os.path.join(w, 'cases', rejected_row['case_id'])
old_file = rejected_row['file']
new_file = old_file.replace('.jpg', '-v2.jpg')
os.rename(
    os.path.join(case_dir, 'input', 'materials', old_file),
    os.path.join(case_dir, 'input', 'materials', new_file),
)
touch_image(os.path.join(case_dir, 'input', 'materials', new_file))
for name in ('provenance.json', os.path.join('input', 'materials.json')):
    path = os.path.join(case_dir, name)
    with open(path) as f:
        data = json.load(f)
    for m in data['materials']:
        if m['file'] == old_file:
            m['file'] = new_file
            if 'sha256' in m:
                m['sha256'] = image_review.sha256(
                    os.path.join(case_dir, 'input', 'materials', new_file)
                )
    with open(path, 'w') as f:
        json.dump(data, f, indent=1)
code, out = tool('release', w, '--by', '@tester')
expect(
    'renamed replacement of a rejected image is not released',
    not released(w, rejected_row['case_id'], new_file),
    out,
)

# 5. Rejecting a flagged (not sampled) image does not escalate its category.
w = fresh()
tool('sample', w, '--seed', '7')
sign_sample(w)
sign_flagged(w, result='rejected')
code, out = tool('release', w, '--by', '@tester')
expect('rejecting a flagged image does not escalate', "'H3': 'escalated'" not in out, out)

# 6. An image added after the draw is not released.
w = fresh()
tool('sample', w, '--seed', '7')
sign_sample(w)
sign_flagged(w)
clone_pack(w, 'CTL-C-002', 'CTL-C-003')
touch_image(os.path.join(w, 'cases', 'CTL-C-003', 'input', 'materials', 'photo-tv-screen.jpg'))
tool('release', w, '--by', '@tester')
expect(
    'image added after the draw is not released',
    not released(w, 'CTL-C-003', 'photo-tv-screen.jpg'),
)

# 7. Editing sampling.json is caught, and releases stop counting.
w = fresh()
tool('sample', w, '--seed', '7')
sign_sample(w)
sign_flagged(w)
tool('release', w, '--by', '@tester')
path = os.path.join(w, 'sampling.json')
with open(path) as f:
    data = json.load(f)
data['sample'] = data['sample'][:-1]
with open(path, 'w') as f:
    json.dump(data, f, indent=1)
report = check(w)
expect(
    'edited sampling.json is caught',
    'draw has been edited' in report and 'not by the draw recorded' in report,
    report,
)

# 8. A population row with wrong categories is caught.
w = fresh()
tool('sample', w, '--seed', '7')
path = os.path.join(w, 'sampling.json')
with open(path) as f:
    data = json.load(f)
data['population'][0]['categories'] = ['M1', 'M2']
data['draw_sha256'] = image_review.draw_sha256(data)
with open(path, 'w') as f:
    json.dump(data, f, indent=1)
report = check(w)
expect(
    'population categories that differ from the corpus are caught',
    'is recorded with categories' in report,
    report,
)

# 9. One image in two categories: a sampled rejection escalates both.
w = fresh()
clone_pack(w, 'CTL-M-001', 'CTL-M-002', category='M2')
tool('sample', w, '--seed', '3')
rows = sampled(w)
shared = next((r for r in rows if set(r['categories']) == {'M1', 'M2'}), None)
if shared is None:
    expect('shared image sampled (setup)', False, json.dumps(rows))
else:
    tool('sign', w, shared['case_id'], shared['file'], 'rejected', 'selftest', '--by', '@tester')
    code, out = tool('release', w, '--by', '@tester')
    expect(
        'rejection of a shared image escalates every category it is in',
        "'M1': 'escalated'" in out and "'M2': 'escalated'" in out,
        out,
    )

# 10. Two current sign-offs for one hash fail the freeze.
w = fresh(strip_signoffs=False)
shutil.copytree(os.path.join(w, 'cases', 'CTL-M-001'), os.path.join(w, 'cases', 'CTL-M-002'))
path = os.path.join(w, 'cases', 'CTL-M-002', 'review.json')
with open(path) as f:
    data = json.load(f)
next(i for i in data['images'] if i['file'] == 'photo-bollard.jpg')['human_signoff']['result'] = (
    'rejected'
)
with open(path, 'w') as f:
    json.dump(data, f, indent=1)
report = check(w)
expect(
    'two sign-offs for one hash fail the freeze',
    'current sign-offs for one image hash' in report,
    report,
)

# 11-16. Flag rule edge cases.
images = image_review.corpus_images(SRC)
tv = next(i for i in images if i['file'] == 'photo-tv-screen.jpg')
bumper = next(i for i in images if i['file'] == 'photo-rear-bumper.jpg')


def variant(image: dict[str, Any], change: Callable[[dict[str, Any]], object]) -> list[str]:
    copy = json.loads(json.dumps(image, default=list))
    change(copy)
    reasons: list[str] = image_review.copy_flag_reasons(copy)
    return reasons


expect(
    "'tv cabinet' is flagged",
    any(
        'tv cabinet' in r
        for r in variant(
            tv, lambda i: i['review']['model_blind']['answers'].update(what_is_damaged='tv cabinet')
        )
    ),
)
expect(
    "'carpet' is flagged for a bumper",
    any(
        'carpet' in r
        for r in variant(
            bumper, lambda i: i['review']['model_blind']['answers'].update(what_is_damaged='carpet')
        )
    ),
)
expect(
    "'rear bumper' is accepted",
    not variant(
        bumper,
        lambda i: i['review']['model_blind']['answers'].update(what_is_damaged='rear bumper'),
    ),
)
expect(
    "'flat-screen television' is accepted",
    not variant(
        tv,
        lambda i: i['review']['model_blind']['answers'].update(
            what_is_damaged='flat-screen television'
        ),
    ),
)
expect(
    'missing privacy answer is flagged',
    any(
        'people is missing' in r
        for r in variant(bumper, lambda i: i['review']['model_blind']['answers'].pop('people'))
    ),
)
expect(
    "plate 'none, but an edge' is flagged",
    any(
        'licence plate' in r
        for r in variant(
            bumper,
            lambda i: i['review']['model_check']['answers'].update(
                licence_plate='none, but a white edge at the right'
            ),
        )
    ),
)
expect(
    'changed facts make the pass with facts stale',
    any(
        'facts changed' in r for r in variant(bumper, lambda i: i.update(inputs_sha256='different'))
    ),
)

shutil.rmtree(BASE, ignore_errors=True)
print(f'{len(FAILURES)} missed')
sys.exit(1 if FAILURES else 0)
