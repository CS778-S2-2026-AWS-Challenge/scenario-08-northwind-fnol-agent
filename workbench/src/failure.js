export function failureReason(error) {
  if (!error) return ''
  return typeof error === 'string' ? error : error.message || 'The service did not return a usable result.'
}

export function failureReference(error) {
  return typeof error === 'object' && error?.requestId
    ? `Request reference: ${error.requestId}`
    : ''
}

export function actionFailureMessage(action, error) {
  const latest = error.projectionReloaded
    ? ` The latest server projection${error.latestRevision ? ` at revision ${error.latestRevision}` : ''} is now shown.`
    : ''
  const reference = failureReference(error)
  const suffix = reference ? ` ${reference}.` : ''

  if (error.code === 'REVISION_CONFLICT') {
    return `${action} was not completed because the Claim changed after this action was opened.${latest} Review the latest state and your preserved input before trying again.${suffix}`
  }
  if (error.code === 'IDEMPOTENCY_CONFLICT') {
    return `${action} was not completed because this request differs from the original attempt.${latest} Review the current action before trying again.${suffix}`
  }
  if (error.code === 'OWNERSHIP_CONFLICT') {
    return `${action} was not completed because another ownership request now conflicts with it.${latest} Review the current owner and pending requests before continuing.${suffix}`
  }
  if (error.code === 'ACCESS_DENIED' || error.status === 403) {
    return `${action} was not completed because this staff identity is not authorised for the current action.${latest} Ask the primary owner or an authorised colleague to continue.${suffix}`
  }
  if (error.code === 'RESOURCE_NOT_FOUND' || error.status === 404) {
    return `${action} was not completed because the Claim or target is no longer available to this account. Return to the queue and refresh it.${suffix}`
  }
  if (!error.projectionReloaded) {
    return `The outcome of ${action.toLowerCase()} could not be confirmed because ${failureReason(error)} Do not submit it again until the Claim projection can be refreshed.${suffix}`
  }
  return `${action} could not be confirmed because ${failureReason(error)}${latest} Review the current state before retrying; an identical retry reuses the same operation key.${suffix}`
}
