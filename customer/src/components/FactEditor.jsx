import { useId, useState } from 'react'

import { choiceLabel } from '../recordedFacts.js'

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

export default function FactEditor({ fact, input, busy, onSave, onCancel }) {
  const inputId = useId()
  const [draft, setDraft] = useState(() => initialDraft(fact, input))
  const choices = input?.value_type === 'boolean'
    ? [['true', 'Yes'], ['false', 'No']]
    : input?.value_type === 'enum'
      ? (input.allowed_values || []).map((value) => [value, choiceLabel(value)])
      : null
  const empty = !String(draft).trim()
    || (input?.value_type === 'number' && Number.isNaN(Number(draft)))

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
          autoFocus
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
          autoFocus
        />
      )}
      <button className="primary-button" type="submit" disabled={busy || empty}>Save</button>
      <button className="text-button" type="button" onClick={onCancel}>Cancel</button>
    </form>
  )
}
