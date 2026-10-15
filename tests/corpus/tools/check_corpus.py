"""Check controlled test packs against the corpus standard.

Usage:
  python -m tests.corpus.tools.check_corpus CORPUS_DIR [--freeze]

Prints PASS or FAIL for every pack with the reasons, and exits with 1 when any pack fails.
--freeze turns the release conditions into failures: every image signed off by a person, and no
assertion still waiting for RC1 values.
"""

import glob
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pdfplumber
from PIL import Image

from tests.corpus.tools import corpus_integrity, image_review, rules
from tests.corpus.tools.corpus_lists import (
    BLOCKED_BRANDS,
    BUSINESSES,
    EMAIL_RE,
    FOOTER,
    LICENCE_RE,
    ORACLE_WORDS,
    PEOPLE,
    PHONE_RE,
    PLATE_RE,
    REAL_LICENCE_LIKE_RE,
    REAL_PLATE_LIKE_RE,
    STREETS,
)

FAMILIES = {'motor', 'home', 'contents'}
CATEGORIES = {'M1', 'M2', 'M3', 'M4', 'M5', 'H1', 'H2', 'H3', 'C1', 'C2'}
CONDITIONS = {
    'normal',
    'illegible',
    'missing_page',
    'expired',
    'missing_information',
    'conflicting',
    'corrupt_file',
    'unsupported_format',
    'not_yet_available',
}
MESSAGE_STYLES = {'plain', 'many_facts', 'emotional', 'typos', 'non_native', 'wrong_product_term'}
# On main an anonymous claimant cannot upload evidence or submit, so every journey ends signed in.
SESSIONS = {'signed_in', 'anonymous_then_sign_in'}
# The corpus supplies materials and never simulates a runtime failure (maintainer, 2026-10-01), so
# the claim-history lookup is always available; `not_checked` history cannot be planted.
HISTORY_LOOKUP = {'available'}
ORACLE_KEYS = [
    'family',
    'scenario_category',
    'condition',
    'design',
    'triage',
    'review_indicators',
    'expected_facts',
    'assertions',
    'expected_rag_sources',
    'allowed_variation',
    'intended_conflicts',
]
ENTRY_KEYS = [
    'id',
    'file',
    'evidence_kind',
    'method',
    'generator_version',
    'created_utc',
    'purpose',
    'synthetic',
    'usage_rights',
    'sha256',
]
IMAGE_KINDS = {'incident_photo', 'item_photo'}
OWNERSHIP_KINDS = {'receipt', 'proof_of_ownership'}
QUOTE_KINDS = {'repair_quote', 'assessment_report'}
UNREADABLE = {'illegible', 'corrupt_file', 'unsupported_format'}
JUDGES = {'state', 'text', 'human'}
STATE_OPS = {'equals', 'in', 'exists', 'absent', 'contains', 'not_equals'}
TEXT_SCOPES = {'claimant_visible', 'staff_visible'}
KNOWN_ISSUERS = {b for names in BUSINESSES.values() for b in names} | {
    'Northwind Insurance (fictional insurer)'
}
# "Expired" is judged against this day, the corpus's "today". A quote that is not meant to be
# expired must stay valid until RUN_WINDOW_END, so a run with a live clock before then still sees
# it as valid and does not add evidence_outstanding that the labels do not expect.
REFERENCE_DAY = date(2026, 10, 1)
WORDING_EFFECTIVE_FROM = '2026-01-01'  # config/knowledge-source-corpus/*-2026.2.md
AMOUNT_THRESHOLD = 5000  # NZD; exactly 5,000 is still fast_track
BROKEN_OR_BLURRED = {'blur', 'truncate', 'to_tiff'}
CONDITION_MATERIAL = {
    'illegible': {'blur'},
    'missing_page': {'keep_pages'},
    'corrupt_file': {'truncate'},
    'unsupported_format': {'to_tiff'},
    'not_yet_available': {'unavailable_notice'},
}
RUN_WINDOW_END = date(2026, 11, 30)
MONTHS = 'January|February|March|April|May|June|July|August|September|October|November|December'
WEEKDAY_DATE_RE = re.compile(
    r'\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),? (\d{1,2}) ('
    + MONTHS
    + r')(?: (\d{4}))?'
)
HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY_PATH = os.path.join(HERE, 'registry_codes.json')


def parse_day(text: object) -> date | None:
    """Parse '26 September 2026' (optionally with a weekday or time around it) into a date."""
    match = re.search(
        r'(\d{1,2}) (January|February|March|April|May|June|July|August|'
        r'September|October|November|December) (\d{4})',
        str(text),
    )
    return datetime.strptime(' '.join(match.groups()), '%d %B %Y').date() if match else None


def derive_date_checks(
    oracle: dict[str, Any], materials: list[dict[str, Any]], facts: dict[str, Any]
) -> tuple[dict[str, str], list[str]]:
    """Recompute the two strong checks from the documents' printed dates and the incident window."""
    problems: list[str] = []
    window = oracle.get('design', {}).get('incident_window', {})
    first, last = window.get('first_day'), window.get('last_day')
    if not first or not last:
        return {}, ['design: incident_window.first_day and last_day are required']
    first, last = date.fromisoformat(first), date.fromisoformat(last)
    occurred = str(facts.get('incident.occurred_at', ''))
    if parse_day(occurred) not in (first, last):
        problems.append(f'design: incident_window does not match incident.occurred_at {occurred!r}')
    boundary = {oracle.get('condition')} | set(oracle.get('additional_conditions', []))
    result: dict[str, str] = {}
    date_field: dict[str | None, str] = {
        'receipt': 'date',
        'proof_of_ownership': 'date',
        'repair_quote': 'quote_date',
        'assessment_report': 'report_date',
    }
    compare: Callable[[date], bool]
    for code, kinds, compare in (
        ('ownership_doc_after_loss', OWNERSHIP_KINDS, lambda d: d > last),
        ('quote_before_loss', QUOTE_KINDS, lambda d: d < first),
    ):
        docs = [m for m in materials if m.get('evidence_kind') in kinds]
        if not docs:
            result[code] = 'not_applicable'
            continue
        outcomes: list[str] = []
        for doc in docs:
            printed = doc.get('printed_fields', {})
            if printed.get('purchase_date_ambiguous'):
                # Rules, section 3: when the purchase date cannot be told apart, the document is
                # left out.
                outcomes.append('not_checked')
                continue
            # A date on a removed page is not in printed_fields, so it derives as not_checked.
            day = parse_day(printed.get(date_field.get(doc.get('evidence_kind'), 'date'), ''))
            unreadable = (
                doc.get('inputs', {}).get('transform') in ('blur', 'truncate', 'to_tiff')
                and boundary & UNREADABLE
            )
            if day is None or unreadable:
                outcomes.append('not_checked')
            else:
                outcomes.append('hit' if compare(day) else 'clear')
        result[code] = (
            'hit'
            if 'hit' in outcomes
            else ('not_checked' if 'not_checked' in outcomes else 'clear')
        )
    return result, problems


def derive_policy_checks(
    setup: dict[str, Any], oracle: dict[str, Any], facts: dict[str, Any]
) -> tuple[dict[str, str], dict[str, str], dict[str, Any] | None]:
    """Recompute policy lookup and inception from the policies the pack puts into the system.

    Returns the outcome the system should report today, the value the rule gives once the data
    exists, and whether the policy lookup fails.
    """
    number = facts.get('policy.policy_number')
    known = {p['policy_number']: p for p in setup.get('policies_in_system', [])}
    design = oracle.get('design', {})
    window = design.get('incident_window', {})
    policy = known.get(number)
    # effective_from is only the current period start, which changes at renewal (maintainer,
    # 2026-09-30). The rule needs the original inception date, which the pack states in its design.
    inception = design.get('policy_inception_date')
    if policy is None or not window.get('first_day') or not inception:
        rule_value = 'not_checked'
    else:
        gap = (date.fromisoformat(window['first_day']) - date.fromisoformat(inception)).days
        rule_value = 'hit' if gap < 30 else 'clear'
    today = 'not_checked' if 'policy_inception_30d' in rules.DATA_DEPENDENCIES else rule_value
    return {'policy_inception_30d': today}, {'policy_inception_30d': rule_value}, policy


def check_fact_values(
    name: str,
    values: dict[str, Any],
    registry: dict[str, Any],
    problems: list[str],
    allow_lists: bool,
) -> None:
    types, enums = registry.get('value_types', {}), registry.get('enum_values', {})
    for code, value in values.items():
        if code not in registry['codes']:
            problems.append(f'{name}: {code} is not a Field Registry code')
            continue
        candidates = value if allow_lists and isinstance(value, list) else [value]
        for candidate in candidates:
            kind = types.get(code)
            if kind == 'enum' and candidate not in enums.get(code, []):
                problems.append(
                    f'{name}: {code}={candidate!r} is not an allowed value {enums.get(code)}'
                )
            elif kind == 'boolean' and not isinstance(candidate, bool):
                problems.append(f'{name}: {code} must be true or false')
            elif kind == 'temporal':
                try:
                    date.fromisoformat(str(candidate))
                except ValueError:
                    problems.append(
                        f'{name}: {code} must be an ISO date; the scorer compares the calendar day'
                    )


def derive_history_checks(
    setup: dict[str, Any], oracle: dict[str, Any], family: object
) -> dict[str, str]:
    "Recompute the history checks from the pack's setup: who is signed in and which claims exist."
    window = oracle.get('design', {}).get('incident_window', {})
    if not window.get('first_day'):
        return {}
    first, last = date.fromisoformat(window['first_day']), date.fromisoformat(window['last_day'])
    prior = setup.get('prior_submitted_claims', [])

    def same_event(claim: dict[str, Any]) -> bool:
        day = date.fromisoformat(claim['incident_date'])
        return claim.get('family') == family and first - timedelta(
            days=3
        ) <= day <= last + timedelta(days=3)

    # A possible duplicate is not counted again as a prior claim (design section 3).
    duplicates = [c for c in prior if same_event(c)]
    counted = [
        c
        for c in prior
        if not same_event(c) and 0 <= (last - date.fromisoformat(c['submitted_date'])).days <= 365
    ]
    return {
        'prior_claims_12m': 'hit' if len(counted) >= 2 else 'clear',
        'possible_duplicate': 'hit' if duplicates else 'clear',
    }


def check_assertions(
    oracle: dict[str, Any], freeze: bool, problems: list[str], warnings: list[str]
) -> None:
    ids = set()
    pending = 0
    for item in oracle.get('assertions', []):
        label = item.get('id', '?')
        if label in ids:
            problems.append(f'assertions: duplicate id {label}')
        ids.add(label)
        if item.get('kind') not in ('required', 'forbidden'):
            problems.append(f'assertions: {label} kind must be required or forbidden')
        judge = item.get('judge')
        if judge not in JUDGES:
            problems.append(f'assertions: {label} judge {judge!r} is not one of {sorted(JUDGES)}')
        elif judge == 'state':
            if not item.get('path') or item.get('op') not in STATE_OPS:
                problems.append(
                    f'assertions: {label} needs a path and an op from {sorted(STATE_OPS)}'
                )
            elif item['op'] not in ('exists', 'absent') and 'value' not in item:
                problems.append(f'assertions: {label} op {item["op"]} needs a value')
        elif judge == 'text':
            if item.get('scope') not in TEXT_SCOPES or not (
                item.get('must_not_match') or item.get('rubric')
            ):
                problems.append(f'assertions: {label} needs a scope and must_not_match or a rubric')
            for pattern in item.get('must_not_match', []):
                try:
                    re.compile(pattern)
                except re.error as error:
                    problems.append(
                        f'assertions: {label} pattern {pattern!r} does not compile ({error})'
                    )
        elif judge == 'human' and not item.get('question'):
            problems.append(f'assertions: {label} needs a question for the human judge')
        if item.get('bind_at_rc1'):
            pending += 1
    if pending:
        (problems if freeze else warnings).append(f'assertions: {pending} still marked bind_at_rc1')


def resolve(facts: dict[str, Any], path: str) -> Any:
    """Resolve 'code' or 'code[index].subkey' against the flat fact dict."""
    # cast only: a path that does not match still raises TypeError on the subscript below.
    match = cast(
        're.Match[str]', re.match(r'^(?P<key>[^\[]+)(?:\[(?P<idx>\d+)\]\.(?P<sub>.+))?$', path)
    )
    value = facts.get(match['key'])
    if match['idx'] is not None and isinstance(value, list):
        value = value[int(match['idx'])].get(match['sub'])
    return value


def pdf_text(path: str) -> list[str]:
    with pdfplumber.open(path) as pdf:
        return [page.extract_text() or '' for page in pdf.pages]


def check_pack(
    case_dir: str, context: dict[str, Any], freeze: bool = False
) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    warnings: list[str] = []
    inp, orc = os.path.join(case_dir, 'input'), os.path.join(case_dir, 'oracle')
    case_id = os.path.basename(case_dir)

    # 1. Schema and the four parts, plus the runner's setup.
    try:
        message = Path(os.path.join(inp, 'initial_message.txt')).read_text(encoding='utf-8').strip()
        facts_doc = json.loads(Path(os.path.join(inp, 'facts.json')).read_text(encoding='utf-8'))
        materials_doc = json.loads(
            Path(os.path.join(inp, 'materials.json')).read_text(encoding='utf-8')
        )
        oracle = json.loads(Path(os.path.join(orc, 'labels.json')).read_text(encoding='utf-8'))
        setup = json.loads(Path(os.path.join(case_dir, 'setup.json')).read_text(encoding='utf-8'))
        provenance = json.loads(
            Path(os.path.join(case_dir, 'provenance.json')).read_text(encoding='utf-8')
        )
    except (OSError, ValueError) as error:
        return [f'schema: cannot read a required part ({error})'], warnings
    problems.extend(corpus_integrity.case_id_problems(case_dir))
    facts = facts_doc.get('facts', {})
    materials = provenance.get('materials', [])
    visible = materials_doc.get('materials', [])
    if sorted(m['file'] for m in visible) != sorted(m['file'] for m in materials):
        problems.append('provenance: input/materials.json and provenance.json list different files')
    for item in visible:
        extra = set(item) - {'file', 'evidence_kind', 'available_from'}
        if extra:
            problems.append(
                f'separation: input/materials.json exposes {sorted(extra)} for {item["file"]}'
            )
    if not message:
        problems.append('schema: initial message is empty')
    if not facts:
        problems.append('schema: fact sheet is empty')
    missing = [k for k in ORACLE_KEYS if k not in oracle]
    if missing:
        problems.append('schema: oracle missing ' + ', '.join(missing))
    for key, allowed in (
        ('family', FAMILIES),
        ('scenario_category', CATEGORIES),
        ('condition', CONDITIONS),
    ):
        if oracle.get(key) not in allowed:
            problems.append(f'schema: oracle {key}={oracle.get(key)!r} is not an allowed value')
    for additional in oracle.get('additional_conditions', []):
        if additional not in CONDITIONS:
            problems.append(f'schema: additional condition {additional!r} is not allowed')
    if oracle.get('rules_ref', {}).get('sha256') != rules.RULES_REF['sha256']:
        problems.append(
            'schema: oracle rules_ref does not name the current triage and fraud design'
        )
    if oracle.get('design', {}).get('message_style') not in MESSAGE_STYLES:
        problems.append(f'schema: design.message_style must be one of {sorted(MESSAGE_STYLES)}')
    if setup.get('claimant_session') not in SESSIONS:
        problems.append(f'schema: setup.claimant_session must be one of {sorted(SESSIONS)}')
    if setup.get('history_lookup') not in HISTORY_LOOKUP:
        problems.append(f'schema: setup.history_lookup must be one of {sorted(HISTORY_LOOKUP)}')
    if 'policies_in_system' not in setup:
        problems.append(
            'schema: setup.policies_in_system is required (use [] to test a failed lookup)'
        )

    # 1b. Labels follow the rules: reasons give the class, checks give the fraud signal, and the
    # checks themselves follow from the documents and the setup.
    problems.extend(rules.derive(oracle))
    expected_checks = {
        code: item.get('expected')
        for code, item in oracle.get('review_indicators', {}).get('checks', {}).items()
    }
    date_checks, date_problems = derive_date_checks(oracle, materials, facts)
    problems.extend(date_problems)
    policy_checks, rule_values, pack_policy = derive_policy_checks(setup, oracle, facts)
    lookup_fails = pack_policy is None
    inception = oracle.get('design', {}).get('policy_inception_date')
    if not inception:
        problems.append(
            'design: policy_inception_date (the original inception, not the current period start)'
            ' is required'
        )
    for policy in setup.get('policies_in_system', []):
        # The schedules name wording 2026.2, effective from WORDING_EFFECTIVE_FROM; the wording
        # is not to be applied when the schedule's period does not match it.
        if policy.get('effective_from', '') < WORDING_EFFECTIVE_FROM:
            problems.append(
                f'dates: {policy["policy_number"]} period starts {policy["effective_from"]},'
                f' before the wording version is effective ({WORDING_EFFECTIVE_FROM})'
            )
    if pack_policy and inception and pack_policy.get('effective_from', '')[5:] != inception[5:]:
        # Realism, not a rule error: no label depends on it (the reviewed 0.2 samples do this).
        warnings.append(
            f'dates: the current period starts {pack_policy["effective_from"]}, which is not an '
            f'anniversary of the original inception {inception}'
        )
    # Maintainer, 2026-09-30: coverage_unclear rests only on a lookup uncertainty marker or an Agent
    # record that the loss may not be covered. A marker planted in setup therefore requires it.
    marker = bool(pack_policy and pack_policy.get('uncertainty'))
    required_now = oracle.get('triage', {}).get('required_reasons', [])
    if marker and 'coverage_unclear' not in required_now:
        problems.append(
            'triage: the pack policy carries an uncertainty marker, so coverage_unclear must be'
            ' required'
        )
    derived = {
        **date_checks,
        **policy_checks,
        **derive_history_checks(setup, oracle, oracle.get('family')),
    }
    for code, outcome in derived.items():
        if expected_checks.get(code) != outcome:
            problems.append(
                f'review_indicators: {code} is labelled {expected_checks.get(code)!r}'
                f' but the pack gives {outcome!r}'
            )
    for code, value in rule_values.items():
        if code in rules.DATA_DEPENDENCIES:
            labelled = (
                oracle.get('review_indicators', {})
                .get('checks', {})
                .get(code, {})
                .get('value_if_data')
            )
            if labelled != value:
                problems.append(
                    f'review_indicators: {code}.value_if_data is {labelled!r}'
                    f' but the rule gives {value!r}'
                )
    if lookup_fails != (
        'policy_lookup_failed' in oracle.get('triage', {}).get('required_reasons', [])
    ):
        problems.append(
            'triage: policy_lookup_failed must be required exactly when the pack policy is not in'
            ' setup.policies_in_system'
        )
    check_assertions(oracle, freeze, problems, warnings)
    if os.path.exists(REGISTRY_PATH):
        registry = json.loads(Path(REGISTRY_PATH).read_text(encoding='utf-8'))
        check_fact_values(
            'expected_facts',
            oracle.get('expected_facts', {}),
            registry,
            problems,
            allow_lists=False,
        )
        check_fact_values(
            'optional_facts', oracle.get('optional_facts', {}), registry, problems, allow_lists=True
        )
        overlap = set(oracle.get('expected_facts', {})) & set(oracle.get('optional_facts', {}))
        if overlap:
            problems.append(f'expected_facts: {sorted(overlap)} also listed as optional')
    else:
        warnings.append(
            'expected_facts: tools/registry_codes.json missing, registry codes not checked'
        )
    kinds = [m.get('evidence_kind') for m in materials]
    if not any(k in IMAGE_KINDS for k in kinds):
        problems.append('schema: no image material')
    if not any(k not in IMAGE_KINDS for k in kinds):
        problems.append('schema: no document material')

    # 2. Provenance and file integrity.
    listed = set()
    texts = [
        message,
        json.dumps(facts_doc, ensure_ascii=False),
        json.dumps(materials_doc, ensure_ascii=False),
    ]
    boundary = {oracle.get('condition')} | set(oracle.get('additional_conditions', []))
    for entry in materials:
        absent = [k for k in ENTRY_KEYS if k not in entry]
        if absent:
            problems.append(f'provenance: {entry.get("id")} missing ' + ', '.join(absent))
        if entry.get('synthetic') is not True:
            problems.append(f'provenance: {entry.get("id")} is not marked synthetic')
        if entry.get('method') == 'image_model' and not entry.get('model'):
            problems.append(f'provenance: {entry.get("id")} has no model name')
        path = os.path.join(inp, 'materials', entry['file'])
        listed.add(entry['file'])
        if not os.path.exists(path):
            problems.append(f'provenance: file {entry["file"]} is missing')
            continue
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != entry.get('sha256'):
            problems.append(f'provenance: hash mismatch for {entry["file"]}')
        # 3. Format. Only the material a boundary condition was made from is exempt; every other
        # material in the same pack must open as its type.
        may_not_open, may_be_other_format = corpus_integrity.format_exemption(entry, boundary)
        if entry['file'].lower().endswith('.pdf'):
            try:
                pages = pdf_text(path)
                for number, page in enumerate(pages, 1):
                    if FOOTER not in page.replace('\n', ' '):
                        problems.append(
                            f'privacy: {entry["file"]} page {number} lacks the synthetic footer'
                        )
                texts.extend(pages)
            except Exception as error:  # any parse failure is a format finding
                if not may_not_open:
                    problems.append(
                        f'format: {entry["file"]} does not open ({error.__class__.__name__})'
                    )
        else:
            try:
                with Image.open(path) as img:
                    img.verify()
                    fmt = img.format
                if fmt != 'JPEG' and not may_be_other_format:
                    problems.append(f'format: {entry["file"]} is {fmt}, expected JPEG')
            except Exception as error:
                if not may_not_open:
                    problems.append(
                        f'format: {entry["file"]} does not open ({error.__class__.__name__})'
                    )
        if entry.get('method') == 'image_model':
            prompt = entry.get('inputs', {}).get('prompt', '').lower()
            for field in ('vehicle.make', 'vehicle.model'):
                value = str(facts.get(field, '')).lower()
                if value and re.search(r'\b' + re.escape(value) + r'\b', prompt):
                    problems.append(
                        f'privacy: image prompt for {entry["id"]}'
                        f' names the {field} {facts[field]!r}'
                    )
    extra_files = set(os.listdir(os.path.join(inp, 'materials'))) - listed
    if extra_files:
        problems.append('provenance: unlisted files ' + ', '.join(sorted(extra_files)))

    # 4. Separation: no oracle words in model-visible input.
    blob = '\n'.join(texts)
    for word in ORACLE_WORDS:
        if re.search(r'\b' + re.escape(word) + r'\b', blob, re.IGNORECASE):
            problems.append(f'separation: input contains the oracle word {word!r}')

    # 5. Privacy formats.
    for match in REAL_PLATE_LIKE_RE.findall(blob):
        problems.append(f'privacy: {match!r} looks like a real NZ plate')
    for match in REAL_LICENCE_LIKE_RE.findall(blob):
        problems.append(f'privacy: {match!r} looks like a real NZ licence number')
    for phone in re.findall(r'\+64[\d ]{6,}', blob):
        if not PHONE_RE.fullmatch(phone.strip()):
            problems.append(f'privacy: phone {phone.strip()!r} is not in the reserved format')
    for email in EMAIL_RE.findall(blob):
        if not email.lower().endswith('.invalid'):
            problems.append(f'privacy: email {email!r} does not end in .invalid')
    for brand in BLOCKED_BRANDS:
        if re.search(r'\b' + re.escape(brand) + r'\b', blob):
            problems.append(f'privacy: blocked brand {brand!r} appears in input')
    plate = facts.get('vehicle.registration')
    if plate and not PLATE_RE.fullmatch(plate):
        problems.append(f'privacy: vehicle.registration {plate!r} is not in the TST-### format')
    licence = facts.get('driver.licence_number')
    if licence and not LICENCE_RE.fullmatch(licence):
        problems.append(f'privacy: driver.licence_number {licence!r} is not in the reserved format')
    for field in ('policyholder.name', 'driver.name'):
        if facts.get(field) and facts[field] not in PEOPLE:
            problems.append(f'privacy: {field} {facts[field]!r} is not from the corpus name list')
    for field in ('property.address', 'incident.location'):
        value = facts.get(field)
        if value and re.search(r'\d', value) and not any(street in value for street in STREETS):
            problems.append(f'privacy: {field} {value!r} does not use a corpus street')

    # 6. Consistency between documents and facts.
    conflicts = {(c['material'], c['field']): c for c in oracle.get('intended_conflicts', [])}
    for entry in materials:
        printed = entry.get('printed_fields', {})
        for field, fact_path in entry.get('fact_links', {}).items():
            fact_value = resolve(facts, fact_path)
            shown = printed.get(field)
            if fact_value is None or shown is None:
                problems.append(
                    f'consistency: {entry["id"]}.{field} or fact {fact_path} is missing'
                )
                continue
            shown_text = (
                json.dumps(shown, ensure_ascii=False)
                if isinstance(shown, list | dict)
                else str(shown)
            )
            # Whole words only, so a fact of 28 does not match inside 128.
            found = re.search(
                r'(?<![\w.])' + re.escape(str(fact_value)) + r'(?![\w])', shown_text, re.IGNORECASE
            )
            if not found and (entry['id'], field) not in conflicts:
                problems.append(
                    f'consistency: {entry["id"]}.{field}={shown!r}'
                    f' does not match {fact_path}={fact_value!r}'
                )
    for (material_id, field), conflict in conflicts.items():
        entry = next((e for e in materials if e['id'] == material_id), None)
        if entry is None:
            problems.append(f'consistency: intended conflict names unknown material {material_id}')
            continue
        if str(entry.get('printed_fields', {}).get(field)) != str(conflict.get('value')):
            problems.append(
                f'consistency: intended conflict {material_id}.{field}'
                ' is not what the document shows'
            )
        if str(resolve(facts, conflict['fact'])) != str(conflict.get('fact_value')):
            problems.append(
                f'consistency: intended conflict fact {conflict["fact"]}'
                f' does not hold {conflict.get("fact_value")!r}'
            )

    # 6b. Dates that do not depend on the documents agreeing with each other.
    quotes = [
        (e, parse_day(e.get('printed_fields', {}).get('valid_until', '')))
        for e in materials
        if e.get('evidence_kind') == 'repair_quote' and 'valid_until' in e.get('printed_fields', {})
    ]
    if 'expired' in boundary:
        if quotes and not any(day and day < REFERENCE_DAY for _, day in quotes):
            problems.append(f'dates: condition expired, but no quote lapsed before {REFERENCE_DAY}')
    else:
        for entry, day in quotes:
            if day and day < RUN_WINDOW_END:
                problems.append(
                    f'dates: {entry["id"]} is valid only until {day}; a quote that is not meant to '
                    f'be expired must stay valid until {RUN_WINDOW_END}'
                )
    for match in WEEKDAY_DATE_RE.finditer(blob):
        weekday, day, month, year = match.groups()
        try:
            actual = datetime.strptime(f'{day} {month} {year or 2026}', '%d %B %Y').strftime('%A')
        except ValueError:
            problems.append(f'dates: {match.group(0)!r} is not a real date')
            continue
        if actual != weekday:
            problems.append(f'dates: {match.group(0)!r} falls on a {actual}')
    for entry in materials:
        issuer = entry.get('printed_fields', {}).get('issuer')
        if issuer and issuer not in KNOWN_ISSUERS:
            problems.append(
                f'privacy: {entry["id"]} issuer {issuer!r} is not in the corpus business list'
            )

    # 6c. A boundary condition is carried by a material made for it.
    for condition, made_by in CONDITION_MATERIAL.items():
        if condition in boundary and not any(
            (e.get('inputs') or {}).get('transform') in made_by
            or (e.get('inputs') or {}).get('template') in made_by
            for e in materials
        ):
            problems.append(
                f'condition: {condition} is labelled, but no material is made by {sorted(made_by)}'
            )

    # 6d. The schedule shows the policy the runner puts into the system.
    seeded = {p['policy_number']: p for p in setup.get('policies_in_system', [])}
    for entry in materials:
        printed = entry.get('printed_fields', {})
        policy = (
            seeded.get(printed.get('policy_number'))
            if entry.get('evidence_kind') == 'policy'
            else None
        )
        if policy is None:
            continue
        # cast only: every string found here matches parse_day's pattern, so none is None.
        days = [
            cast(date, parse_day(d))
            for d in re.findall(r'\d{1,2} (?:' + MONTHS + r') \d{4}', printed.get('period', ''))
        ]
        if len(days) == 2 and [d.isoformat() for d in days] != [
            policy['effective_from'],
            policy['effective_to'],
        ]:
            problems.append(
                f'consistency: {entry["id"]} period {printed["period"]!r} differs from setup '
                f'{policy["effective_from"]}..{policy["effective_to"]}'
            )
        excess = re.search(r'\$([\d,]+)', str(printed.get('excess', '')))
        if excess and int(excess.group(1).replace(',', '')) != policy.get('excess_nzd'):
            problems.append(
                f'consistency: {entry["id"]} excess {printed["excess"]!r} differs from setup '
                f'excess_nzd {policy.get("excess_nzd")}'
            )

    # 6e. A readable quote or assessment total over the threshold requires the amount reason.
    triage = oracle.get('triage', {})
    readable_totals = [
        e['printed_fields']['total_incl_gst']
        for e in materials
        if 'total_incl_gst' in e.get('printed_fields', {})
        and not (
            (e.get('inputs') or {}).get('transform') in BROKEN_OR_BLURRED and boundary & UNREADABLE
        )
    ]
    if (
        triage.get('applies', True)
        and readable_totals
        and max(readable_totals) > AMOUNT_THRESHOLD
        and 'amount_over_threshold_or_unknown' not in triage.get('required_reasons', [])
    ):
        problems.append(
            f'triage: a document total of NZD {max(readable_totals):,.2f} is over '
            f'{AMOUNT_THRESHOLD:,}, so amount_over_threshold_or_unknown must be required'
        )

    # 7. Review of images, by the rules in image_review.py: a sign-off per image hash, with a method
    # that the model check and the sample support.
    release = problems if freeze else warnings
    for image in (i for i in context['images'] if i['case_id'] == case_id):
        item = image['review'].get('human_signoff')
        if (
            item
            and item.get('sha256') != image['sha256']
            and image['sha256'] not in context['signoffs']
        ):
            release.append(f'review: {image["file"]} changed after its human sign-off')
            continue
        problem = image_review.release_problem(
            image,
            context['groups'],
            context['signoffs'],
            context['sampling'],
            context['escalated'],
            context['rejected_slots'],
        )
        if problem is None:
            continue
        signed = context['signoffs'].get(image['sha256'], [])
        if any(s.get('result') == 'rejected' for s in signed):
            problems.append(f'review: {image["file"]}: {problem}')
        else:
            release.append(f'review: {image["file"]}: {problem}')
    return problems, warnings


def main() -> None:
    corpus = sys.argv[1]
    freeze = '--freeze' in sys.argv[2:]
    failed = 0
    global_problems: list[str] = []
    global_warnings: list[str] = []
    check_assertions(
        json.loads(Path(os.path.join(HERE, 'global_assertions.json')).read_text(encoding='utf-8')),
        freeze,
        global_problems,
        global_warnings,
    )
    print(('FAIL' if global_problems else 'PASS') + ' corpus-wide assertions')
    for p in global_problems:
        print('   x ' + p)
    for w in global_warnings:
        print('   ! ' + w)
    failed += bool(global_problems)
    # The corpus must be exactly what its committed manifest lists, so the pack lines below cover
    # every listed pack and nothing else; and it must match its version's plan, when one exists.
    manifest_issues = corpus_integrity.manifest_problems(corpus)
    manifest = corpus_integrity.load_manifest(corpus)
    listed = len(manifest.get('packs', [])) if manifest else 0
    print(('FAIL' if manifest_issues else 'PASS') + f' manifest ({listed} packs listed)')
    for p in manifest_issues:
        print('   x ' + p)
    failed += bool(manifest_issues)
    plan_issues, plan = corpus_integrity.plan_problems(corpus)
    if plan is None:
        print('   ! plan: no distribution plan for this corpus version; distribution not checked')
    else:
        print(('FAIL' if plan_issues else 'PASS') + f' distribution against {plan}')
        for p in plan_issues:
            print('   x ' + p)
        failed += bool(plan_issues)
    try:
        images = image_review.corpus_images(corpus)
        sampling = image_review.load_sampling(corpus)
        escalated, rejected_slots = image_review.rejection_state(corpus, images)
        groups = image_review.by_hash(images)
        context: dict[str, Any] = {
            'images': images,
            'groups': groups,
            'signoffs': image_review.signoffs_by_hash(images),
            'sampling': sampling,
            'escalated': escalated,
            'rejected_slots': rejected_slots,
        }
        orphans = image_review.orphan_entries(corpus, images)
    except (OSError, ValueError, KeyError) as error:
        print(f'FAIL image review context ({error})')
        sys.exit(1)
    sampling_issues = image_review.sampling_problems(sampling, groups)
    if sampling_issues:
        print('FAIL sampling')
        for issue in sampling_issues:
            print('   x ' + issue)
        failed += 1
    if orphans:
        # Kept on purpose: an old entry can hold a rejection that still binds its material slot.
        print(
            f'   ! review: {len(orphans)} review entries name files no longer in their pack:'
            f' {orphans[:5]}'
        )
    for case_dir in sorted(glob.glob(os.path.join(corpus, 'cases', '*'))):
        problems, warnings = check_pack(case_dir, context, freeze)
        status = 'FAIL' if problems else 'PASS'
        failed += bool(problems)
        print(f'{status} {os.path.basename(case_dir)}')
        for p in problems:
            print('   x ' + p)
        for w in warnings:
            print('   ! ' + w)
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
