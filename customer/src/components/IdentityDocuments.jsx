import { useCallback, useEffect, useRef, useState } from 'react'

import {
  createAccountIdentityDocument,
  listAccountIdentityDocuments,
  requestId,
  updateAccountIdentityDocument,
} from '../api.js'

const DOCUMENT_TYPES = [
  { value: 'driver_licence', label: 'Driver licence' },
  { value: 'passport', label: 'Passport' },
]

function documentLabel(type) {
  return DOCUMENT_TYPES.find(({ value }) => value === type)?.label || 'Identity document'
}

async function readIdentityDocuments(signal) {
  const items = []
  const seenCursors = new Set()
  let cursor = null
  do {
    const page = await listAccountIdentityDocuments({ cursor, signal })
    items.push(...page.items)
    cursor = page.page.next_cursor
    if (cursor && seenCursors.has(cursor)) throw new Error('Repeated identity document cursor')
    if (cursor) seenCursors.add(cursor)
  } while (cursor)
  return items
}

function failureMessage(error, action) {
  if (error?.status === 401) return 'Your session has expired. Sign in again, then reopen Identity & verification.'
  if (error?.status === 403) return 'This session cannot access saved identity documents. Sign in with the account that owns them, then try again.'
  if (action === 'load') return error?.code === 'NETWORK_ERROR'
    ? 'Northwind could not load saved identity documents because the connection was lost. Check your connection and try again.'
    : 'The account service could not return saved identity documents. Try again.'
  if (error?.status === 422) return 'The number needs 4–80 characters, including at least four letters or digits. Check it and try again.'
  if (error?.code === 'NETWORK_ERROR') return 'Northwind could not confirm whether this document was saved. Refresh the saved list when your connection returns, then retry if needed.'
  if (error?.status === 503) return `Northwind could not ${action} this document because protected account storage is unavailable. Try again later.`
  return `The account service could not ${action} this document. Review the number and try again.`
}

export default function IdentityDocuments({ busy = false }) {
  const [documents, setDocuments] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [editor, setEditor] = useState(null)
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState(null)
  const requestRef = useRef(null)
  const inputRef = useRef(null)
  const selectRef = useRef(null)
  const addButtonRef = useRef(null)
  const editButtonRefs = useRef(new Map())
  const returnFocusRef = useRef(null)

  const reload = useCallback(async () => {
    requestRef.current?.abort()
    const controller = new AbortController()
    requestRef.current = controller
    setLoadError('')
    setDocuments(null)
    try {
      const items = await readIdentityDocuments(controller.signal)
      if (!controller.signal.aborted) setDocuments(items)
    } catch (error) {
      if (!controller.signal.aborted) {
        setLoadError(failureMessage(error, 'load'))
      }
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    requestRef.current = controller
    readIdentityDocuments(controller.signal)
      .then((items) => { if (!controller.signal.aborted) setDocuments(items) })
      .catch((error) => { if (!controller.signal.aborted) setLoadError(failureMessage(error, 'load')) })
    return () => controller.abort()
  }, [])

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
    setDraft('')
    setEditor(null)
  }

  function beginAdd() {
    returnFocusRef.current = { mode: 'add' }
    setNotice(null)
    setDraft('')
    setEditor({ mode: 'add', documentType: 'driver_licence', idempotencyKey: requestId('identity-document') })
  }

  function beginEdit(document) {
    returnFocusRef.current = { mode: 'edit', identityId: document.identity_id }
    setNotice(null)
    setDraft('')
    setEditor({ mode: 'edit', identityId: document.identity_id })
  }

  async function save(event) {
    event.preventDefault()
    if (saving || !draft.trim()) return
    setSaving(true)
    setNotice(null)
    const number = draft.trim()
    const current = editor.mode === 'edit'
      ? documents.find((document) => document.identity_id === editor.identityId)
      : null
    if (editor.mode === 'edit' && !current) {
      closeEditor()
      setSaving(false)
      setNotice({ kind: 'error', text: 'This document is no longer in the saved list. Refresh the list, then choose a document to edit.' })
      return
    }
    try {
      const saved = current
        ? await updateAccountIdentityDocument({
          identityId: current.identity_id,
          revision: current.revision,
          documentNumber: number,
        })
        : await createAccountIdentityDocument({
          documentType: editor.documentType,
          documentNumber: number,
          idempotencyKey: editor.idempotencyKey,
        })
      setDocuments((previous) => current
        ? previous.map((document) => document.identity_id === saved.identity_id ? saved : document)
        : previous.some((document) => document.identity_id === saved.identity_id)
          ? previous.map((document) => document.identity_id === saved.identity_id ? saved : document)
          : [saved, ...previous])
      closeEditor()
      setNotice({ kind: 'success', text: `${documentLabel(saved.document_type)} saved. Only its masked number is shown.` })
    } catch (error) {
      if (current && (error?.status === 409 || error?.status === 404)) {
        closeEditor()
        setNotice({ kind: 'error', text: 'This document changed or is no longer available. The list is being refreshed; reopen the document and enter its new number.' })
        void reload()
      } else if (!current && error?.status === 409) {
        setNotice({
          kind: 'error',
          text: 'This save request conflicts with an earlier attempt. Refresh the saved list; if the document is absent, cancel and start a new entry.',
          canRefresh: true,
        })
      } else {
        setNotice({
          kind: 'error',
          text: failureMessage(error, current ? 'update' : 'save'),
          canRefresh: error?.code === 'NETWORK_ERROR',
        })
      }
    } finally {
      setSaving(false)
    }
  }

  const editingDocument = editor?.mode === 'edit'
    ? documents?.find((document) => document.identity_id === editor.identityId)
    : null

  return (
    <div className="profile-identity-documents">
      <p className="profile-helper-copy">Saved numbers are shown only in masked form. Saving a number does not verify your identity.</p>
      {notice && <p className={`profile-notice is-${notice.kind}`} role={notice.kind === 'error' ? 'alert' : 'status'}>{notice.text}</p>}
      {notice?.canRefresh && <button className="profile-quiet-action" type="button" onClick={() => { void reload() }}>Refresh saved list</button>}
      {loadError && (
        <div className="profile-assets-error" role="alert">
          <p>{loadError}</p>
          <button className="profile-quiet-action" type="button" onClick={() => { void reload() }}>Try again</button>
        </div>
      )}
      {documents === null && !loadError && <p className="profile-assets-loading" role="status">Loading saved identity documents…</p>}
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
                      disabled={busy || saving}
                      onClick={() => beginEdit(document)}
                      aria-label={`Edit ${documentLabel(document.document_type)} ${document.masked_document_number}`}
                    >Edit</button>
                  </li>
                ))}
              </ul>
            )}
          {!editor && (
            <button ref={addButtonRef} className="profile-asset-add-action" type="button" disabled={busy || saving} onClick={beginAdd}>
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
