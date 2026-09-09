import { useState } from 'react'
import { Plus, Save, ShieldX } from 'lucide-react'
import { adminMutation, getToken } from '../api.js'
import ActionPanel from '../components/ActionPanel.jsx'
import CollectionState from '../components/CollectionState.jsx'
import { Feedback, Field } from '../components/FormControls.jsx'
import PageHeader from '../components/PageHeader.jsx'
import ResourceWorkspace from '../components/ResourceWorkspace.jsx'
import useAdminCollection from '../hooks/useAdminCollection.js'
import useSelection from '../hooks/useSelection.js'

function CreateAccount({ kind, onDone }) {
  const [email, setEmail] = useState('')
  const [initialPassword, setInitialPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [phone, setPhone] = useState('')
  const [roles, setRoles] = useState('claims_professional')
  const [feedback, setFeedback] = useState(null)

  async function submit(event) {
    event.preventDefault()
    setFeedback({ kind: 'working', message: 'Creating the account in the identity repository...' })
    const body = kind === 'customers'
      ? { email, initial_password: initialPassword, display_name: displayName, phone }
      : { email, initial_password: initialPassword, display_name: displayName, roles: roles.split(',').map((role) => role.trim()).filter(Boolean) }
    try {
      await adminMutation(`/internal/v1/admin/accounts/${kind}`, { token: getToken(), body })
      setFeedback({ kind: 'success', message: 'The account was created without returning its credential.' })
      setEmail('')
      setInitialPassword('')
      setDisplayName('')
      setPhone('')
      onDone()
    } catch (error) {
      setFeedback({ kind: 'error', error })
    }
  }

  return (
    <details className="create-panel">
      <summary><Plus aria-hidden="true" />Create {kind === 'customers' ? 'customer' : 'staff'} account</summary>
      <form className="control-form form-grid" onSubmit={submit}>
        <Field label="Email"><input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="off" required /></Field>
        <Field label="Display name"><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} required /></Field>
        <Field label="Initial password" hint="Sent only to the identity API and never returned."><input type="password" value={initialPassword} onChange={(event) => setInitialPassword(event.target.value)} autoComplete="new-password" minLength="8" required /></Field>
        {kind === 'customers'
          ? <Field label="Phone"><input value={phone} onChange={(event) => setPhone(event.target.value)} /></Field>
          : <Field label="Roles" hint="Comma-separated staff roles."><input value={roles} onChange={(event) => setRoles(event.target.value)} required /></Field>}
        <button className="primary"><Plus aria-hidden="true" />Create account</button>
      </form>
      <Feedback state={feedback} />
    </details>
  )
}

function AccountAction({ action, kind, item, setFeedback, onDone }) {
  const [displayName, setDisplayName] = useState(item.display_name)
  const [phone, setPhone] = useState(item.phone || '')
  const [roles, setRoles] = useState((item.roles || []).join(', '))
  const [active, setActive] = useState(item.active)
  const [confirmed, setConfirmed] = useState(false)
  const deactivating = item.active && !active

  async function submit(event) {
    event.preventDefault()
    setFeedback({ kind: 'working', message: 'Updating the account through the identity repository...' })
    try {
      const body = kind === 'customers' ? { display_name: displayName, phone, active } : { display_name: displayName, roles: roles.split(',').map((role) => role.trim()).filter(Boolean), active }
      await adminMutation(`/internal/v1/admin/accounts/${kind}/${kind === 'customers' ? item.customer_id : item.staff_id}`, { token: getToken(), method: 'PATCH', revision: action.expected_revision, body })
      setFeedback({ kind: 'success', message: 'The account and append-only audit record were updated.' })
      onDone()
    } catch (error) {
      setFeedback({ kind: 'error', error })
    }
  }
  return (
    <form className="control-form" onSubmit={submit}>
      <Field label="Display name"><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} required /></Field>
      {kind === 'customers' ? <Field label="Phone"><input value={phone} onChange={(event) => setPhone(event.target.value)} /></Field> : <Field label="Roles" hint="Comma-separated registered staff roles."><input value={roles} onChange={(event) => setRoles(event.target.value)} required /></Field>}
      <label className="confirmation"><input type="checkbox" checked={active} onChange={(event) => { setActive(event.target.checked); setConfirmed(false) }} /><span>Account is active</span></label>
      {deactivating && <label className="confirmation warning"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /><span>I confirm that new authentication for this account will be blocked.</span></label>}
      <button className="primary" disabled={deactivating && !confirmed}><Save aria-hidden="true" />Save account</button>
    </form>
  )
}

function AccountSessions({ kind, item }) {
  const accountId = kind === 'customers' ? item.customer_id : item.staff_id
  const collection = useAdminCollection(`/internal/v1/admin/accounts/${kind}/${accountId}/sessions`, getToken())
  const [pending, setPending] = useState(null)
  const [confirmed, setConfirmed] = useState(false)
  const [feedback, setFeedback] = useState(null)

  async function revoke(event) {
    event.preventDefault()
    setFeedback({ kind: 'working', message: 'Revoking the selected identity session...' })
    try {
      await adminMutation(`/internal/v1/admin/accounts/${kind}/${accountId}/sessions/${pending.session_id}/revoke`, { token: getToken(), revision: pending.revision })
      setFeedback({ kind: 'success', message: 'The session was revoked and can no longer authenticate.' })
      setPending(null)
      setConfirmed(false)
      collection.reload()
    } catch (error) {
      setFeedback({ kind: 'error', error })
    }
  }

  return (
    <section className="history" aria-labelledby="identity-sessions-heading">
      <div className="section-heading"><h3 id="identity-sessions-heading">Identity sessions</h3></div>
      {collection.status === 'loading' && <p role="status" className="muted">Loading session state...</p>}
      {collection.status === 'error' && <Feedback state={{ kind: 'error', error: collection.error }} />}
      {collection.status === 'ready' && collection.items.length === 0 && <p className="muted">No identity sessions exist for this account.</p>}
      {collection.status === 'ready' && collection.items.length > 0 && (
        <ul>
          {collection.items.map((session) => {
            const revokeAction = session.allowed_actions.find((action) => action.action_code === 'admin.account_session.revoke')
            return (
              <li key={session.session_id}>
                <strong>{session.state}</strong>
                <span>{session.session_id}</span>
                <span>Expires {new Date(session.expires_at).toLocaleString()}</span>
                <button type="button" className="secondary" disabled={revokeAction?.availability === 'blocked'} onClick={() => { setPending(session); setConfirmed(false); setFeedback(null) }}><ShieldX aria-hidden="true" />Revoke session</button>
              </li>
            )
          })}
        </ul>
      )}
      {pending && (
        <form className="control-form" onSubmit={revoke}>
          <label className="confirmation warning"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /><span>I confirm revocation of {pending.session_id}.</span></label>
          <button className="primary" disabled={!confirmed}><ShieldX aria-hidden="true" />Confirm revocation</button>
        </form>
      )}
      <Feedback state={feedback} />
    </section>
  )
}

export default function AccountsPage({ kind }) {
  const label = kind === 'customers' ? 'Customers' : 'Staff'
  const collection = useAdminCollection(`/internal/v1/admin/accounts/${kind}`, getToken())
  const [selected, setSelected] = useSelection(collection.items)
  return (
    <>
      <PageHeader title={label} summary={`${collection.items.length} account projections from the identity repository`} onRefresh={collection.reload} />
      <CreateAccount kind={kind} onDone={collection.reload} />
      <CollectionState {...collection} label={label}>
        <ResourceWorkspace label={label} items={collection.items} selected={selected} onSelect={setSelected}>
          <ActionPanel actions={selected?.allowed_actions} renderForm={(action, setFeedback) => <AccountAction key={`${selected.customer_id || selected.staff_id}-${selected.revision}`} action={action} kind={kind} item={selected} setFeedback={setFeedback} onDone={collection.reload} />} />
          {selected && <AccountSessions kind={kind} item={selected} />}
        </ResourceWorkspace>
      </CollectionState>
    </>
  )
}
