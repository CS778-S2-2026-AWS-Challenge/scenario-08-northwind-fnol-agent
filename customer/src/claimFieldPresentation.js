// Claimant-facing names and readable values for registered Claim fields.

export const FIELD_LABELS = {
  'claim.product_family': 'Claim type',
  'incident.type': 'Incident type',
  'incident.description': 'What happened',
  'incident.cause': 'Cause',
  'incident.injury_or_danger': 'Injury or immediate danger',
  'incident.occurred_at': 'When it happened',
  'incident.discovered_at': 'When it was discovered',
  'incident.location': 'Incident location',
  'loss.description': 'Damage or loss',
  'parties.other_parties': 'Other people or vehicles involved',
  'vehicle.registration': 'Vehicle registration',
  'vehicle.damage_description': 'Vehicle damage',
  'vehicle.drivable': 'Vehicle safe to drive',
  'property.address': 'Affected property',
  'property.affected_areas': 'Affected areas',
  'property.ongoing_risk': 'Ongoing property risk',
  'property.habitable': 'Property safe to live in',
  'contents.items': 'Damaged, lost, or stolen items',
  'contents.police_reference': 'Police reference for stolen items',
  'theft.entry_context': 'How entry occurred',
  'injury.persons_affected': 'Who was injured',
  'injury.severity_reported': 'Injury severity',
  'injury.medical_attention': 'Medical attention received',
  'authorities.police_report_reference': 'Police report reference',
  'authorities.emergency_services_notified': 'Emergency services notified',
  'policy.policy_number': 'Policy number',
  'claimant.role': 'Your role in this claim',
  'claimant.client_number': 'Client number',
  'claimant.contact_preference': 'Preferred contact method',
}

export const FIELD_SOURCE_LABELS = {
  claimant: 'Provided by you',
  inference: 'Suggested from your description',
  image: 'Suggested from your image',
  document: 'Suggested from your document',
  policy: 'From your policy information',
  claim_history: 'From your previous claim information',
  staff: 'Provided by Northwind support',
}

export function fieldLabel(fieldCode) {
  return FIELD_LABELS[fieldCode] || fieldCode.split('.').at(-1).replaceAll('_', ' ')
}

export function fieldStatusLabel(status) {
  if (status === 'confirmed') return 'Confirmed'
  if (status === 'pending_generation') return 'Pending'
  if (status === 'proposed') return 'Needs review'
  if (status === 'missing') return 'Missing'
  if (status === 'disputed') return 'Conflict'
  if (status === 'unavailable') return 'Unavailable'
  return 'Recorded'
}

export function fieldSourceLabel(source) {
  return FIELD_SOURCE_LABELS[source] || 'Source recorded by Northwind'
}

export function fieldValueText(field) {
  if (
    field.status === 'pending_generation'
    && (field.value === null || field.value === undefined || field.value === '')
  ) {
    return 'Expected later'
  }
  if (typeof field.value === 'boolean') return field.value ? 'Yes' : 'No'
  if (Array.isArray(field.value)) return field.value.join(', ')
  if (field.value && typeof field.value === 'object') {
    return field.value.claimant_wording
      || field.value.formatted
      || Object.values(field.value).filter((value) => (
        typeof value === 'string' || typeof value === 'number'
      )).join(', ')
  }
  return String(field.value ?? '')
}
