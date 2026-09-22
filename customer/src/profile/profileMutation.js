export class ProfileMutationError extends Error {
  constructor(message, { code, kind, cause } = {}) {
    super(message, cause ? { cause } : undefined)
    this.name = 'ProfileMutationError'
    this.code = code
    this.kind = kind
  }
}

export function profileMutationMessage(error, fallback) {
  if (error instanceof ProfileMutationError) return error.message
  if (error?.status === 401) {
    return 'Your session expired before Northwind could save this change. Sign in again, reopen Profile, and review your draft.'
  }
  if (error?.status === 403) {
    return 'This session cannot change this Profile information. Sign in with the account that owns it and try again.'
  }
  if (error?.code === 'RESOURCE_CONFLICT') {
    return 'Northwind did not save this change because the value conflicts with another account record. Review the value and try again.'
  }
  if (error?.code === 'IDEMPOTENCY_CONFLICT') {
    return 'Northwind found a different request with this save identity. Cancel this editor, start a new entry, and try again.'
  }
  if (error?.status === 422) {
    return `${error.message || 'Northwind could not validate this information.'} Review the highlighted values and try again.`
  }
  if (error?.status === 503) {
    return `${error.message || fallback} The service is unavailable, so Northwind did not confirm a save. Keep your draft and try again later.`
  }
  return `Your changes were not saved. ${error?.message || fallback} Northwind did not confirm the change. Review your draft and try again.`
}
