"""Mutate copies of the 0.2 samples and confirm the checker catches each planted error."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from typing import Any, cast

from tests.corpus.tools import corpus_paths

TOOLS = os.path.dirname(os.path.abspath(__file__))
# The 0.2 samples, fetched next to the tools; CORPUS_SAMPLES overrides the location.
SRC = os.environ.get('CORPUS_SAMPLES') or corpus_paths.SAMPLES

BASE = tempfile.mkdtemp(prefix='selftest-')
WORK: str | None = None
COUNTER = [0]


def fresh() -> None:
    global WORK
    COUNTER[0] += 1
    WORK = os.path.join(BASE, str(COUNTER[0]))
    shutil.copytree(SRC, WORK)


def labels(case: str) -> str:
    return os.path.join(cast(str, WORK), 'cases', case, 'oracle', 'labels.json')


def edit(path: str, change: Callable[[dict[str, Any]], object]) -> None:
    with open(path, encoding='utf-8') as f:
        data: dict[str, Any] = json.load(f)
    change(data)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1)


def run(*extra: str) -> tuple[int, str]:
    out = subprocess.run(
        [sys.executable, '-m', 'tests.corpus.tools.check_corpus', cast(str, WORK), *extra],
        cwd=corpus_paths.REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return out.returncode, out.stdout


CASES: list[tuple[str, str, Callable[[dict[str, Any]], object], str]] = [
    (
        'innocent control labelled as flagged',
        'CTL-C-002',
        lambda o: o['review_indicators'].update(expected_fraud_signal='review_required'),
        "expected_fraud_signal='review_required' but the checks give 'none'",
    ),
    (
        'strong hit relabelled clear',
        'CTL-C-001',
        lambda o: o['review_indicators']['checks']['ownership_doc_after_loss'].update(
            expected='clear'
        ),
        "ownership_doc_after_loss is labelled 'clear' but the pack gives 'hit'",
    ),
    (
        'class without a reason',
        'CTL-M-001',
        lambda o: o['triage'].update(expected_class='standard'),
        "expected_class='standard' but the required reasons give 'fast_track'",
    ),
    (
        'flag without the escalation reason',
        'CTL-C-001',
        lambda o: o['triage'].update(
            required_reasons=['inconsistency_unresolved'], expected_class='standard'
        ),
        'the checks imply reason review_indicator_escalated',
    ),
    (
        'non-registry expected fact',
        'CTL-H-001',
        lambda o: o['expected_facts'].update({'property.occupancy_type': 'owner'}),
        'property.occupancy_type is not a Field Registry code',
    ),
    (
        'enum value outside the registry',
        'CTL-C-001',
        lambda o: o['expected_facts'].update({'theft.entry_context': 'forced'}),
        "theft.entry_context='forced' is not an allowed value",
    ),
    (
        'unchecked check labelled clear',
        'CTL-M-001',
        lambda o: o['review_indicators']['checks']['policy_inception_30d'].update(expected='clear'),
        'policy_inception_30d needs policy_inception_date',
    ),
    (
        'bad assertion operator',
        'CTL-M-001',
        lambda o: o['assertions'].append(
            {
                'id': 'X1',
                'kind': 'required',
                'judge': 'state',
                'path': 'claimant:claim.x',
                'op': 'looks_like',
            }
        ),
        'X1 needs a path and an op',
    ),
]


def main() -> None:
    failures = 0
    # out holds checker stdout, except once where it holds the review_tool.py process result.
    out: str | subprocess.CompletedProcess[str]
    for name, case, change, expect in CASES:
        fresh()
        edit(labels(case), change)
        code, out = run()
        caught = code == 1 and expect in out
        failures += not caught
        print(('CAUGHT ' if caught else 'MISSED ') + name)
        if not caught:
            print(out)
    # Policy removed from the system without the lookup reason.
    fresh()
    edit(
        os.path.join(cast(str, WORK), 'cases', 'CTL-M-001', 'setup.json'),
        lambda s: s.update(policies_in_system=[]),
    )
    code, out = run()
    caught = (
        code == 1
        and 'policy_lookup_failed must be required' in out
        and "value_if_data is 'clear' but the rule gives 'not_checked'" in out
    )
    failures += not caught
    print(('CAUGHT ' if caught else 'MISSED ') + 'policy missing from the system')
    # A policy with an uncertainty marker needs coverage_unclear.
    fresh()
    edit(
        os.path.join(cast(str, WORK), 'cases', 'CTL-M-001', 'setup.json'),
        lambda s: s['policies_in_system'][0].update(uncertainty=['COVERAGE_SECTION_INCOMPLETE']),
    )
    code, out = run()
    caught = code == 1 and 'coverage_unclear must be required' in out
    failures += not caught
    print(('CAUGHT ' if caught else 'MISSED ') + 'uncertainty marker without coverage_unclear')
    # Model-visible materials list leaks a purpose line.
    fresh()
    edit(
        os.path.join(cast(str, WORK), 'cases', 'CTL-H-001', 'input', 'materials.json'),
        lambda m: m['materials'][3].update(purpose='Repair quote with the totals page missing'),
    )
    code, out = run()
    caught = code == 1 and "input/materials.json exposes ['purpose']" in out
    failures += not caught
    print(('CAUGHT ' if caught else 'MISSED ') + 'purpose leaked into input/materials.json')

    def review(case: str) -> str:
        return os.path.join(cast(str, WORK), 'cases', case, 'review.json')

    def image(data: dict[str, Any], file: str) -> dict[str, Any]:
        return cast(dict[str, Any], next(i for i in data['images'] if i['file'] == file))

    def sign_rule_case(
        name: str,
        changes: list[tuple[str, Callable[[dict[str, Any]], object]]],
        expect: str,
        sampling: dict[str, Any] | None = None,
    ) -> bool:
        fresh()
        for case, change in changes:
            edit(review(case), change)
        if sampling is not None:
            with open(os.path.join(cast(str, WORK), 'sampling.json'), 'w') as f:
                json.dump(sampling, f, indent=1)
        code, out = run('--freeze')
        caught = code == 1 and expect in out
        print(('CAUGHT ' if caught else 'MISSED ') + name)
        if not caught:
            print(out)
        return not caught

    failures += sign_rule_case(
        'freeze without human sign-off',
        [('CTL-M-001', lambda d: image(d, 'photo-bollard.jpg').pop('human_signoff'))],
        'photo-bollard.jpg: no human sign-off',
    )
    failures += sign_rule_case(
        'sign-off without a method',
        [('CTL-M-001', lambda d: image(d, 'photo-bollard.jpg')['human_signoff'].pop('method'))],
        'no valid method',
    )
    failures += sign_rule_case(
        'released by sampling although the blind pass names another object',
        [
            (
                'CTL-C-002',
                lambda d: (
                    image(d, 'photo-tv-screen.jpg')['human_signoff'].update(
                        method='model_check_with_sampling'
                    ),
                    image(d, 'photo-tv-screen.jpg')['model_blind']['answers'].update(
                        what_is_damaged='glass table'
                    ),
                ),
            )
        ],
        "image-only pass names 'glass table'",
    )
    # Escalation after a rejected sample is covered, with a real draw, by selftest_review.py.
    # A hash is signed once: signing an already signed image is refused.
    fresh()
    out = subprocess.run(
        [
            sys.executable,
            '-m',
            'tests.corpus.tools.review_tool',
            'sign',
            cast(str, WORK),
            'CTL-M-001',
            'photo-bollard.jpg',
            'accepted',
            'again',
            '--by',
            '@someone',
        ],
        cwd=corpus_paths.REPO_ROOT,
        capture_output=True,
        text=True,
    )
    caught = out.returncode != 0 and 'a hash is signed once' in (out.stdout + out.stderr)
    failures += not caught
    print(('CAUGHT ' if caught else 'MISSED ') + 'second sign-off of the same hash')

    # Dates and issuers (added 2026-10-01). The 0.2 samples were built before quotes printed their
    # validity and issuer, so each case plants the field it tests.
    def provenance_case(
        name: str, case: str, change: Callable[[dict[str, Any]], object], expect: str
    ) -> bool:
        fresh()
        edit(os.path.join(cast(str, WORK), 'cases', case, 'provenance.json'), change)
        code, out = run()
        caught = code == 1 and expect in out
        print(('CAUGHT ' if caught else 'MISSED ') + name)
        if not caught:
            print(out)
        return not caught

    def quote(data: dict[str, Any]) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            next(m for m in data['materials'] if m.get('evidence_kind') == 'repair_quote'),
        )

    failures += provenance_case(
        'quote lapses before the run window ends',
        'CTL-M-001',
        lambda d: quote(d)['printed_fields'].update(valid_until='10 October 2026'),
        'must stay valid until 2026-11-30',
    )
    failures += provenance_case(
        'issuer outside the business list',
        'CTL-M-001',
        lambda d: quote(d)['printed_fields'].update(issuer='Bigname Panels Ltd'),
        'is not in the corpus business list',
    )

    def schedule(data: dict[str, Any]) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            next(m for m in data['materials'] if m.get('evidence_kind') == 'policy'),
        )

    failures += provenance_case(
        'schedule period differs from the seeded policy',
        'CTL-M-001',
        lambda d: schedule(d)['printed_fields'].update(period='1 March 2026 to 28 February 2027'),
        'differs from setup',
    )
    failures += provenance_case(
        'schedule excess differs from the seeded policy',
        'CTL-M-001',
        lambda d: schedule(d)['printed_fields'].update(excess='$999 for each event'),
        'excess_nzd',
    )
    failures += provenance_case(
        'quote total over the threshold without the amount reason',
        'CTL-M-001',
        lambda d: quote(d)['printed_fields'].update(total_incl_gst=6000.0),
        'amount_over_threshold_or_unknown must be required',
    )
    failures += provenance_case(
        'a name that only matches inside a longer word',
        'CTL-M-001',
        lambda d: quote(d)['printed_fields'].update(
            customer=quote(d)['printed_fields']['customer'] + 'son'
        ),
        'does not match policyholder.name',
    )
    failures += provenance_case(
        'boundary condition without the material made for it',
        'CTL-H-001',
        lambda d: next(m for m in d['materials'] if m['id'] == 'quote-page1')['inputs'].update(
            transform='crop'
        ),
        'condition: missing_page is labelled',
    )
    fresh()
    edit(
        os.path.join(cast(str, WORK), 'cases', 'CTL-M-001', 'setup.json'),
        lambda s: s['policies_in_system'][0].update(
            effective_from='2025-11-01', effective_to='2026-10-31'
        ),
    )
    code, out = run()
    caught = code == 1 and 'before the wording version is effective' in out
    failures += not caught
    print(
        ('CAUGHT ' if caught else 'MISSED ')
        + 'policy period starting before the wording is effective'
    )
    fresh()
    message = os.path.join(cast(str, WORK), 'cases', 'CTL-M-001', 'input', 'initial_message.txt')
    with open(message, encoding='utf-8') as f:
        text = f.read()
    with open(message, 'w', encoding='utf-8') as f:
        f.write(text + ' It was Monday 1 October 2026.')
    code, out = run()
    caught = code == 1 and "'Monday 1 October 2026' falls on a Thursday" in out
    failures += not caught
    print(('CAUGHT ' if caught else 'MISSED ') + 'weekday that does not match its date')

    # The corpus is exactly its committed manifest, every file names its pack, and only the
    # material a boundary condition was made from may fail its format check (review, 2026-10-01).
    def corpus_case(name: str, change: Callable[[str], object], expect: str) -> int:
        fresh()
        change(cast(str, WORK))
        code, out = run()
        caught = code == 1 and expect in out
        print(('CAUGHT ' if caught else 'MISSED ') + name)
        if not caught:
            print(out)
        return int(not caught)

    def pack(work: str, *parts: str) -> str:
        return os.path.join(work, 'cases', *parts)

    def broken_quote_in_a_corrupt_file_pack(work: str) -> None:
        edit(
            pack(work, 'CTL-M-001', 'oracle', 'labels.json'),
            lambda o: o.update(condition='corrupt_file'),
        )
        path = pack(work, 'CTL-M-001', 'input', 'materials', 'repair-quote.pdf')
        with open(path, 'rb') as f:
            cut = f.read()[:400]
        with open(path, 'wb') as f:
            f.write(cut)
        digest = hashlib.sha256(cut).hexdigest()
        edit(
            pack(work, 'CTL-M-001', 'provenance.json'),
            lambda d: next(m for m in d['materials'] if m['id'] == 'repair-quote').update(
                sha256=digest
            ),
        )

    failures += corpus_case(
        'pack removed from the corpus',
        lambda work: shutil.rmtree(pack(work, 'CTL-C-002')),
        'listed pack(s) missing: CTL-C-002',
    )
    failures += corpus_case(
        'manifest removed',
        lambda work: os.remove(os.path.join(work, 'manifest.json')),
        'manifest.json is missing or unreadable',
    )
    failures += corpus_case(
        'a pack file that names another case',
        lambda work: edit(
            pack(work, 'CTL-M-001', 'setup.json'), lambda s: s.update(case_id='CTL-M-002')
        ),
        "case ID: setup.json names 'CTL-M-002'",
    )
    failures += corpus_case(
        'an unrelated document that does not open, in a corrupt_file pack',
        broken_quote_in_a_corrupt_file_pack,
        'format: repair-quote.pdf does not open',
    )
    # Unchanged copy passes.
    fresh()
    code, out = run()
    print(('PASS   ' if code == 0 else 'FAIL   ') + 'unchanged copy')
    failures += code != 0
    shutil.rmtree(BASE, ignore_errors=True)
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
