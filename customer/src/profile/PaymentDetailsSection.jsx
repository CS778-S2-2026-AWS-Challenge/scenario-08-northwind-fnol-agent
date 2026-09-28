import { useEffect, useRef, useState } from 'react'

import { profileMutationMessage } from './profileMutation.js'
import { FeatureNotice, ResourceError, SectionHeading, SummaryRow } from './ProfilePrimitives.jsx'

function accountTypeLabel(value = '') {
  return value
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => `${part[0].toUpperCase()}${part.slice(1)}`)
    .join(' ') || 'Bank account'
}

function destinationLabel(destination) {
  return `${accountTypeLabel(destination.account_type)} ${destination.masked_account_number}`
}

function draftFor(destination = null) {
  return {
    bankName: destination?.bank_name || '',
    accountHolderName: destination?.account_holder_name || '',
    accountType: destination?.account_type || '',
    accountNumber: '',
  }
}

export default function PaymentDetailsSection({
  resource,
  pending,
  headingAs: Heading = 'h1',
  onBeginCreate,
  onAbandonCreate,
  onCreate,
  onReload,
  onUpdate,
}) {
  const destinations = resource.items
  const authoritative = destinations !== null && !resource.error && !resource.loading && !resource.stale
  const commonDestination = destinations?.find((destination) => destination.is_common) || null
  const [editor, setEditor] = useState(null)
  const [draft, setDraft] = useState(() => draftFor())
  const [notice, setNotice] = useState(null)
  const firstInputRef = useRef(null)
  const returnFocusRef = useRef(null)
  const saving = editor?.mode === 'create'
    ? Boolean(pending['payment-create'])
    : Boolean(pending[`payment:${editor?.paymentDestinationId}`])
  const editingDestination = editor?.mode === 'edit'
    ? destinations?.find((destination) => (
      destination.payment_destination_id === editor.paymentDestinationId
    )) || null
    : null

  useEffect(() => { if (editor && authoritative) firstInputRef.current?.focus() }, [authoritative, editor])

  useEffect(() => {
    if (editor || !returnFocusRef.current) return
    const targetId = returnFocusRef.current
    returnFocusRef.current = null
    globalThis.document?.getElementById(targetId)?.focus()
  }, [editor])

  function closeEditor() {
    if (editor?.mode === 'create') onAbandonCreate('payment', editor.attemptId)
    setEditor(null)
    setDraft(draftFor())
  }

  function beginCreate(event) {
    closeEditor()
    setNotice(null)
    returnFocusRef.current = event.currentTarget.id
    setEditor({ mode: 'create', attemptId: onBeginCreate('payment') })
    setDraft(draftFor())
  }

  function beginEdit(event) {
    setNotice(null)
    returnFocusRef.current = event.currentTarget.id
    setEditor({ mode: 'edit', paymentDestinationId: commonDestination.payment_destination_id })
    setDraft(draftFor(commonDestination))
  }

  function change(field, value) {
    setDraft((current) => ({ ...current, [field]: value }))
  }

  async function save(event) {
    event.preventDefault()
    if (editor.mode === 'edit' && !editingDestination) {
      setNotice({
        kind: 'error',
        text: 'This payment destination is no longer available. Cancel this draft and review the latest saved details.',
      })
      return
    }
    const values = {
      bankName: draft.bankName.trim(),
      accountHolderName: draft.accountHolderName.trim(),
      accountType: draft.accountType.trim(),
    }
    try {
      const saved = editor.mode === 'create'
        ? await onCreate({
          ...values,
          accountNumber: draft.accountNumber.trim(),
          attemptId: editor.attemptId,
        })
        : await onUpdate(
          editingDestination.payment_destination_id,
          editingDestination.revision,
          {
            ...values,
            ...(draft.accountNumber.trim() ? { accountNumber: draft.accountNumber.trim() } : {}),
            isCommon: true,
          },
        )
      setNotice({
        kind: 'success',
        text: saved.is_common
          ? `${destinationLabel(saved)} is saved as your Claim payment destination.`
          : `${destinationLabel(saved)} was saved. Choose it below before Northwind can use it for Claim payments.`,
      })
      setEditor(null)
      setDraft(draftFor())
    } catch (error) {
      setNotice({
        kind: 'error',
        text: profileMutationMessage(error, 'Northwind could not save these payment details.'),
      })
    }
  }

  async function designate(destination) {
    setNotice(null)
    try {
      const saved = await onUpdate(
        destination.payment_destination_id,
        destination.revision,
        { isCommon: true },
      )
      setNotice({
        kind: 'success',
        text: `${destinationLabel(saved)} is now your Claim payment destination.`,
      })
    } catch (error) {
      setNotice({
        kind: 'error',
        text: profileMutationMessage(error, 'Northwind could not designate this payment destination.'),
      })
    }
  }

  const formReady = draft.bankName.trim()
    && draft.accountHolderName.trim()
    && draft.accountType.trim()
    && (editor?.mode === 'edit' || draft.accountNumber.trim())

  return (
    <section className="profile-section" aria-labelledby="profile-payment-details">
      <FeatureNotice notice={notice} />
      <SectionHeading
        as={Heading}
        id="profile-payment-details"
        title="Payment details"
        description="Manage the bank account Northwind may use for an eligible Claim payment."
      />
      <ResourceError
        message={resource.error}
        onRetry={onReload}
        retainedLabel={resource.stale ? 'saved payment details' : ''}
      />
      {destinations === null && !resource.error && (
        <p className="profile-assets-loading" role="status">Loading saved payment details…</p>
      )}
      {commonDestination && (
        <>
          <dl className="profile-summary-list">
            <SummaryRow label="Bank" value={commonDestination.bank_name || 'Not provided'} />
            <SummaryRow label="Account holder" value={commonDestination.account_holder_name || 'Not provided'} />
            <SummaryRow label="Claim payment destination" value={destinationLabel(commonDestination)} />
          </dl>
          {authoritative && !editor && (
            <button
              id="profile-payment-edit-button"
              className="profile-quiet-action"
              type="button"
              onClick={beginEdit}
            >
              Edit payment details
            </button>
          )}
        </>
      )}
      {authoritative && destinations.length === 0 && !editor && (
        <>
          <p className="profile-assets-empty">No Claim payment destination saved.</p>
          <button
            id="profile-payment-add-button"
            className="profile-asset-add-action"
            type="button"
            onClick={beginCreate}
          >
            <span aria-hidden="true">+</span> Add payment details
          </button>
        </>
      )}
      {authoritative && destinations.length > 0 && !commonDestination && (
        <div className="profile-availability-note">
          <strong>Choose a Claim payment destination</strong>
          <p>Your account has saved payment details, but none is designated for Claim payments.</p>
          <ul className="profile-record-list" aria-label="Payment destinations requiring designation">
            {destinations.map((destination) => (
              <li key={destination.payment_destination_id} className="profile-record-row">
                <span>
                  <strong>{destination.bank_name || accountTypeLabel(destination.account_type)}</strong>
                  <span>{destinationLabel(destination)}</span>
                </span>
                <button
                  className="profile-quiet-action"
                  type="button"
                  disabled={Boolean(pending[`payment:${destination.payment_destination_id}`])}
                  onClick={() => designate(destination)}
                >
                  Use for Claims
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {editor && (
        <form className="profile-edit-form profile-record-form" onSubmit={save}>
          <h3>{editor.mode === 'create' ? 'Add payment details' : 'Edit payment details'}</h3>
          <label htmlFor="profile-payment-bank">Bank</label>
          <input
            ref={firstInputRef}
            id="profile-payment-bank"
            value={draft.bankName}
            maxLength="200"
            autoComplete="organization"
            required
            disabled={saving}
            onChange={(event) => change('bankName', event.target.value)}
          />
          <label htmlFor="profile-payment-account-holder">Account holder</label>
          <input
            id="profile-payment-account-holder"
            value={draft.accountHolderName}
            maxLength="200"
            autoComplete="name"
            required
            disabled={saving}
            onChange={(event) => change('accountHolderName', event.target.value)}
          />
          <label htmlFor="profile-payment-account-type">Account type</label>
          <input
            id="profile-payment-account-type"
            value={draft.accountType}
            maxLength="200"
            autoComplete="off"
            required
            disabled={saving}
            onChange={(event) => change('accountType', event.target.value)}
          />
          <label htmlFor="profile-payment-account-number">
            Bank account number {editor.mode === 'edit' && <span>(leave blank to keep the saved number)</span>}
          </label>
          <input
            id="profile-payment-account-number"
            value={draft.accountNumber}
            minLength="4"
            maxLength="80"
            autoComplete="off"
            inputMode="numeric"
            required={editor.mode === 'create'}
            disabled={saving}
            onChange={(event) => change('accountNumber', event.target.value)}
          />
          <p className="profile-helper-copy">
            The complete account number is sent only to the protected account-data service and is never shown again.
          </p>
          <div className="profile-asset-form-actions">
            <button className="primary-button" type="submit" disabled={!authoritative || saving || !formReady}>
              {saving ? 'Saving…' : 'Save payment details'}
            </button>
            <button className="profile-quiet-action" type="button" disabled={saving} onClick={closeEditor}>Cancel</button>
          </div>
        </form>
      )}
    </section>
  )
}
