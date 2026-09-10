import { useEffect, useState } from 'react'
import { Activity, BookOpen, Boxes, ClipboardList, DatabaseZap, FileClock, Gauge, LogOut, Settings2, ShieldCheck, Users } from 'lucide-react'
import { Link, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { ADMIN_ACCESS_DENIED_EVENT, adminFetch, getToken, setToken } from './api.js'
import AccountsPage from './pages/AccountsPage.jsx'
import AuditPage from './pages/AuditPage.jsx'
import ConfigurationPage from './pages/ConfigurationPage.jsx'
import EvaluationPage from './pages/EvaluationPage.jsx'
import IntegrationsPage from './pages/IntegrationsPage.jsx'
import KnowledgePage from './pages/KnowledgePage.jsx'
import OperationsPage from './pages/OperationsPage.jsx'
import ReleasePage from './pages/ReleasePage.jsx'
import RuntimeSnapshotPage from './pages/RuntimeSnapshotPage.jsx'

const navigation = [
  { path: '/admin/configurations', label: 'Configurations', icon: Settings2 },
  { path: '/admin/releases', label: 'Release Sets', icon: Boxes },
  { path: '/admin/runtime', label: 'Runtime Snapshot', icon: DatabaseZap },
  { path: '/admin/knowledge', label: 'Knowledge', icon: BookOpen },
  { path: '/admin/evaluations', label: 'Evaluations', icon: ClipboardList },
  { path: '/admin/operations', label: 'Operations', icon: Activity },
  { path: '/admin/integrations', label: 'Integrations', icon: Gauge },
  { path: '/admin/audit', label: 'Audit', icon: FileClock },
  { path: '/admin/customers', label: 'Customers', icon: Users },
  { path: '/admin/staff', label: 'Staff', icon: ShieldCheck },
]

const accessProbe = '/internal/v1/admin/configurations?limit=1'

function accessFailure(error) {
  if (error?.status === 401) return 'unauthenticated'
  if (error?.status === 403) return 'denied'
  return 'unavailable'
}

function AdminAccessBoundary({ token, children }) {
  const navigate = useNavigate()
  const [attempt, setAttempt] = useState(0)
  const [access, setAccess] = useState({ status: 'checking', error: null })

  useEffect(() => {
    let active = true
    const rejectAccess = (event) => {
      if (active) setAccess({ status: accessFailure(event.detail), error: event.detail })
    }
    window.addEventListener(ADMIN_ACCESS_DENIED_EVENT, rejectAccess)
    adminFetch(accessProbe, { token })
      .then(() => {
        if (active) setAccess({ status: 'allowed', error: null })
      })
      .catch((error) => {
        if (active) setAccess({ status: accessFailure(error), error })
      })
    return () => {
      active = false
      window.removeEventListener(ADMIN_ACCESS_DENIED_EVENT, rejectAccess)
    }
  }, [attempt, token])

  function useAnotherToken() {
    setToken('')
    navigate('/admin/login', { replace: true })
  }

  function retry() {
    setAccess({ status: 'checking', error: null })
    setAttempt((value) => value + 1)
  }

  if (access.status === 'allowed') return children

  if (access.status === 'checking') {
    return (
      <main className="login-page">
        <section className="login-card" role="status" aria-live="polite">
          <p className="eyebrow">Northwind Control Plane</p>
          <h1>Checking administrator access</h1>
          <p>The Admin API is verifying this identity before restricted navigation is loaded.</p>
        </section>
      </main>
    )
  }

  if (access.status === 'unauthenticated' || access.status === 'denied') {
    const denied = access.status === 'denied'
    return (
      <main className="login-page">
        <section className="login-card notice error" role="alert">
          <p className="eyebrow">Northwind Control Plane</p>
          <h1>{denied ? 'Access denied' : 'Sign-in failed'}</h1>
          <p>{access.error?.message || 'The administrator identity could not be verified.'}</p>
          <p>{denied ? 'This identity does not have administrator access.' : 'The token is missing, invalid, or expired.'} No restricted records or navigation were loaded.</p>
          {access.error?.requestId && <p className="muted">Request ID: {access.error.requestId}</p>}
          <button type="button" className="primary" onClick={useAnotherToken}>Use another token</button>
        </section>
      </main>
    )
  }

  return (
    <main className="login-page">
      <section className="login-card notice error" role="alert">
        <p className="eyebrow">Northwind Control Plane</p>
        <h1>Admin Console unavailable</h1>
        <p>The Admin API could not verify access, so restricted navigation was not loaded.</p>
        <p>{access.error?.message || 'The service did not return a usable response.'}</p>
        <p>Check the API connection, then retry.</p>
        {access.error?.requestId && <p className="muted">Request ID: {access.error.requestId}</p>}
        <button type="button" className="primary" onClick={retry}>Retry access check</button>
      </section>
    </main>
  )
}

function Login() {
  const navigate = useNavigate()
  const [value, setValue] = useState(getToken())
  function submit(event) {
    event.preventDefault()
    setToken(value.trim())
    navigate('/admin')
  }
  return (
    <main className="login-page">
      <form className="login-card" onSubmit={submit}>
        <p className="eyebrow">Northwind Control Plane</p>
        <h1>Sign in to administration</h1>
        <p>Use an administrator bearer token. Provider and database credentials remain behind the server boundary.</p>
        <label className="field"><span>Administrator token</span><input type="password" value={value} onChange={(event) => setValue(event.target.value)} autoComplete="off" required /></label>
        <button className="primary" disabled={!value.trim()}><ShieldCheck aria-hidden="true" />Continue</button>
      </form>
    </main>
  )
}

function Shell({ children }) {
  const location = useLocation()
  const navigate = useNavigate()
  return (
    <div className="app-shell">
      <aside className="nav-rail">
        <Link className="brand" to="/admin">Northwind<span>Control Plane</span></Link>
        <nav aria-label="Administration navigation">
          {navigation.map(({ path, label, icon: Icon }) => <Link className={location.pathname === path ? 'active' : ''} key={path} to={path}><Icon aria-hidden="true" /><span>{label}</span></Link>)}
        </nav>
        <button className="quiet" onClick={() => { setToken(''); navigate('/admin/login') }}><LogOut aria-hidden="true" />Sign out</button>
      </aside>
      <main className="content">{children}</main>
    </div>
  )
}

function Overview() {
  return (
    <>
      <header className="page-header"><div><p className="eyebrow">Northwind</p><h1>Administration overview</h1><p>Manage versioned runtime inputs, inspect the active release, operate governed services, and audit changes through the authenticated Admin API.</p></div></header>
      <div className="overview-grid">{navigation.map(({ path, label, icon: Icon }) => <Link className="overview-card" to={path} key={path}><Icon aria-hidden="true" /><strong>{label}</strong><span>Open server-backed view</span></Link>)}</div>
    </>
  )
}

function ProtectedRoutes() {
  const token = getToken()
  if (!token) return <Navigate to="/admin/login" replace />
  return (
    <AdminAccessBoundary token={token}>
      <Shell>
        <Routes>
          <Route path="/admin" element={<Overview />} />
          <Route path="/admin/configurations" element={<ConfigurationPage />} />
          <Route path="/admin/releases" element={<ReleasePage />} />
          <Route path="/admin/runtime" element={<RuntimeSnapshotPage />} />
          <Route path="/admin/knowledge" element={<KnowledgePage />} />
          <Route path="/admin/evaluations" element={<EvaluationPage />} />
          <Route path="/admin/operations" element={<OperationsPage />} />
          <Route path="/admin/integrations" element={<IntegrationsPage />} />
          <Route path="/admin/audit" element={<AuditPage />} />
          <Route path="/admin/customers" element={<AccountsPage kind="customers" />} />
          <Route path="/admin/staff" element={<AccountsPage kind="staff" />} />
          <Route path="*" element={<Navigate to="/admin" replace />} />
        </Routes>
      </Shell>
    </AdminAccessBoundary>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/admin/login" element={<Login />} />
      <Route path="*" element={<ProtectedRoutes />} />
    </Routes>
  )
}
