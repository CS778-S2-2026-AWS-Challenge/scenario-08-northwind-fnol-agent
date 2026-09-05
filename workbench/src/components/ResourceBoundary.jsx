import { AlertTriangle } from 'lucide-react'

export default function ResourceBoundary({ resource, children }) {
  if (resource?.loading) return <div className="queue-state"><span className="loading-mark" /><p>Loading current records...</p></div>
  if (resource?.error) return <div className="claim-state claim-state--error" role="alert"><AlertTriangle /><h2>This section is unavailable</h2><p>{resource.error}</p></div>
  if (resource?.status === 'unavailable') return <div className="claim-state claim-state--error"><AlertTriangle /><h2>This source is unavailable</h2><p>{resource.limitation || 'The source did not provide a usable result.'}</p></div>
  return children
}
