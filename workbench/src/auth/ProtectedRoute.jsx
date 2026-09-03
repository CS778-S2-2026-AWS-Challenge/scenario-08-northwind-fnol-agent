import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './auth-context.js'

export default function ProtectedRoute({ children }) {
  const { session, checking } = useAuth()
  const location = useLocation()

  if (checking) {
    return (
      <main className="center-state" aria-live="polite">
        <span className="loading-mark" aria-hidden="true" />
        <p>Opening your Workbench...</p>
      </main>
    )
  }
  if (!session) {
    return <Navigate to="/workbench/login" replace state={{ from: `${location.pathname}${location.search}` }} />
  }
  return children
}
