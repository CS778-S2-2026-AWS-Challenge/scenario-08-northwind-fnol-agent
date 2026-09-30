const SAFETY_FIELDS = new Set([
  'incident.injury_or_danger',
  'authorities.emergency_services_notified',
  'vehicle.drivable',
  'vehicle.towing_required',
  'vehicle.towing_location',
  'property.ongoing_risk',
  'property.habitable',
])

const REVIEW_SECTION_DEFINITIONS = Object.freeze([
  {
    id: 'overview',
    title: 'Claim overview',
    matches: (fieldCode) => [
      'claim.',
      'claimant.',
      'policy.',
      'policyholder.',
    ].some((prefix) => fieldCode.startsWith(prefix)),
  },
  {
    id: 'incident',
    title: 'Incident details',
    matches: (fieldCode) => !SAFETY_FIELDS.has(fieldCode) && [
      'incident.',
      'parties.',
      'other_party.',
      'witness.',
      'police.',
      'authorities.',
      'theft.',
    ].some((prefix) => fieldCode.startsWith(prefix)),
  },
  {
    id: 'loss',
    title: 'Insured item and loss',
    matches: (fieldCode) => !SAFETY_FIELDS.has(fieldCode) && [
      'loss.',
      'vehicle.',
      'property.',
      'contents.',
    ].some((prefix) => fieldCode.startsWith(prefix)),
  },
  {
    id: 'safety',
    title: 'Safety and ongoing risk',
    matches: (fieldCode) => SAFETY_FIELDS.has(fieldCode),
  },
])

function uniqueStrings(values) {
  return [...new Set((values || []).filter((value) => typeof value === 'string' && value))]
}

export function claimReviewSectionId(fieldCode) {
  return REVIEW_SECTION_DEFINITIONS.find((definition) => definition.matches(fieldCode))?.id
    || 'overview'
}

export function claimReviewSections(form = {}, contentsItems = [], missingFields = []) {
  const hasContent = Object.keys(form).length > 0
    || contentsItems.length > 0
    || missingFields.length > 0
  if (!hasContent) return []

  const sections = REVIEW_SECTION_DEFINITIONS.map((definition) => ({
    id: definition.id,
    title: definition.title,
    fields: [],
    contentsItems: definition.id === 'loss' ? contentsItems : [],
    missingFields: [],
  }))

  for (const entry of Object.entries(form)) {
    const sectionId = claimReviewSectionId(entry[0])
    sections.find((section) => section.id === sectionId).fields.push(entry)
  }

  for (const fieldCode of uniqueStrings(missingFields)) {
    const sectionId = claimReviewSectionId(fieldCode)
    sections.find((section) => section.id === sectionId).missingFields.push(fieldCode)
  }

  return sections
}

export function claimReviewRequirements(dynamicForm) {
  const requirements = dynamicForm?.requirements
  if (!requirements) {
    return {
      available: false,
      ready: false,
      missingRequiredNow: [],
      pendingLater: [],
      currentActionTotal: null,
      currentActionSatisfied: null,
    }
  }

  const total = requirements.current_action_total == null
    ? Number.NaN
    : Number(requirements.current_action_total)
  const satisfied = requirements.current_action_satisfied == null
    ? Number.NaN
    : Number(requirements.current_action_satisfied)

  return {
    available: true,
    ready: requirements.ready === true,
    missingRequiredNow: uniqueStrings(requirements.missing_required_now),
    pendingLater: uniqueStrings(requirements.pending_later),
    currentActionTotal: Number.isFinite(total) && total >= 0 ? total : null,
    currentActionSatisfied: Number.isFinite(satisfied) && satisfied >= 0 ? satisfied : null,
  }
}
