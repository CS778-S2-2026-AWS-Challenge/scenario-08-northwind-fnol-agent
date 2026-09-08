import { RefreshCw } from 'lucide-react'
import { Link } from 'react-router-dom'

export default function CollectionState({ status, error, label, reload, children }) {
  if (status === 'loading') return <p role="status" className="notice">Loading {label.toLowerCase()} from the Admin API...</p>
  if (status !== 'error') return children
  return (
    <section className="notice error" role="alert">
      <h1>Unable to load {label.toLowerCase()}</h1>
      <p>{error.message}</p>
      <p>Check the API connection and administrator access, then retry.</p>
      {error.status === 401 || error.status === 403 ? <Link to="/admin/login">Sign in again</Link> : <button className="secondary" onClick={reload}><RefreshCw aria-hidden="true" />Retry</button>}
    </section>
  )
}
