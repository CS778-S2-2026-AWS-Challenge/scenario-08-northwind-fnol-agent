export function ProjectedActionState({ action, absentMessage }) {
  if (!action) return <p className="record-note">{absentMessage}</p>
  if (action.availability !== 'blocked') return null
  return (
    <p className="record-note record-note--blocked" role="status">
      <strong>{action.label} is blocked</strong>
      {action.blocked_reason || 'This action is not available for the current Claim state.'}
    </p>
  )
}

export function ProjectedActionInput({ input, required = input.required, onChange, onKeyDown, inputRef, value }) {
  const controlled = value === undefined ? {} : { value }
  if (input.control === 'select') {
    return (
      <label>
        {input.label}
        <select ref={inputRef} name={input.field_code} required={required} onChange={onChange} onKeyDown={onKeyDown} {...controlled}>
          {input.choices.map((choice) => <option value={choice.value} key={choice.value}>{choice.label}</option>)}
        </select>
      </label>
    )
  }
  if (input.control === 'textarea') {
    return <label>{input.label}<textarea ref={inputRef} name={input.field_code} rows="3" required={required} onChange={onChange} onKeyDown={onKeyDown} {...controlled} /></label>
  }
  return <label>{input.label}<input ref={inputRef} name={input.field_code} required={required} onChange={onChange} onKeyDown={onKeyDown} autoComplete="off" {...controlled} /></label>
}

export function ActionDetails({ action }) {
  if (!action) return null
  return (
    <details className="action-details">
      <summary>Action details</summary>
      <dl>
        <dt>Target</dt><dd>{action.target_ref}</dd>
        <dt>Availability</dt><dd>{action.availability.replaceAll('_', ' ')}</dd>
        <dt>Result state</dt><dd>{action.result_state?.replaceAll('_', ' ') || 'Not recorded'}</dd>
        <dt>Based on revision</dt><dd>{action.based_on_revision ?? 'Not recorded'}</dd>
        <dt>Expected effects</dt><dd>{action.expected_effects?.join(', ') || 'None recorded'}</dd>
        <dt>Sources</dt><dd>{action.source_refs?.join(', ') || 'None recorded'}</dd>
      </dl>
    </details>
  )
}
