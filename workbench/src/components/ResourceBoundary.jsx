import { AlertTriangle, RefreshCw } from 'lucide-react'
import { failureReason, failureReference } from '../failure.js'

export default function ResourceBoundary({ resource, children, onRetry }) {
  const hasRecords = Boolean(resource?.items?.length)
  if (!resource || (resource.loading && !hasRecords)) {
    return <div className="claim-state" role="status"><span className="loading-mark" /><p>Loading current records...</p></div>
  }
  if ((resource.error || resource.status === 'unavailable') && !hasRecords) {
    return <ResourceNotice resource={resource} onRetry={onRetry} />
  }
  return (
    <>
      {(resource.loading || resource.error || ['partial', 'unavailable'].includes(resource.status)) && (
        <ResourceNotice resource={resource} onRetry={onRetry} stale={hasRecords} />
      )}
      {children}
    </>
  )
}

function ResourceNotice({ resource, onRetry, stale = false }) {
  const loading = resource.loading
  const error = resource.error
  const partial = resource.status === 'partial' && !error
  const title = loading
    ? 'Refreshing this section'
    : partial
      ? 'Some source records are unavailable'
    : stale
      ? 'Showing saved records'
      : 'This section is unavailable'
  const message = loading
    ? 'The existing records remain visible while the latest source is loaded.'
    : partial
      ? 'Available records remain visible with the source limitation below.'
    : stale
      ? 'The latest source query failed, so the records below may be out of date.'
      : 'The source did not return usable records. Retry without leaving the Claim.'
  return (
    <div className={`resource-notice${error ? ' resource-notice--error' : ''}`} role={error ? 'alert' : 'status'}>
      {error ? <AlertTriangle size={18} aria-hidden="true" /> : <RefreshCw size={18} aria-hidden="true" />}
      <div>
        <strong>{title}</strong>
        <p>{message}</p>
        {!loading && <small>{resource.limitation || failureReason(error)}</small>}
        {failureReference(error) && <small>{failureReference(error)}</small>}
      </div>
      {!loading && onRetry && <button className="button button--quiet" type="button" onClick={onRetry}>Retry section</button>}
    </div>
  )
}
