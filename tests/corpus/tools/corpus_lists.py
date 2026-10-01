"""Invented names used by the controlled corpus, and patterns the checker enforces.

Every person, street and business in a pack must come from these lists. The words "Test" in street
names and the invented business names make it clear that no pack describes a real place or firm.
"""

import re

_SAMPLE_PEOPLE = [
    'Aroha Tanewood',
    'Mere Kowhaiford',
    'Liam Harbourne',
    'Priya Ranganath-Vale',
    'Wei Chenmoor',
    'Sione Talavale',
    'Hannah Pikeroft',
    'Tomas Rewiford',
    'Anjali Northbeck',
    'Ngaire Whitlowe',
    'Daniel Okorewa',
    'Grace Tiritane',
    'Mateo Kahurangi-Ross',
    'Emily Waitarefield',
    'Rawiri Fenmoor',
]

# Common first names paired with invented compound surnames. The surnames are made up from place
# words, so a full name is not meant to point at any real person.
_FIRST = [
    'Aroha',
    'Liam',
    'Mere',
    'Oliver',
    'Priya',
    'Sione',
    'Hannah',
    'Tomas',
    'Anjali',
    'Ngaire',
    'Daniel',
    'Grace',
    'Mateo',
    'Emily',
    'Rawiri',
    'Wei',
    'Charlotte',
    'Tane',
    'Isla',
    'Arjun',
    'Leilani',
    'Jack',
    'Mia',
    'Hemi',
    'Sofia',
    'Noah',
    'Amelia',
    'Kiri',
    'Lucas',
    'Ruby',
    'Manaia',
    'Chloe',
    'Ethan',
    'Aria',
    'Samuel',
    'Olivia',
    'Wiremu',
    'Zara',
    'James',
    'Hana',
    'Mohammed',
    'Ava',
    'Finn',
    'Maia',
    'Henry',
    'Lucy',
    'Tui',
    'Ravi',
    'Ella',
    'Kai',
    'Fatima',
    'George',
    'Nikau',
    'Ivy',
    'Leo',
    'Anahera',
    'Min',
    'Paige',
    'Toby',
    'Yuki',
]
_SURNAME_PARTS = [
    ('Tane', 'wood'),
    ('Harbour', 'ne'),
    ('Kowhai', 'ford'),
    ('Chen', 'moor'),
    ('Pike', 'croft'),
    ('Rewi', 'field'),
    ('North', 'beck'),
    ('Whit', 'lowe'),
    ('Fern', 'moor'),
    ('Tide', 'well'),
    ('Kiln', 'hurst'),
    ('Salt', 'marsh'),
    ('Copper', 'dale'),
    ('Long', 'reach'),
    ('Ridge', 'fern'),
    ('Waka', 'thorne'),
    ('Rimu', 'vale'),
    ('Totara', 'brook'),
    ('Mata', 'lane'),
    ('Awa', 'field'),
    ('Kauri', 'dean'),
    ('Pohutu', 'wick'),
    ('Tarata', 'holm'),
    ('Manuka', 'stead'),
    ('Harakeke', 'by'),
    ('Kereru', 'mont'),
    ('Puriri', 'combe'),
    ('Nikau', 'ridge'),
    ('Karaka', 'worth'),
    ('Matai', 'shaw'),
    ('Ash', 'tarn'),
    ('Bell', 'moor'),
    ('Cedar', 'holt'),
    ('Drift', 'wood'),
    ('Elm', 'garth'),
    ('Flax', 'mere'),
    ('Glen', 'rook'),
    ('Heron', 'dale'),
    ('Iron', 'bark'),
    ('Juniper', 'lea'),
]
_GENERATED: list[str] = []
for _round in range(4):
    for _j, _first in enumerate(_FIRST):
        _left, _right = _SURNAME_PARTS[(_j * 7 + _round * 11) % len(_SURNAME_PARTS)]
        _name = f'{_first} {_left}{_right}'
        if _name not in _GENERATED and _name not in _SAMPLE_PEOPLE:
            _GENERATED.append(_name)

# Claimants of the v1 corpus use PEOPLE[CLAIMANT_OFFSET[family] + number - 1]; everyone else in a
# pack (other drivers, witnesses, estimators, tradespeople) uses PEOPLE[OTHER_START:].
PEOPLE = _GENERATED[:230] + _SAMPLE_PEOPLE
CLAIMANT_OFFSET = {'M': 0, 'H': 50, 'C': 80}
OTHER_START = 100

STREETS = [
    'Harbourlight Test Lane',
    'Fernbank Test Road',
    'Tidewater Test Street',
    'Kiln Test Crescent',
    'Ridgefern Test Avenue',
    'Saltmarsh Test Place',
    'Copperleaf Test Drive',
    'Longreach Test Way',
    'Kowhai Test Grove',
    'Rimu Test Terrace',
    'Totara Test Rise',
    'Matai Test Close',
    'Awa Test Parade',
    'Kauri Test Heights',
    'Puriri Test Mews',
    'Nikau Test Glade',
    'Karaka Test Row',
    'Manuka Test Street',
    'Harakeke Test Lane',
    'Kereru Test Road',
    'Ashbourne Test Avenue',
    'Bellbird Test Drive',
    'Cedarvale Test Way',
    'Driftwood Test Crescent',
    'Elmgarth Test Place',
    'Flaxmere Test Road',
    'Glenrook Test Street',
    'Herondale Test Lane',
    'Ironbark Test Grove',
    'Juniper Test Terrace',
    'Lighthouse Test Road',
    'Millbrook Test Street',
    'Orchard Test Lane',
    'Pinecrest Test Avenue',
    'Quarry Test Road',
    'Riverbend Test Drive',
    'Seaview Test Terrace',
    'Tussock Test Way',
    'Upland Test Road',
    'Wharf Test Street',
]

BUSINESSES = {
    'panel_beater': [
        'Harbourside Panel & Paint (Synthetic)',
        'Ridgeway Collision Repairs (Synthetic)',
        'Kiln Hurst Smash Repairs (Synthetic)',
        'Totara Brook Body Works (Synthetic)',
        'Cedar Holt Auto Refinish (Synthetic)',
        'Glen Rook Panelcraft (Synthetic)',
    ],
    'mechanic': ['Awa Field Automotive (Synthetic)', 'Iron Bark Motors Workshop (Synthetic)'],
    'towing': ['Long Reach Towing (Synthetic)', 'Rimu Vale Recovery (Synthetic)'],
    'vehicle_dealer': [
        'Copper Dale Car Sales (Synthetic)',
        'Heron Dale Motors (Synthetic)',
        'Seaview Vehicle Traders (Synthetic)',
    ],
    'plumber': [
        'Tidewater Plumbing Services (Synthetic)',
        'Kiln Street Plumbing (Synthetic)',
        'Flax Mere Plumbing & Gas (Synthetic)',
        'Juniper Lea Drainage (Synthetic)',
    ],
    'builder': [
        'Fernbank Interior Repairs (Synthetic)',
        'Kauri Dean Builders (Synthetic)',
        'Matai Shaw Construction (Synthetic)',
        'Elm Garth Renovations (Synthetic)',
    ],
    'roofer': ['Pohutu Wick Roofing (Synthetic)', 'Bell Moor Roof Repairs (Synthetic)'],
    'electrician': ['Ash Tarn Electrical (Synthetic)', 'Nikau Ridge Sparks (Synthetic)'],
    'glazier': ['Drift Wood Glass (Synthetic)', 'Karaka Worth Glazing (Synthetic)'],
    'locksmith': ['Tarata Holm Locksmiths (Synthetic)', 'Puriri Combe Security (Synthetic)'],
    'retailer': [
        'Copperleaf Electronics (Synthetic)',
        'Longreach Tech Store (Synthetic)',
        'Manuka Stead Home & Living (Synthetic)',
        'Harakeke By Appliances (Synthetic)',
        'Kereru Mont Outdoor (Synthetic)',
        'Orchard Lane Jewellers (Synthetic)',
    ],
    'assessor': [
        'Saltmarsh Loss Assessing (Synthetic)',
        'Waka Thorne Assessors (Synthetic)',
        'Rewi Field Claims Consulting (Synthetic)',
    ],
    'restoration': [
        'Tide Well Drying & Restoration (Synthetic)',
        'Upland Water Damage Services (Synthetic)',
    ],
}

# Retailers, repairers and insurers that must never appear as an issuer or on a document.
BLOCKED_BRANDS = [
    'AA Insurance',
    'AMI',
    'State Insurance',
    'Tower',
    'IAG',
    'Vero',
    'Suncorp',
    'NZI',
    'Lumley',
    'Noel Leeming',
    'JB Hi-Fi',
    'Harvey Norman',
    'PB Tech',
    'Warehouse Stationery',
    'Mitre 10',
    'Bunnings',
    'Placemakers',
    'Repco',
    'Supercheap',
    'Beaurepaires',
    'Countdown',
    'Woolworths',
    'New World',
    "PAK'nSAVE",
    'Apple',
    'Samsung',
    'Dell',
    'Lenovo',
    'HP Inc',
    'Microsoft',
]

FOOTER = 'SYNTHETIC TEST DOCUMENT - Northwind FNOL student project - not a real record'

# Formats that cannot belong to a real person or vehicle in New Zealand.
PLATE_RE = re.compile(r'\bTST-\d{3}\b')
LICENCE_RE = re.compile(r'\bTST\d{5}\b')
PHONE_RE = re.compile(r'\+64 00 000 \d{4}')
EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)*')

# Tokens that look like a real NZ plate (three letters and three digits) or licence number
# (two letters and six digits). The checker fails any document text that contains one.
REAL_PLATE_LIKE_RE = re.compile(r'\b[A-Z]{3}\d{3}\b')
REAL_LICENCE_LIKE_RE = re.compile(r'\b[A-Z]{2}\d{6}\b')

# Words that belong to the oracle and must never appear in model-visible input.
ORACLE_WORDS = [
    'fast_track',
    'review_required',
    'severity',
    'fraud',
    'oracle',
    'expected_endpoint',
    'scenario_category',
    'intended_conflict',
    'triage',
    'review_indicator',
    'innocent_control',
    'not_checked',
]
