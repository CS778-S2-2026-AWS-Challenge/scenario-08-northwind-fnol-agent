import { useEffect, useMemo, useState } from 'react'
import './PayoutContactPanel.css'

const CONTACT_METHODS = [
  { value: 'in_app', label: 'In-app', destination: () => 'Northwind account messages' },
  { value: 'email', label: 'Email', destination: (profile) => profile?.email || '' },
  { value: 'sms', label: 'SMS / text message', destination: (profile) => profile?.phone || '' },
  { value: 'phone', label: 'Phone call', destination: (profile) => profile?.phone || '' },
]

function hasMeaningfulAccountNumber(value) {
  return [...String(value || '')].filter((character) => /[A-Za-z0-9]/.test(character)).length >= 4
}

export default function PayoutContactPanel({
  account,
  claim,
  destinations,
  loading,
  loadError,
  busy,
  onAddDestination,
  onContinue,
  onManageContact,
  onLogin,
}) {
  const profile = account?.profile
  const activeDestinations = useMemo(
    () => (destinations || []).filter((item) => item.active !== false),
    [destinations],
  )
  const existingContact = claim?.form?.['claimant.contact_preference']?.value || ''
  const [selectedDestinationId, setSelectedDestinationId] = useState(
    claim?.payment_destination_id || '',
  )
  const [contactPreference, setContactPreference] = useState(existingContact)
  const [addingDestination, setAddingDestination] = useState(false)
  const [accountType, setAccountType] = useState('')
  const [accountNumber, setAccountNumber] = useState('')
  const [formError, setFormError] = useState('')

  useEffect(() => {
    const activeIds = new Set(activeDestinations.map((item) => item.payment_destination_id))
    setSelectedDestinationId((current) => {
      if (activeIds.has(current)) return current
      if (activeIds.has(claim?.payment_destination_id)) return claim.payment_destination_id
      return ''
    })
    if (!loading && activeDestinations.length === 0) setAddingDestination(true)
  }, [activeDestinations, claim?.payment_destination_id, loading])

  useEffect(() => {
    if (existingContact) setContactPreference(existingContact)
  }, [existingContact])

  const contactMethods = CONTACT_METHODS.map((method) => {
    const destination = method.destination(profile)
    return {
      ...method,
      destination,
      available: method.value === 'in_app' || Boolean(destination),
    }
  })
  const selectedContact = contactMethods.find((method) => method.value === contactPreference)
  const canContinue = Boolean(
    selectedDestinationId
    && contactPreference
    && selectedContact?.available
    && !busy
    && !loading,
  )

  async function saveDestination(event) {
    event.preventDefault()
    setFormError('')
    const normalizedType = accountType.trim()
    const normalizedNumber = accountNumber.trim()
    if (!normalizedType) {
      setFormError('Enter the account type.')
      return
    }
    if (!hasMeaningfulAccountNumber(normalizedNumber)) {
      setFormError('Enter a valid bank account number.')
      return
    }
    try {
      const created = await onAddDestination({
        accountType: normalizedType,
        accountNumber: normalizedNumber,
      })
      setSelectedDestinationId(created.payment_destination_id)
      setAccountType('')
      setAccountNumber('')
      setAddingDestination(false)
    } catch (requestError) {
      setFormError(requestError.message || 'The payout account could not be saved.')
    }
  }

  async function continueToAgreement(event) {
    event.preventDefault()
    setFormError('')
    if (!selectedDestinationId) {
      setFormError('Select or add a payout account before continuing.')
      return
    }
    if (!contactPreference) {
      setFormError('Select how Northwind should contact you about this Claim.')
      return
    }
    if (!selectedContact?.available) {
      setFormError('The selected contact method does not have a usable destination.')
      return
    }
    try {
      await onContinue({
        paymentDestinationId: selectedDestinationId,
        contactPreference,
      })
    } catch (requestError) {
      setFormError(requestError.message || 'Payout and contact details could not be saved.')
    }
  }

  if (!account) {
    return (
      <section className="payout-contact-panel" aria-labelledby="payout-contact-title">
        <div className="payout-contact-heading">
          <span className="payout-contact-step">Step 3</span>
          <h2 id="payout-contact-title">Payout & contact</h2>
          <p>Log in before saving payout details so protected account information stays tied to your Northwind account.</p>
        </div>
        <button className="primary-button" type="button" onClick={onLogin}>Log in to continue</button>
      </section>
    )
  }

  return (
    <section className="payout-contact-panel" aria-labelledby="payout-contact-title">
      <div className="payout-contact-heading">
        <span className="payout-contact-step">Step 3</span>
        <h2 id="payout-contact-title">Payout & contact</h2>
        <p>
          Choose where Northwind should send any eligible Claim payment and how you prefer to be contacted.
          Saving a payout destination does not execute a payment.
        </p>
      </div>

      <div className="payout-contact-section" aria-labelledby="payout-account-title">
        <div className="payout-contact-section-heading">
          <div>
            <h3 id="payout-account-title">Payout account</h3>
            <p>Saved account numbers are masked after they are stored.</p>
          </div>
          {activeDestinations.length > 0 && (
            <button
              className="secondary-button"
              type="button"
              onClick={() => setAddingDestination((current) => !current)}
              disabled={busy}
            >
              {addingDestination ? 'Cancel new account' : 'Add another account'}
            </button>
          )}
        </div>

        {loading && <p className="payout-contact-status" role="status">Loading saved payout accounts…</p>}
        {loadError && <p className="backend-status is-error" role="alert">{loadError}</p>}

        {!loading && activeDestinations.length > 0 && (
          <fieldset className="payout-destination-list">
            <legend>Select a saved payout account</legend>
            {activeDestinations.map((destination) => (
              <label className="payout-option" key={destination.payment_destination_id}>
                <input
                  type="radio"
                  name="payout_destination"
                  value={destination.payment_destination_id}
                  checked={selectedDestinationId === destination.payment_destination_id}
                  onChange={() => setSelectedDestinationId(destination.payment_destination_id)}
                  disabled={busy}
                />
                <span>
                  <strong>{destination.account_type}</strong>
                  <small>{destination.masked_account_number}</small>
                </span>
              </label>
            ))}
          </fieldset>
        )}

        {addingDestination && (
          <form className="payout-new-account" onSubmit={saveDestination}>
            <label htmlFor="payout-account-type">Account type</label>
            <input
              id="payout-account-type"
              value={accountType}
              onChange={(event) => setAccountType(event.target.value)}
              autoComplete="off"
              disabled={busy}
              required
            />
            <label htmlFor="payout-account-number">Bank account number</label>
            <input
              id="payout-account-number"
              value={accountNumber}
              onChange={(event) => setAccountNumber(event.target.value)}
              autoComplete="off"
              inputMode="numeric"
              disabled={busy}
              required
            />
            <p className="payout-sensitive-note">
              The complete account number is sent only to the protected account-data service and is masked on later reads.
            </p>
            <button className="secondary-button" type="submit" disabled={busy}>
              {busy ? 'Saving…' : 'Save payout account'}
            </button>
          </form>
        )}
      </div>

      <form className="payout-contact-section" onSubmit={continueToAgreement}>
        <div className="payout-contact-section-heading">
          <div>
            <h3>Preferred contact method</h3>
            <p>Northwind will use the contact details already saved in your profile.</p>
          </div>
          <button className="secondary-button" type="button" onClick={onManageContact} disabled={busy}>
            Update contact details
          </button>
        </div>
        <fieldset className="contact-method-list">
          <legend>Choose one preferred contact method</legend>
          {contactMethods.map((method) => (
            <label
              className={`payout-option ${method.available ? '' : 'is-unavailable'}`}
              key={method.value}
            >
              <input
                type="radio"
                name="contact_preference"
                value={method.value}
                checked={contactPreference === method.value}
                onChange={() => setContactPreference(method.value)}
                disabled={!method.available || busy}
              />
              <span>
                <strong>{method.label}</strong>
                <small>{method.available ? method.destination : 'Add this contact detail in your profile first.'}</small>
              </span>
            </label>
          ))}
        </fieldset>
        {formError && <p className="backend-status is-error" role="alert">{formError}</p>}
        <button className="primary-button" type="submit" disabled={!canContinue}>
          {busy ? 'Saving…' : 'Continue to agreement'}
        </button>
      </form>
    </section>
  )
}
