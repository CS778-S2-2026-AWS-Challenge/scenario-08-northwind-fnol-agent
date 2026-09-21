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
      <p className="profile-helper-copy">Show makes a category eligible for a future Claim suggestion. You will review and confirm any suggested information before it enters a Claim.</p>
      <p className="profile-helper-copy">Payment details and Identity information only prompt you to confirm separately. Their numbers are never suggested.</p>
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
