// The title-bar status (see caseStatus.js). A sync problem adds a short hint beside it.

export default function CaseStatus({ status, missingLabels = [], syncNotice = null, panelOpen, onTogglePanel }) {
  if (!status) return null
  const tip = status.detail || (missingLabels.length > 0 ? `Still needed: ${missingLabels.join(', ')}` : null)
  return (
    <span className="case-status-wrap">
      {syncNotice && <span className="case-status-sync" role="status" aria-label={syncNotice}>{syncNotice}</span>}
      <button
        className={`case-status is-${status.tone}`}
        type="button"
        aria-expanded={panelOpen}
        aria-controls="claim-details-body"
        aria-describedby={tip ? 'case-status-tip' : undefined}
        onClick={onTogglePanel}
      >
        <span className="case-status-dot" aria-hidden="true" />
        <span>{status.text}</span>
      </button>
      {tip && <span className="case-status-tip" id="case-status-tip" role="tooltip">{tip}</span>}
    </span>
  )
}
