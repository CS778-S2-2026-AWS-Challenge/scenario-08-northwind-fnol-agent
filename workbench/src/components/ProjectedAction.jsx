import { translate as t } from '../i18n.js'

export function ProjectedActionState({ action, absentMessage }) {
  if (!action) return <p className="record-note">{absentMessage}</p>
  if (action.availability !== 'blocked') return null
  return (
    <p className="record-note record-note--blocked" role="status">
      <strong>{t('{action} is blocked', { action: action.label })}</strong>
      {action.blocked_reason || t('This action is not available for the current Claim state.')}
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
          {required && <option value="" disabled>{t('Select an option')}</option>}
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
      <summary>{t('Action details')}</summary>
      <dl>
        <dt>{t('Target')}</dt><dd>{action.target_ref}</dd>
        <dt>{t('Availability')}</dt><dd>{action.availability.replaceAll('_', ' ')}</dd>
        <dt>{t('Result state')}</dt><dd>{action.result_state ? action.result_state.replaceAll('_', ' ') : t('Not recorded')}</dd>
        <dt>{t('Based on revision')}</dt><dd>{action.based_on_revision ?? t('Not recorded')}</dd>
        <dt>{t('Expected effects')}</dt><dd>{action.expected_effects?.join(', ') || t('None recorded')}</dd>
        <dt>{t('Sources')}</dt><dd>{action.source_refs?.join(', ') || t('None recorded')}</dd>
      </dl>
    </details>
  )
}
