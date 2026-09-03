import { BriefcaseBusiness, LockKeyhole } from 'lucide-react'
import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/auth-context.js'

export default function LoginPage() {
  const { session, login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()

  if (session) return <Navigate to="/workbench" replace />

  async function submit(event) {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      await login(email, password)
      const destination = location.state?.from
      navigate(destination?.startsWith('/workbench') ? destination : '/workbench', {
        replace: true,
      })
    } catch (nextError) {
      setError(nextError.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="staff-login">
      <section className="staff-login__context" aria-labelledby="staff-login-heading">
        <div className="brand-lockup">
          <span className="brand-mark"><BriefcaseBusiness size={22} /></span>
          <span>Northwind Claims</span>
        </div>
        <div>
          <p className="eyebrow">Claims operations</p>
          <h1 id="staff-login-heading">Continue the work that matters now.</h1>
          <p className="staff-login__lead">
            Review claimant needs, evidence, conversations, and next actions in one accountable
            workspace.
          </p>
        </div>
        <p className="staff-login__privacy">
          Staff access is separate from claimant accounts and every business action remains
          attributable.
        </p>
      </section>
      <section className="staff-login__form-wrap" aria-label="Staff sign in">
        <form className="staff-login__form" onSubmit={submit}>
          <span className="form-icon"><LockKeyhole size={22} /></span>
          <p className="eyebrow">Secure staff access</p>
          <h2>Sign in to Workbench</h2>
          <label>
            Work email
            <input
              type="email"
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </label>
          <label>
            Password
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="button button--primary button--wide" type="submit" disabled={submitting}>
            {submitting ? 'Signing in...' : 'Sign in'}
          </button>
        </form>
      </section>
    </main>
  )
}
