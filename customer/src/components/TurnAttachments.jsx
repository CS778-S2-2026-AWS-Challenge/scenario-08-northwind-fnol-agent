import { useId, useRef, useState } from 'react'

import { documentTaskTitle } from '../claimDocumentProjection.js'
import { receiptChip } from '../openItems.js'
import FactEditor from './FactEditor.jsx'
import { displayValue, isEditable } from '../recordedFacts.js'
import { claimantStatusCopy } from '../externalServiceCopy.js'

// The attachments under an assistant reply. Recorded facts use a compact
// disclosure so their meaning and correction action are available on demand.
// Receipts, services, file reads, policy clauses, and the next step remain chips.

function Chip({ className = '', children, ...props }) {
  const Element = props.onClick ? 'button' : 'span'
  return (
    <Element
      className={`turn-chip ${props.onClick ? 'is-button' : ''} ${className}`.trim()}
      type={props.onClick ? 'button' : undefined}
      {...props}
    >
      {children}
    </Element>
  )
}

function ChipUpload({ item, onUpload, busy }) {
  const input = useRef(null)
  if (!onUpload) return null
  return (
    <>
      <input
        ref={input}
        className="sr-only"
        type="file"
        accept="image/jpeg,image/png,application/pdf"
        tabIndex={-1}
        aria-hidden="true"
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) onUpload(item, file)
          event.target.value = ''
        }}
      />
      <button
        className="turn-chip-action"
        type="button"
        disabled={busy}
        onClick={() => input.current?.click()}
      >
        Upload
      </button>
    </>
  )
}

function RecordedIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="m5 12 4 4L19 6" />
    </svg>
  )
}

function DisclosureIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="m8 10 4 4 4-4" />
    </svg>
  )
}

function EditIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="m14 6 4 4M4 20l1-5L16 4l4 4L9 19l-5 1Z" />
    </svg>
  )
}

function CapturedInformationCard({ facts, fieldInputs, busy, onConfirm, onSave }) {
  const titleId = useId()
  const detailsId = useId()
  const [expanded, setExpanded] = useState(false)
  const [editingCode, setEditingCode] = useState(null)
  const toCheck = facts.filter((fact) => fact.toCheck)
  const detailLabel = `${facts.length} ${facts.length === 1 ? 'detail' : 'details'}`
  return (
    <section className="captured-information-card" aria-labelledby={titleId}>
      <h3 className="sr-only" id={titleId}>Captured information</h3>
      <div className="captured-information-summary">
        <p className="captured-information-status">
          <RecordedIcon />
          <span>{`Noted ${detailLabel}`}</span>
        </p>
        <div className="captured-information-actions">
          <button
            className="captured-information-disclosure"
            type="button"
            aria-expanded={expanded}
            aria-controls={detailsId}
            onClick={() => setExpanded((current) => !current)}
          >
            <span>{expanded ? 'Hide' : 'Review'}</span>
            <DisclosureIcon />
          </button>
          {toCheck.length > 0 && (
            <button
              className="captured-information-confirm"
              type="button"
              disabled={busy}
              onClick={() => onConfirm?.(toCheck.map((fact) => fact.fieldCode))}
            >
              Looks right
            </button>
          )}
        </div>
      </div>
      <div className="captured-information-details" id={detailsId} hidden={!expanded}>
        <dl className="captured-information-list">
          {facts.map((fact) => (
            <div className="captured-information-row" key={fact.fieldCode}>
              <dt>{fact.label}</dt>
              <dd>
                {editingCode === fact.fieldCode ? (
                  <FactEditor
                    fact={fact}
                    input={fieldInputs?.[fact.fieldCode]}
                    busy={busy}
                    onSave={onSave}
                    onCancel={() => setEditingCode(null)}
                  />
                ) : (
                  <>
                    <span className="captured-information-value">
                      {displayValue(fact, fieldInputs?.[fact.fieldCode])}
                    </span>
                    {isEditable(fact) && (
                      <button
                        className="captured-information-edit"
                        type="button"
                        aria-label={`Edit ${fact.label} in captured information`}
                        disabled={busy}
                        onClick={() => setEditingCode(fact.fieldCode)}
                      >
                        <EditIcon />
                        Edit
                      </button>
                    )}
                  </>
                )}
              </dd>
            </div>
          ))}
        </dl>
        <p className="captured-information-help">
          {facts.length === 1
            ? 'Review this detail. You can correct it at any time.'
            : 'Review these details. You can correct them at any time.'}
        </p>
      </div>
    </section>
  )
}

function serviceChipText(action) {
  const state = claimantStatusCopy(action)
  return `${action.service_name} · ${state.label}`
}

export default function TurnAttachments({
  facts = [],
  fieldInputs,
  receipts = [],
  scopeNote = null,
  services = [],
  fileReads = [],
  clauses = [],
  nextStep = null,
  busy = false,
  onConfirmFacts,
  onSaveFact,
  onUpload,
  onOpenReceipt,
  onPin,
}) {
  const hasChips = receipts.length > 0 || services.length > 0
    || fileReads.length > 0 || clauses.length > 0 || nextStep
  if (facts.length === 0 && !hasChips && !scopeNote) return null

  return (
    <div className="turn-attachments">
      {scopeNote && <p className="turn-scope-note">{scopeNote}</p>}
      {facts.length > 0 && (
        <CapturedInformationCard
          facts={facts}
          fieldInputs={fieldInputs}
          busy={busy}
          onConfirm={onConfirmFacts}
          onSave={onSaveFact}
        />
      )}
      {hasChips && (
        <div className="turn-chips">
          {receipts.map((item) => {
            const chip = receiptChip(item)
            return (
              <Chip
                key={item.item_id}
                className={chip.owed ? 'is-owed' : chip.settled ? 'is-done' : ''}
                title={chip.text}
                onClick={chip.owed ? undefined : () => onOpenReceipt?.(item)}
              >
                <span aria-hidden="true">{chip.mark}</span>
                <span className="turn-chip-text">{chip.text}</span>
                {chip.owed && <ChipUpload item={item} onUpload={onUpload} busy={busy} />}
              </Chip>
            )
          })}
          {services.map((action) => (
            <Chip
              key={action.offer_id || action.service_identity}
              className={claimantStatusCopy(action).attention || action.status === 'consent_required' ? 'is-owed' : ''}
              onClick={() => onPin?.({ kind: 'service', id: action.offer_id || action.service_identity })}
            >
              <span className="turn-chip-text">{serviceChipText(action)}</span>
              <span aria-hidden="true">›</span>
            </Chip>
          ))}
          {fileReads.map((read) => (
            <Chip
              key={read.evidence_id}
              onClick={() => onPin?.({ kind: 'file', id: read.evidence_id })}
            >
              <span className="turn-chip-text">{`File · read as ${documentTaskTitle({ kind: read.kind })}`}</span>
              <span aria-hidden="true">›</span>
            </Chip>
          ))}
          {clauses.map((clause) => (
            <Chip
              key={clause.chunk_id}
              onClick={() => onPin?.({ kind: 'clause', id: clause.chunk_id })}
            >
              <span className="turn-chip-text">{`Policy · ${clause.section_path || clause.title}`}</span>
              <span aria-hidden="true">›</span>
            </Chip>
          ))}
          {nextStep && (
            <Chip className="is-owed" onClick={() => onPin?.({ kind: nextStep.pin })}>
              <span className="turn-chip-text">{nextStep.label}</span>
              <span aria-hidden="true">›</span>
            </Chip>
          )}
        </div>
      )}
    </div>
  )
}
