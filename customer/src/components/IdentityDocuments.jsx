import { useEffect, useRef, useState } from 'react'

import { FeatureNotice, ResourceError } from '../profile/ProfilePrimitives.jsx'
import { profileMutationMessage } from '../profile/profileMutation.js'

const DOCUMENT_TYPES = [
  { value: 'driver_licence', label: 'Driver licence' },
  { value: 'passport', label: 'Passport' },
]

function documentLabel(type) {
  return DOCUMENT_TYPES.find(({ value }) => value === type)?.label || 'Identity document'
}

export default function IdentityDocuments({
  resource,
  pending,
  onBeginCreate,
  onAbandonCreate,
  onCreate,
  onReload,
  onUpdate,
}) {
  const documents = resource.items
  const [editor, setEditor] = useState(null)
  const [draft, setDraft] = useState('')
  const [notice, setNotice] = useState(null)
  const inputRef = useRef(null)
  const selectRef = useRef(null)
  const addButtonRef = useRef(null)
  const editButtonRefs = useRef(new Map())
  const returnFocusRef = useRef(null)

  useEffect(() => {
    if (editor?.mode === 'add') selectRef.current?.focus()
    if (editor?.mode === 'edit') inputRef.current?.focus()
    if (!editor && documents && returnFocusRef.current) {
      const target = returnFocusRef.current.mode === 'add'
        ? addButtonRef.current
        : editButtonRefs.current.get(returnFocusRef.current.identityId)
      target?.focus()
      returnFocusRef.current = null
    }
  }, [editor, documents])

  function closeEditor() {
    if (editor?.mode === 'add') onAbandonCreate('identity', editor.attemptId)
    setDraft('')
    setEditor(null)
  }

  function beginAdd() {
    closeEditor()
    returnFocusRef.current = { mode: 'add' }
    setNotice(null)
    setEditor({
      mode: 'add',
      documentType: 'driver_licence',
      attemptId: onBeginCreate('identity'),
    })
  }

  function beginEdit(document) {
    closeEditor()
    returnFocusRef.current = { mode: 'edit', identityId: document.identity_id }
    setNotice(null)
    setEditor({ mode: 'edit', identityId: document.identity_id })
  }

  async function save(event) {
    event.preventDefault()
    if (!draft.trim()) return
    const number = draft.trim()
    const current = editor.mode === 'edit'
      ? documents.find((document) => document.identity_id === editor.identityId)
      : null
    if (editor.mode === 'edit' && !current) {
      setNotice({ kind: 'error', text: 'This document is no longer in the saved list. Review the latest list before editing again.' })
      return
    }
    setNotice(null)
    try {
      const saved = current
        ? await onUpdate(current.identity_id, current.revision, number)
        : await onCreate({
          documentType: editor.documentType,
          documentNumber: number,
          attemptId: editor.attemptId,
        })
      setDraft('')
      setEditor(null)
      setNotice({ kind: 'success', text: `${documentLabel(saved.document_type)} saved. Only its masked number is shown.` })
    } catch (error) {
      setNotice({
        kind: 'error',
        text: profileMutationMessage(error, 'Northwind could not save this identity document.'),
      })
    }
  }

  const editingDocument = editor?.mode === 'edit'
    ? documents?.find((document) => document.identity_id === editor.identityId)
    : null
  const saving = editor?.mode === 'add'
    ? Boolean(pending['identity-create'])
    : Boolean(pending[`identity:${editor?.identityId}`])

  return (
    <div className="profile-identity-documents">
      <p className="profile-helper-copy">Saved numbers are shown only in masked form. Saving a number does not verify your identity.</p>
      <FeatureNotice notice={notice} />
      <ResourceError message={resource.error} onRetry={onReload} />
      {documents === null && !resource.error && <p className="profile-assets-loading" role="status">Loading saved identity documents…</p>}
      {documents && (
        <>
          {documents.length === 0
            ? <p className="profile-assets-empty">No identity documents saved.</p>
            : (
              <ul className="profile-identity-list" aria-label="Saved identity documents">
                {documents.map((document) => (
                  <li key={document.identity_id} className="profile-identity-row">
                    <span><strong>{documentLabel(document.document_type)}</strong><span>{document.masked_document_number}</span></span>
                    <button
                      ref={(node) => {
                        if (node) editButtonRefs.current.set(document.identity_id, node)
                        else editButtonRefs.current.delete(document.identity_id)
                      }}
                      className="profile-quiet-action"
                      type="button"
                      disabled={Boolean(pending[`identity:${document.identity_id}`])}
                      onClick={() => beginEdit(document)}
                      aria-label={`Edit ${documentLabel(document.document_type)} ${document.masked_document_number}`}
                    >Edit</button>
                  </li>
                ))}
              </ul>
            )}
          {!editor && (
            <button ref={addButtonRef} className="profile-asset-add-action" type="button" disabled={Boolean(pending['identity-create'])} onClick={beginAdd}>
              <span aria-hidden="true">+</span> Add identity document
            </button>
          )}
        </>
      )}
      {editor && documents && (
        <form className="profile-edit-form profile-identity-form" onSubmit={save}>
          <h3>{editor.mode === 'add' ? 'Add identity document' : `Edit ${documentLabel(editingDocument?.document_type)}`}</h3>
          {editor.mode === 'add' ? (
            <>
              <label htmlFor="profile-identity-type">Document type</label>
              <select
                ref={selectRef}
                id="profile-identity-type"
                value={editor.documentType}
                disabled={saving}
                onChange={(event) => setEditor((current) => ({ ...current, documentType: event.target.value }))}
              >
                {DOCUMENT_TYPES.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
              </select>
            </>
          ) : <p className="profile-helper-copy">Current number: {editingDocument?.masked_document_number}. Enter the full new number below.</p>}
          <label htmlFor="profile-identity-number">{documentLabel(editor.mode === 'add' ? editor.documentType : editingDocument?.document_type)} number</label>
          <input
            ref={inputRef}
            id="profile-identity-number"
            type="text"
            value={draft}
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
            minLength={4}
            maxLength={80}
            required
            disabled={saving}
            onChange={(event) => setDraft(event.target.value)}
          />
          <div className="profile-asset-form-actions">
            <button className="primary-button" type="submit" disabled={saving || !draft.trim()}>{saving ? 'Saving…' : 'Save identity document'}</button>
            <button className="profile-quiet-action" type="button" disabled={saving} onClick={closeEditor}>Cancel</button>
          </div>
        </form>
      )}
    </div>
  )
}
