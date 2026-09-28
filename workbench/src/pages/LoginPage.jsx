import { BriefcaseBusiness, LockKeyhole } from 'lucide-react'
import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/auth-context.js'
import { translate as t, useLanguage } from '../i18n.js'

export default function LoginPage() {
  useLanguage()
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
          <span>{t('Northwind Claims')}</span>
        </div>
        <div>
          <p className="eyebrow">{t('Claims operations')}</p>
          <h1 id="staff-login-heading">{t('Continue the work that matters now.')}</h1>
          <p className="staff-login__lead">
            {t('Review claimant needs, evidence, conversations, and next actions in one accountable workspace.')}
          </p>
        </div>
        <p className="staff-login__privacy">
          {t('Staff access is separate from claimant accounts and every business action remains attributable.')}
        </p>
      </section>
      <section className="staff-login__form-wrap" aria-label={t('Staff sign in')}>
        <form className="staff-login__form" onSubmit={submit}>
          <span className="form-icon"><LockKeyhole size={22} /></span>
          <p className="eyebrow">{t('Secure staff access')}</p>
          <h2>{t('Sign in to Workbench')}</h2>
          <label>
            {t('Work email')}
            <input
              type="email"
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </label>
          <label>
            {t('Password')}
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
            {t(submitting ? 'Signing in...' : 'Sign in')}
          </button>
        </form>
      </section>
    </main>
  )
}
