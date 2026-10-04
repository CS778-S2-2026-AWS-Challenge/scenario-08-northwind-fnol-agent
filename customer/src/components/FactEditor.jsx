import { useId, useState } from 'react'

import {
  fieldDraftValue,
  fieldInputChoices,
  fieldInputValue,
} from '../recordedFacts.js'

export default function FactEditor({ fact, input, busy, onSave, onCancel }) {
  const inputId = useId()
  const [draft, setDraft] = useState(() => fieldDraftValue(fact.field.value, input))
  const choices = fieldInputChoices(input)
  const empty = !String(draft).trim()
    || (input?.value_type === 'number' && Number.isNaN(Number(draft)))

  return (
    <form
      className="recorded-facts-editor"
      onSubmit={async (event) => {
        event.preventDefault()
        if (empty) return
        if (await onSave(fact, fieldInputValue(draft, input))) onCancel()
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
