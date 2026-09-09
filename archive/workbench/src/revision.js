export function revisionNotice(current, next) {
  if (!current || !next || current.claim_id !== next.claim_id) return null
  if (current.revision === next.revision) return null
  return { claimId: next.claim_id, revision: next.revision }
}
