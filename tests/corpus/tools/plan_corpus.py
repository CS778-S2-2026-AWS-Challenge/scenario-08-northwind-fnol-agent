"""Allocate the 100 controlled packs: category, planted feature, boundary condition, \
message style, session.

Usage:
  python -m tests.corpus.tools.plan_corpus OUT_DIR

Writes OUT_DIR/corpus-plan-v1.json and OUT_DIR/corpus-plan-v1.md. The numbers come from the
standard ("Plan the distribution"): 50/30/20 families from sprint/sprint5.md stage C, and the
review-indicator groups scaled from section 5 of the maintainer's rules. The allocation is
deterministic, so a rerun gives the same plan.
"""

import json
import os
import sys
from collections import Counter
from typing import cast

CATEGORIES = [
    ('M1', 12),
    ('M2', 6),
    ('M3', 10),
    ('M4', 12),
    ('M5', 10),
    ('H1', 8),
    ('H2', 14),
    ('H3', 8),
    ('C1', 12),
    ('C2', 8),
]

# Planted features: (feature, count, categories in preference order). One feature per pack, so a
# failure points at one cause.
FEATURES = [
    ('ownership_doc_after_loss', 3, ['C2']),
    ('ownership_doc_after_loss_time_range', 2, ['C2']),
    ('ownership_doc_after_loss', 2, ['M5']),
    ('ownership_doc_after_loss_time_range', 1, ['M5']),
    ('ownership_doc_after_loss', 1, ['H3']),
    ('quote_before_loss', 5, ['M4', 'M5']),
    ('quote_before_loss', 3, ['H2', 'H3']),
    ('innocent_reprint_date_after_loss', 2, ['C1']),
    ('innocent_reprint_date_after_loss', 1, ['M1']),
    ('innocent_reprint_date_after_loss', 1, ['H2']),
    ('innocent_same_day_purchase', 2, ['C1']),
    ('innocent_same_day_purchase', 1, ['M1']),
    ('innocent_one_prior_claim', 2, ['M1', 'M4']),
    ('innocent_one_prior_claim', 1, ['H2']),
    ('innocent_non_date_inconsistency', 1, ['M3']),
    ('innocent_non_date_inconsistency', 1, ['H2']),
    ('innocent_non_date_inconsistency', 1, ['C1']),
    ('hint_two_prior_claims', 2, ['M1', 'M4']),
    ('hint_two_prior_claims', 1, ['H2']),
    ('possible_duplicate', 2, ['M1', 'M3']),
    ('possible_duplicate', 1, ['C1']),
    ('policy_not_found', 1, ['M1']),
    ('policy_not_found', 1, ['H2']),
    ('policy_not_found', 1, ['C1']),
    ('coverage_uncertainty_marker', 1, ['M5']),
    ('coverage_uncertainty_marker', 1, ['H3']),
    ('coverage_uncertainty_marker', 1, ['C1']),
]

# Boundary conditions for about 40 packs, five each, placed where they are natural.
CONDITIONS = [
    ('illegible', ['H3', 'M4', 'C1', 'M1', 'H2']),
    ('missing_page', ['H3', 'M4', 'H2', 'M5', 'C1']),
    ('expired', ['M4', 'H2', 'C1', 'M1', 'H3']),
    ('missing_information', ['M4', 'H2', 'C1', 'M3', 'H1']),
    ('conflicting', ['M5', 'C2', 'M3', 'H3', 'M5']),
    ('corrupt_file', ['M1', 'H2', 'C1', 'M4', 'H1']),
    ('unsupported_format', ['M1', 'H2', 'C1', 'M3', 'H1']),
    ('not_yet_available', ['M3', 'H1', 'C2', 'M3', 'H1']),
]

STYLES = (
    ['plain'] * 40
    + ['many_facts'] * 12
    + ['emotional'] * 12
    + ['typos'] * 12
    + ['non_native'] * 12
    + ['wrong_product_term'] * 12
)
ANONYMOUS_FIRST = 10

CATEGORY_MEANING = {
    'M1': 'Collision and fast progression',
    'M2': 'Injury or continuing danger',
    'M3': 'Another party or Police',
    'M4': 'Vehicle damage with assessor or repair',
    'M5': 'Fact or evidence conflict and professional review',
    'H1': 'Burglary',
    'H2': 'Weather, water, or other property damage',
    'H3': 'Evidence, safety, repair, or review difference',
    'C1': 'Damaged items with ownership, value, and purchase evidence',
    'C2': 'Item-level evidence or fact conflict',
}


def plan() -> list[dict[str, str | None]]:
    slots: list[dict[str, str | None]] = []
    for category, count in CATEGORIES:
        for _ in range(count):
            slots.append({'category': category, 'feature': None, 'condition': 'normal'})
    for feature, count, categories in FEATURES:
        for _ in range(count):
            slot = next(
                (
                    s
                    for c in categories
                    for s in slots
                    if s['category'] == c and s['feature'] is None
                ),
                None,
            )
            if slot is None:
                raise SystemExit(f'no free slot for {feature} in {categories}')
            slot['feature'] = feature
    for condition, categories in CONDITIONS:
        for category in categories:
            # Prefer a slot without a planted feature, so a boundary condition and a feature do
            # not mix.
            slot = next(
                (
                    s
                    for s in slots
                    if s['category'] == category
                    and s['condition'] == 'normal'
                    and s['feature'] is None
                ),
                None,
            ) or next(
                (s for s in slots if s['category'] == category and s['condition'] == 'normal'), None
            )
            if slot is None:
                raise SystemExit(f'no free slot for {condition} in {category}')
            slot['condition'] = condition
    for slot in slots:
        # A planted date indicator is a document that contradicts the statement, as in CTL-C-001.
        if (
            slot['feature']
            and slot['feature'].startswith(('ownership_doc_after_loss', 'quote_before_loss'))
            and slot['condition'] == 'normal'
        ):
            slot['condition'] = 'conflicting'
    counters: Counter[str] = Counter()
    for index, slot in enumerate(slots):
        family = {'M': 'motor', 'H': 'home', 'C': 'contents'}[cast(str, slot['category'])[0]]
        counters[family] += 1
        slot['case_id'] = f'CTL-{cast(str, slot["category"])[0]}-{counters[family]:03d}'
        slot['family'] = family
        slot['scenario'] = CATEGORY_MEANING[cast(str, slot['category'])]
        # Styles and sessions are spread by a fixed stride so every family and category gets a mix.
        slot['message_style'] = STYLES[(index * 37) % 100]
        slot['claimant_session'] = (
            'anonymous_then_sign_in' if (index * 37) % 100 < ANONYMOUS_FIRST else 'signed_in'
        )
        slot['feature'] = slot['feature'] or 'none'
    return slots


def main() -> None:
    out = sys.argv[1]
    slots = plan()
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, 'corpus-plan-v1.json'), 'w', encoding='utf-8') as json_file:
        json.dump(slots, json_file, indent=1)
    lines = [
        '# Controlled corpus plan v1',
        '',
        f'{len(slots)} packs. Generated by `tools/plan_corpus.py`.',
        '',
        '| case_id | category | scenario | planted feature | condition | message style | session |',
        '| --- | --- | --- | --- | --- | --- | --- |',
    ]
    for s in slots:
        lines.append(
            f'| {s["case_id"]} | {s["category"]} | {s["scenario"]} | {s["feature"]} '
            f'| {s["condition"]} | {s["message_style"]} | {s["claimant_session"]} |'
        )
    summary = [
        '',
        '## Totals',
        '',
        f'- Families: {dict(Counter(s["family"] for s in slots))}',
        f'- Categories: {dict(Counter(s["category"] for s in slots))}',
        f'- Planted features: {dict(Counter(s["feature"] for s in slots))}',
        f'- Conditions: {dict(Counter(s["condition"] for s in slots))}',
        f'- Message styles: {dict(Counter(s["message_style"] for s in slots))}',
        f'- Sessions: {dict(Counter(s["claimant_session"] for s in slots))}',
    ]
    with open(os.path.join(out, 'corpus-plan-v1.md'), 'w', encoding='utf-8') as md_file:
        md_file.write('\n'.join(lines + summary) + '\n')
    print('\n'.join(summary))


if __name__ == '__main__':
    main()
