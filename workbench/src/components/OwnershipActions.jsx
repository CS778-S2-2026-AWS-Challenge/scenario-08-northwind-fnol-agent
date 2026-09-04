import { UsersRound } from 'lucide-react'
import { useState } from 'react'

export default function OwnershipActions({ actions = [], requests = [], onAction }) {
  const ownershipActions = actions.filter((action) => action.action_code.startsWith('ownership.'))
  if (!ownershipActions.length) return null

  return (
    <section className="ownership-actions" aria-labelledby="ownership-actions-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Access and ownership</p>
          <h2 id="ownership-actions-title">Work with this Claim</h2>
        </div>
      </div>
      <div className="ownership-action-list">
        {ownershipActions.map((action) => (
          <ProjectedOwnershipAction
            key={`${action.action_code}:${action.target_ref}`}
            action={action}
            request={requests.find((item) => item.request_id === action.target_ref)}
            onAction={onAction}
          />
        ))}
      </div>
    </section>
  )
}

function ProjectedOwnershipAction({ action, request, onAction }) {
  const [expanded, setExpanded] = useState(false)
  const [values, setValues] = useState(() => initialValues(action.inputs))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const blocked = action.availability === 'blocked'
  const formId = `ownership-form-${action.action_code.replaceAll('.', '-')}-${action.target_ref}`
  const missingRequiredInput = action.inputs.some((input) => (
    isRequired(input, values) && !String(values[input.field_code] || '').trim()
  ))

  async function submit(event) {
    event.preventDefault()
    if (blocked || missingRequiredInput) return
    setBusy(true)
    setError('')
    try {
      const payload = Object.fromEntries(
        action.inputs.map((input) => [input.field_code, String(values[input.field_code] || '').trim()]),
      )
      await onAction(action, payload)
      setExpanded(false)
      setValues(initialValues(action.inputs))
    } catch (nextError) {
      setError(nextError.message)
    } finally {
      setBusy(false)
    }
  }

  if (blocked) {
    return (
      <article className="ownership-decision" aria-disabled="true">
        <UsersRound size={18} />
        <div>
          <strong>{action.label}</strong>
          <p>{action.purpose}</p>
          <small>Unavailable: {action.blocked_reason || 'This action is not available for the current Claim state.'}</small>
        </div>
      </article>
    )
  }

  return (
    <article className="ownership-action">
      <button
        type="button"
        className="ownership-action__toggle"
        aria-expanded={expanded}
        aria-controls={formId}
        onClick={() => setExpanded((value) => !value)}
      >
        <UsersRound size={18} />
        <span><strong>{action.label}</strong><small>{action.purpose}</small></span>
      </button>
      {expanded && (
        <form id={formId} className="ownership-action__form" onSubmit={submit}>
          {request?.reason && <p>Request reason: {request.reason}</p>}
          {action.inputs.map((input) => (
            <ProjectedInput
              key={input.field_code}
              input={input}
              value={values[input.field_code] || ''}
              required={isRequired(input, values)}
              onChange={(value) => setValues((current) => ({
                ...current,
                [input.field_code]: value,
              }))}
            />
          ))}
          {action.confirmation?.message && <p>{action.confirmation.message}</p>}
          {error && <p className="form-error" role="alert">{error}</p>}
          <div className="ownership-action__controls">
            <button type="button" className="button button--quiet" onClick={() => setExpanded(false)}>Cancel</button>
            <button type="submit" className="button button--primary" disabled={busy || missingRequiredInput}>{busy ? 'Working...' : action.label}</button>
          </div>
        </form>
      )}
    </article>
  )
}

function ProjectedInput({ input, value, required, onChange }) {
  if (input.control === 'select') {
    return (
      <label>
        {input.label}
        <select value={value} required={required} onChange={(event) => onChange(event.target.value)}>
          {input.choices.map((choice) => <option value={choice.value} key={choice.value}>{choice.label}</option>)}
        </select>
      </label>
    )
  }
  if (input.control === 'textarea') {
    return <label>{input.label}<textarea rows="2" value={value} required={required} onChange={(event) => onChange(event.target.value)} /></label>
  }
  return <label>{input.label}<input value={value} required={required} onChange={(event) => onChange(event.target.value)} autoComplete="off" /></label>
}

function initialValues(inputs) {
  return Object.fromEntries(
    inputs.map((input) => [input.field_code, input.choices?.[0]?.value || '']),
  )
}

function isRequired(input, values) {
  return input.required || (
    input.required_when
    && values[input.required_when.field_code] === input.required_when.equals
  )
}
