import { ResourceError, SectionHeading, SummaryRow } from './ProfilePrimitives.jsx'

function accountTypeLabel(value = '') {
  return value
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => `${part[0].toUpperCase()}${part.slice(1)}`)
    .join(' ') || 'Bank account'
}

export default function PaymentDetailsSection({ resource, headingAs: Heading = 'h1', onReload }) {
  const destinations = resource.items
  return (
    <section className="profile-section" aria-labelledby="profile-payment-details">
      <SectionHeading
        as={Heading}
        id="profile-payment-details"
        title="Payment details"
        description="Bank account to receive claim payments"
      />
      <p className="profile-helper-copy">
        Northwind can store an account type and masked account number. Bank name, account holder, and a designated Claim payment destination are not part of the current account contract.
      </p>
      <ResourceError message={resource.error} onRetry={onReload} />
      {destinations === null && !resource.error && <p className="profile-assets-loading" role="status">Loading saved payment details…</p>}
      {destinations && (
        <>
          <dl className="profile-summary-list profile-compact-summary-list">
            <SummaryRow label="Saved accounts" value={`${destinations.length}`} />
            <SummaryRow label="Bank" value="Not supported" />
            <SummaryRow label="Account holder" value="Not supported" />
            <SummaryRow label="Claim payment destination" value="Not designated" />
          </dl>
          {destinations.length === 0
            ? <p className="profile-assets-empty">No payment details saved.</p>
            : (
              <ul className="profile-record-list" aria-label="Saved payment details">
                {destinations.map((destination) => (
                  <li key={destination.payment_destination_id} className="profile-record-row">
                    <span>
                      <strong>{accountTypeLabel(destination.account_type)}</strong>
                      <span>{destination.masked_account_number}</span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          <p className="profile-helper-copy">Adding or changing payment details remains unavailable in this Profile delivery.</p>
        </>
      )}
    </section>
  )
}
