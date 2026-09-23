import { useEffect, useRef, useState } from 'react'

import { FeatureNotice, ResourceError } from './ProfilePrimitives.jsx'
import { maskPolicyNumber } from './policyNumber.js'
import { profileMutationMessage } from './profileMutation.js'

export default function PolicyNumberDetails({
  announceResourceState = true,
  editingDisabled = false,
  fallbackFocusId,
  resource,
  pending,
  onBeginCreate,
  onAbandonCreate,
  onCreate,
  onReload,
  onUpdate,
  onEditingChange,
}) {
  const [editor, setEditor] = useState(null)
  const [draft, setDraft] = useState('')
  const [notice, setNotice] = useState(null)
  const inputRef = useRef(null)
  const returnFocusIdRef = useRef(null)
  const policies = resource.items
  const authoritative = policies !== null && !resource.error && !resource.loading && !resource.stale

  useEffect(() => { if (editor && authoritative) inputRef.current?.focus() }, [authoritative, editor])

  useEffect(() => { onEditingChange?.(Boolean(editor)) }, [editor, onEditingChange])

  useEffect(() => {
    if (editor || !returnFocusIdRef.current) return
    const triggerId = returnFocusIdRef.current
    returnFocusIdRef.current = null
    const target = globalThis.document?.getElementById(triggerId)
      || globalThis.document?.getElementById(fallbackFocusId)
    target?.focus()
  }, [editor, fallbackFocusId])

  function closeEditor() {
    if (editor?.mode === 'create') onAbandonCreate('policy', editor.attemptId)
    setEditor(null)
    setDraft('')
  }

  function beginCreate(event) {
    setNotice(null)
    returnFocusIdRef.current = event.currentTarget.id
    setEditor({ mode: 'create', attemptId: onBeginCreate('policy') })
  }

  function beginEdit(policy, event) {
    setNotice(null)
    returnFocusIdRef.current = event.currentTarget.id
    setEditor({ mode: 'edit', policyId: policy.policy_id })
    setDraft(policy.policy_number)
  }

  async function save(event) {
    event.preventDefault()
    const policyNumber = draft.trim()
    if (!policyNumber) return
    const current = editor.mode === 'edit'
      ? policies?.find((policy) => policy.policy_id === editor.policyId)
      : null
    try {
      const saved = current
        ? await onUpdate(current.policy_id, current.revision, policyNumber)
        : await onCreate({ policyNumber, attemptId: editor.attemptId })
      setNotice({ kind: 'success', text: `Policy number ${maskPolicyNumber(saved.policy_number)} was saved to your Profile.` })
      setEditor(null)
      setDraft('')
    } catch (error) {
      setNotice({ kind: 'error', text: profileMutationMessage(error, 'Northwind could not save this policy number.') })
    }
  }

  const saving = editor?.mode === 'create'
    ? Boolean(pending['policy-create'])
    : Boolean(pending[`policy:${editor?.policyId}`])

  return (
    <div className="profile-policy-details" role="group" aria-label="Saved policy number controls">
      <FeatureNotice notice={notice} />
      <p className="profile-helper-copy">A saved policy number does not confirm coverage or attach it to a Claim.</p>
      <ResourceError
        announce={announceResourceState}
        message={resource.error}
        onRetry={onReload}
        retainedLabel={resource.stale ? 'saved policy numbers' : ''}
      />
      {policies === null && !resource.error && (
        <p className="profile-assets-loading" role={announceResourceState ? 'status' : undefined}>
          Loading saved policy numbers…
        </p>
      )}
      {authoritative && policies.length === 0 && !editor && <p className="profile-assets-empty">No policy numbers saved.</p>}
      {policies !== null && policies.length > 0 && (
        <ul className="profile-record-list" aria-label="Saved policy numbers">
          {policies.map((policy) => (
            <li key={policy.policy_id} className="profile-record-row">
              <span><strong>Policy number</strong><span>{maskPolicyNumber(policy.policy_number)}</span></span>
              {authoritative && (
                <button
                  id={`profile-policy-edit-${policy.policy_id}`}
                  className="profile-quiet-action"
                  type="button"
                  disabled={editingDisabled || Boolean(pending[`policy:${policy.policy_id}`])}
                  aria-label={`Edit policy number ${maskPolicyNumber(policy.policy_number)}`}
                  onClick={(event) => beginEdit(policy, event)}
                >
                  Edit
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {authoritative && !editor && (
        <button
          id="profile-policy-add-button"
          className="profile-asset-add-action"
          type="button"
          disabled={editingDisabled || Boolean(pending['policy-create'])}
          onClick={beginCreate}
        >
          <span aria-hidden="true">+</span> Add policy number
        </button>
      )}
      {editor && (
        <form className="profile-edit-form profile-record-form" onSubmit={save}>
          <h3>{editor.mode === 'create' ? 'Add policy number' : 'Edit policy number'}</h3>
          <label htmlFor="profile-policy-number">Policy number</label>
          <input
            ref={inputRef}
            id="profile-policy-number"
            type="text"
            value={draft}
            minLength={1}
            maxLength={200}
            autoComplete="off"
            required
            disabled={saving}
            onChange={(event) => setDraft(event.target.value)}
          />
          {!authoritative && (
            <p className="profile-helper-copy">
              Policy data is being refreshed or could not be confirmed. Retry the load or cancel this draft.
            </p>
          )}
          <p className="profile-helper-copy">Northwind stores policy numbers as reusable account records. Choosing one for a Claim is a separate step and does not decide coverage.</p>
          <div className="profile-asset-form-actions">
            <button className="primary-button" type="submit" disabled={!authoritative || saving || !draft.trim()}>{saving ? 'Saving…' : 'Save policy number'}</button>
            <button className="profile-quiet-action" type="button" disabled={saving} onClick={closeEditor}>Cancel</button>
          </div>
        </form>
      )}
    </div>
  )
}
