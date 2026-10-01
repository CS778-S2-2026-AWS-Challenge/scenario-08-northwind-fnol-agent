export function revisionNotice(current, next, ownRevision = null) {
  if (!current || !next || current.claim_id !== next.claim_id) return null
  if (current.revision === next.revision) return null
  // A revision produced by this staff member's own successful mutation is not a change from
  // another session. Mutations are revision-checked, so no foreign change can precede it.
  if (Number.isInteger(ownRevision) && next.revision <= ownRevision) return null
  return { claimId: next.claim_id, revision: next.revision }
}

export function mutationResultRevision(result) {
  if (Number.isInteger(result?.revision)) return result.revision
  if (Number.isInteger(result?.claim_revision)) return result.claim_revision
  return null
}
