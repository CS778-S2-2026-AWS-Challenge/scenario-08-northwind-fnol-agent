// Readable explanations for `unavailable_reason` codes from `GET /workbench/agent/capabilities`.
const UNAVAILABLE_REASONS = {
  profile_unavailable: 'The selected model profile is marked unavailable for this environment.',
  endpoint_unavailable: 'The selected model has no configured endpoint in this environment.',
  credential_unavailable: 'The selected model has no configured credential in this environment.',
}

export function staffAgentUnavailableReason(models, modelProfileId) {
  if (!models.length) return 'No Staff Agent model is published for this Workbench environment.'
  const model = models.find((item) => item.id === modelProfileId)
  if (!model) return 'The model selected for this session is not published in this Workbench environment.'
  if (model.availability !== 'unavailable') return null
  return UNAVAILABLE_REASONS[model.unavailable_reason] || 'The model selected for this session is not ready.'
}
