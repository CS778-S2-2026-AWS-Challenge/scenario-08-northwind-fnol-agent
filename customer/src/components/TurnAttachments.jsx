import { useId, useRef, useState } from 'react'

import { documentTaskTitle } from '../claimDocumentProjection.js'
import { receiptChip } from '../openItems.js'
import FactEditor from './FactEditor.jsx'
import { displayValue, isEditable } from '../recordedFacts.js'
import { claimantStatusCopy } from '../externalServiceCopy.js'

// The one attachment row under an assistant reply. A reply is text plus at most
// this row of small chips: what was noted (facts), what was added or passed on
// (receipts), a service waiting on the claimant, how a file was read, the policy
// clauses the reply relies on, and the next step. Chips stay folded; details
// open in place (facts) or pinned at the top of the case panel (everything else).

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

function FactList({ id, facts, fieldInputs, busy, onConfirm, onSave, onClose }) {
  const [editingCode, setEditingCode] = useState(null)
  const toCheck = facts.filter((fact) => fact.toCheck)
  return (
    <section className="turn-fact-list" id={id} aria-label="Just noted">
      <dl>
        {facts.map((fact) => (
          <div className="turn-fact-row" key={fact.fieldCode}>
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
                  <span>{displayValue(fact, fieldInputs?.[fact.fieldCode])}</span>
                  {fact.toCheck && <span className="turn-fact-state">To check</span>}
                </>
              )}
            </dd>
            {editingCode !== fact.fieldCode && isEditable(fact) && (
              <button
                className="text-button turn-fact-edit"
                type="button"
                aria-label={`Change ${fact.label}`}
                disabled={busy}
                onClick={() => setEditingCode(fact.fieldCode)}
              >
                Change
              </button>
            )}
          </div>
        ))}
      </dl>
      <div className="turn-fact-actions">
        {toCheck.length > 0 && (
          <button
            className="primary-button"
            type="button"
            disabled={busy}
            onClick={() => onConfirm(toCheck.map((fact) => fact.fieldCode))}
          >
            All correct
          </button>
        )}
        <button className="secondary-button" type="button" onClick={onClose}>Close</button>
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
  const listId = useId()
  const [factsOpen, setFactsOpen] = useState(false)
  const hasChips = facts.length > 0 || receipts.length > 0 || services.length > 0
    || fileReads.length > 0 || clauses.length > 0 || nextStep
  if (!hasChips && !scopeNote) return null

  return (
    <div className="turn-attachments">
      {scopeNote && <p className="turn-scope-note">{scopeNote}</p>}
      {hasChips && (
        <div className="turn-chips">
          {facts.map((fact) => (
            <Chip
              key={fact.fieldCode}
              className={fact.toCheck ? 'is-check' : ''}
              aria-expanded={factsOpen}
              aria-controls={listId}
              aria-label={`${fact.label}: ${displayValue(fact, fieldInputs?.[fact.fieldCode])}${fact.toCheck ? ' (to check)' : ''}`}
              title={`${fact.label}: ${displayValue(fact, fieldInputs?.[fact.fieldCode])}`}
              onClick={() => setFactsOpen((open) => !open)}
            >
              <span className="turn-chip-text">{displayValue(fact, fieldInputs?.[fact.fieldCode])}</span>
            </Chip>
          ))}
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
      {factsOpen && facts.length > 0 && (
        <FactList
          id={listId}
          facts={facts}
          fieldInputs={fieldInputs}
          busy={busy}
          onConfirm={async (codes) => {
            await onConfirmFacts?.(codes)
            setFactsOpen(false)
          }}
          onSave={onSaveFact}
          onClose={() => setFactsOpen(false)}
        />
      )}
    </div>
  )
}
