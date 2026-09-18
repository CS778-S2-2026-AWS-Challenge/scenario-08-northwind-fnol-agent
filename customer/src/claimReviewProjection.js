const REVIEW_SECTION_DEFINITIONS = Object.freeze([
  {
    id: 'claimant',
    title: 'Claimant details',
    matches: (fieldCode) => fieldCode.startsWith('claimant.'),
  },
  {
    id: 'overview',
    title: 'Claim overview',
    matches: (fieldCode) => fieldCode === 'claim.product_family',
  },
  {
    id: 'incident',
    title: 'Incident details',
    matches: (fieldCode) => fieldCode.startsWith('incident.'),
  },
  {
    id: 'loss',
    title: 'Insured item and loss',
    matches: (fieldCode) => [
      'loss.',
      'vehicle.',
      'property.',
      'contents.',
    ].some((prefix) => fieldCode.startsWith(prefix)),
  },
  {
    id: 'parties',
    title: 'Other parties involved',
    matches: (fieldCode) => fieldCode.startsWith('parties.'),
  },
])

function uniqueStrings(values) {
  return [...new Set((values || []).filter((value) => typeof value === 'string' && value))]
}

export function claimReviewSections(form = {}, contentsItems = []) {
  const sections = REVIEW_SECTION_DEFINITIONS.map((definition) => ({
    id: definition.id,
    title: definition.title,
    fields: [],
    contentsItems: definition.id === 'loss' ? contentsItems : [],
  }))
  const fallback = {
    id: 'other',
    title: 'Other information',
    fields: [],
    contentsItems: [],
  }

  for (const entry of Object.entries(form)) {
    const [fieldCode] = entry
    const index = REVIEW_SECTION_DEFINITIONS.findIndex((definition) => definition.matches(fieldCode))
    if (index >= 0) sections[index].fields.push(entry)
    else fallback.fields.push(entry)
  }

  return [...sections, fallback].filter((section) => (
    section.fields.length > 0 || section.contentsItems.length > 0
  ))
}

export function claimReviewRequirements(dynamicForm) {
  const requirements = dynamicForm?.requirements
  if (!requirements) {
    return {
      available: false,
      ready: false,
      missingRequiredNow: [],
      pendingLater: [],
    }
  }

  return {
    available: true,
    ready: requirements.ready === true,
    missingRequiredNow: uniqueStrings(requirements.missing_required_now),
    pendingLater: uniqueStrings(requirements.pending_later),
  }
}
