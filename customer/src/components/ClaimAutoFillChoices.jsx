import { useId } from 'react'

export default function ClaimAutoFillChoices({
  choices,
  dirty = false,
  saving = false,
  error = '',
  notice = '',
  onChange,
  onSave,
}) {
  const formId = useId()

  function submit(event) {
    event.preventDefault()
    if (dirty && !saving) onSave()
  }

  return (
    <form className="profile-autofill-form" onSubmit={submit}>
      <p className="profile-helper-copy">Show lets Northwind use this category in future Claims. When the matching Claim information is empty, one saved policy or asset is added automatically for review; if there are several, the Claim asks you to choose one.</p>
      <p className="profile-helper-copy">At the payout or identity step, saved details can be offered or preselected for separate confirmation. Full account and document numbers are never copied into the Claim.</p>
      <div className="profile-autofill-choices">
        {choices.map((choice, index) => {
          const inputId = `${formId}-${index}`
          return (
            <div className="profile-autofill-row" key={choice.key}>
              <label htmlFor={inputId}>{choice.label}</label>
              <select
                id={inputId}
                value={choice.visible ? 'show' : 'hide'}
                disabled={saving}
                onChange={(event) => onChange(choice.key, event.target.value === 'show')}
              >
                <option value="hide">Do not show</option>
                <option value="show">Show</option>
              </select>
            </div>
          )
        })}
      </div>
      {error && <p className="profile-form-error" role="alert">{error}</p>}
      {notice && <p className="profile-notice is-success" role="status">{notice}</p>}
      <button className="primary-button" type="submit" disabled={!dirty || saving}>
        {saving ? 'Saving…' : 'Save Claim auto-fill choices'}
      </button>
    </form>
  )
}
