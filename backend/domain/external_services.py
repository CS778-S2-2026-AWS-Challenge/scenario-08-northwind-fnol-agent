ASSESSOR_SERVICE_IDENTITY = 'vehicle_damage_assessment_routing'
ASSESSOR_REQUESTED_ACTION = 'vehicle_damage_assessment'
ASSESSOR_CONSENT_FIELDS = frozenset(
    {
        'claim_id',
        'external_claim_id',
        'authorisation_ref',
        'claimant_consent_ref',
        'requested_action',
        'location.region',
    }
)

ASSESSOR_SHARED_DATA_SUMMARY = (
    'Your Northwind claim and external claim references',
    'Northwind routing authority and your permission reference',
    'The vehicle damage assessment request',
    'Your confirmed incident region',
)
