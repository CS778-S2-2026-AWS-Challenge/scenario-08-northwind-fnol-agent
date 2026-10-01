import { useId, useState } from 'react'

import { choiceLabel, progressLabel } from '../recordedFacts.js'

function displayValue(fact, input) {
  if (input?.value_type === 'enum' && typeof fact.field.value === 'string') {
    return choiceLabel(fact.field.value)
  }
  return fact.value
}

function initialDraft(fact, input) {
  const { value } = fact.field
  if (input?.value_type === 'boolean') return value === true ? 'true' : value === false ? 'false' : ''
  if (input?.value_type === 'enum') return typeof value === 'string' ? value : ''
  return fact.value
}

// The value as the registry stores it: Yes/No as a boolean, a list as an array.
function typedValue(draft, input) {
  if (input?.value_type === 'boolean') return draft === 'true'
  if (input?.value_type === 'number') return Number(draft)
  if (input?.value_type === 'text_list') {
    return draft.split(',').map((item) => item.trim()).filter(Boolean)
  }
  return draft.trim()
}

function FactEditor({ fact, input, busy, onSave, onCancel }) {
  const inputId = useId()
  const [draft, setDraft] = useState(() => initialDraft(fact, input))
  const choices = input?.value_type === 'boolean'
    ? [['true', 'Yes'], ['false', 'No']]
    : input?.value_type === 'enum'
      ? (input.allowed_values || []).map((value) => [value, choiceLabel(value)])
      : null
  const empty = !String(draft).trim()

  return (
    <form
      className="recorded-facts-editor"
      onSubmit={async (event) => {
        event.preventDefault()
        if (empty) return
        if (await onSave(fact, typedValue(draft, input))) onCancel()
      }}
    >
      <label className="sr-only" htmlFor={inputId}>{fact.label}</label>
      {choices ? (
        <select
          id={inputId}
          className="input-field"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          disabled={busy}
        >
          {!draft && <option value="">Choose…</option>}
          {choices.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      ) : (
        <input
          id={inputId}
          className="input-field"
          type={input?.value_type === 'number' ? 'number' : 'text'}
          min={input?.value_type === 'number' ? 0 : undefined}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          disabled={busy}
        />
      )}
      <button className="primary-button" type="submit" disabled={busy || empty}>Save</button>
      <button className="text-button" type="button" onClick={onCancel}>Cancel</button>
    </form>
  )
}

// "Just noted": the facts recorded from the claimant's message, shown under the
// assistant reply so they can be checked where the claimant is reading.
// Earlier cards fold into one line once a newer card arrives.
export default function RecordedFactsCard({
  facts,
  fieldInputs = {},
  progress,
  latest,
  busy,
  onConfirm,
  onSave,
}) {
  const [expandedChoice, setExpandedChoice] = useState(null)
  const [editing, setEditing] = useState(false)
  const [editingCode, setEditingCode] = useState(null)
  const expanded = expandedChoice ?? latest
  const toCheck = facts.filter((fact) => fact.toCheck)

  if (!expanded) {
    return (
      <button
        className="recorded-facts-collapsed"
        type="button"
        aria-expanded="false"
        onClick={() => setExpandedChoice(true)}
      >
        {toCheck.length > 0
          ? `Just noted · ${toCheck.length} to check`
          : `Just noted · ${facts.length} checked`}
      </button>
    )
  }

  return (
    <section className="recorded-facts" aria-label="Just noted">
      <header className="recorded-facts-header">
        <h3>Just noted</h3>
        {latest && progress && <span className="recorded-facts-progress">{progressLabel(progress)}</span>}
      </header>
      <dl className="recorded-facts-list">
        {facts.map((fact) => (
          <div className="recorded-facts-row" key={fact.fieldCode}>
            <dt>{fact.label}</dt>
            <dd>
              {editingCode === fact.fieldCode ? (
                <FactEditor
                  fact={fact}
                  input={fieldInputs[fact.fieldCode]}
                  busy={busy}
                  onSave={onSave}
                  onCancel={() => setEditingCode(null)}
                />
              ) : (
                <>
                  <span className="recorded-facts-value">{displayValue(fact, fieldInputs[fact.fieldCode])}</span>
                  {fact.toCheck
                    ? <span className="recorded-facts-state">To check</span>
                    : <span className="recorded-facts-state is-checked">Checked</span>}
                  {editing && (
                    <button
                      className="text-button recorded-facts-edit"
                      type="button"
                      aria-label={`Change ${fact.label}`}
                      disabled={busy}
                      onClick={() => setEditingCode(fact.fieldCode)}
                    >
                      Change
                    </button>
                  )}
                </>
              )}
            </dd>
          </div>
        ))}
      </dl>
      <div className="recorded-facts-actions">
        {toCheck.length > 0 && (
          <button
            className="primary-button"
            type="button"
            disabled={busy}
            onClick={() => onConfirm(toCheck.map((fact) => fact.fieldCode))}
          >
            Looks right
          </button>
        )}
        <button
          className="secondary-button"
          type="button"
          aria-pressed={editing}
          disabled={busy}
          onClick={() => {
            setEditing((current) => !current)
            setEditingCode(null)
          }}
        >
          {editing ? 'Done' : 'Edit'}
        </button>
      </div>
    </section>
  )
}
