import AttachmentPreview from './AttachmentPreview.jsx'
import { documentTaskTitle } from '../claimDocumentProjection.js'

// The pinned slot at the top of the case panel. One item at a time, opened by an
// event or a chip: review and submit, a service, a file, a policy clause, saved
// details, or the third-party services list. A newer item replaces it.

const SUBMIT_STEPS = [
  { kind: 'review-details', label: 'Check' },
  { kind: 'payout-contact', label: 'Payout & contact' },
  { kind: 'review-agreement', label: 'Agree' },
  { kind: 'create-claim', label: 'Submit' },
]

export function PinnedCard({ kicker, title, onClose, children }) {
  return (
    <section className="pinned-card" aria-label={title}>
      <header className="pinned-card-head">
        <div>
          {kicker && <p className="pinned-card-kicker">{kicker}</p>}
          <h3>{title}</h3>
        </div>
        <button className="pinned-card-close" type="button" aria-label={`Close ${title}`} onClick={onClose}>
          <span aria-hidden="true">×</span>
        </button>
      </header>
      {children}
    </section>
  )
}

export function SubmitSteps({ current }) {
  const index = SUBMIT_STEPS.findIndex((step) => step.kind === current)
  return (
    <ol className="pinned-steps" aria-label="Review and submit">
      {SUBMIT_STEPS.map((step, position) => (
        <li
          key={step.kind}
          className={position < index ? 'is-done' : position === index ? 'is-current' : ''}
          aria-current={position === index ? 'step' : undefined}
        >
          <span>{step.label}</span>
        </li>
      ))}
    </ol>
  )
}

export function PinnedFile({ evidence, previewFile, reading }) {
  const name = evidence?.original_filename || 'Attached file'
  return (
    <div className="pinned-file">
      <AttachmentPreview
        attachment={{ id: evidence?.evidence_id, name, previewFile }}
        fallbackClassName="pinned-file-icon"
        className="pinned-file-preview"
      />
      <p className="pinned-file-name">{name}</p>
      <p className="pinned-file-reading">
        {reading ? `The assistant read this as: ${documentTaskTitle({ kind: reading })}` : 'The assistant is still looking at this file.'}
      </p>
    </div>
  )
}

export function PinnedClause({ clause }) {
  return (
    <div className="pinned-clause">
      <p className="pinned-clause-source">
        {[clause.title, clause.version && `version ${clause.version}`].filter(Boolean).join(' · ')}
      </p>
      <blockquote className="pinned-clause-text">{clause.text}</blockquote>
    </div>
  )
}
