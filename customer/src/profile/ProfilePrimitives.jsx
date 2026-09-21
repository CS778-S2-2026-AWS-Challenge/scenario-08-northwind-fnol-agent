export function SummaryRow({ label, value }) {
  return <div className="profile-summary-row"><dt>{label}</dt><dd>{value}</dd></div>
}

export function SectionHeading({ as: Heading = 'h2', id, title, description }) {
  return (
    <header className="profile-section-heading">
      <div><Heading id={id}>{title}</Heading>{description && <p>{description}</p>}</div>
    </header>
  )
}

export function FeatureNotice({ notice }) {
  if (!notice) return null
  return (
    <p
      className={`profile-notice is-${notice.kind}`}
      role={notice.kind === 'error' ? 'alert' : 'status'}
      aria-live="polite"
    >
      {notice.text}
    </p>
  )
}

export function ResourceError({ message, onRetry }) {
  if (!message) return null
  return (
    <div className="profile-assets-error" role="alert">
      <p>{message}</p>
      <button className="profile-quiet-action" type="button" onClick={() => { void onRetry() }}>
        Try again
      </button>
    </div>
  )
}
