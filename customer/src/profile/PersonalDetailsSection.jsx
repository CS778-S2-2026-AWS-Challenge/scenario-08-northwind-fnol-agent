import { FeatureNotice, SummaryRow } from './ProfilePrimitives.jsx'

function maskEmail(value = '') {
  const [local, domain] = value.split('@')
  if (!local || !domain) return value ? '••••' : 'Not provided'
  return `${local.slice(0, 1)}•••@${domain}`
}

function maskPhone(value = '') {
  const digits = value.replace(/\D/g, '')
  if (!digits) return 'Not provided'
  return `••• ••• ${digits.slice(-3).padStart(3, '•')}`
}

function initials(value = '') {
  const parts = value.trim().split(/\s+/).filter(Boolean)
  return (parts.slice(0, 2).map((part) => part[0]).join('') || 'NW').toUpperCase()
}

function contactPreference(preferences = {}) {
  if (preferences.email && preferences.sms) return 'Multiple saved — choose one'
  if (preferences.email) return 'Email'
  if (preferences.sms) return 'SMS'
  return 'Not provided'
}

function formatDateOfBirth(value) {
  if (!value) return 'Not provided'
  const date = new Date(`${value}T00:00:00`)
  if (Number.isNaN(date.getTime())) return 'Not provided'
  return new Intl.DateTimeFormat('en-NZ', {
    day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Pacific/Auckland',
  }).format(date)
}

function ProfileHeader({ account, controller }) {
  return (
    <header className="profile-header">
      <div className="profile-avatar" aria-hidden="true">{initials(account.profile.display_name)}</div>
      <div className="profile-header-copy">
        <span className="profile-account-name-label">Preferred name</span>
        <strong>{account.profile.preferred_name || 'Not provided'}</strong>
        <p className="profile-header-meta">
          <span>Customer ID:</span>
          <strong>{account.customer_id || 'Not provided'}</strong>
        </p>
      </div>
      <button
        id="profile-edit-button"
        className="profile-quiet-action"
        type="button"
        aria-expanded={controller.activeEditor === 'profile'}
        aria-controls="profile-header-editor"
        onClick={controller.activeEditor === 'profile'
          ? controller.closeEditor
          : () => controller.openEditor('profile')}
      >
        {controller.activeEditor === 'profile' ? 'Done' : 'Edit profile'}
      </button>
    </header>
  )
}

export default function PersonalDetailsSection({
  account,
  controller,
  headingAs: Heading = 'h1',
}) {
  const profile = account.profile || {}
  return (
    <section className="profile-section" aria-label="Personal details">
      <FeatureNotice notice={controller.notice} />
      <section className="profile-header-region" aria-label="Profile header">
        <ProfileHeader account={account} controller={controller} />
        {controller.activeEditor === 'profile' && (
          <form id="profile-header-editor" className="profile-edit-form profile-header-editor" onSubmit={controller.saveDetails}>
            <h3>Profile details</h3>
            <label htmlFor="profile-preferred-name">Preferred name <span>(optional)</span></label>
            <input
              autoFocus
              id="profile-preferred-name"
              name="preferred_name"
              aria-label="Preferred name"
              value={controller.detailDraft.preferredName}
              maxLength="120"
              autoComplete="name"
              onChange={(event) => controller.changeDetail('preferredName', event.target.value)}
            />
            <p className="profile-field-limit">Clear this field to use your legal name as the account display name. Avatar changes remain unavailable.</p>
            <button className="primary-button" type="submit" disabled={controller.saving || !controller.detailsDirty}>
              {controller.saving ? 'Saving…' : 'Save profile'}
            </button>
          </form>
        )}
      </section>

      <section className="profile-personal-information" aria-labelledby="profile-personal-information-title">
        <header className="profile-personal-information-heading">
          <Heading id="profile-personal-information-title">Personal information</Heading>
          <button
            id="profile-personal-edit-button"
            className="profile-quiet-action"
            type="button"
            aria-label={controller.activeEditor === 'personal'
              ? 'Done editing personal information'
              : 'Edit personal information'}
            aria-expanded={controller.activeEditor === 'personal'}
            aria-controls="profile-personal-editor"
            onClick={controller.activeEditor === 'personal'
              ? controller.closeEditor
              : () => controller.openEditor('personal')}
          >
            {controller.activeEditor === 'personal' ? 'Done' : 'Edit'}
          </button>
        </header>
        <dl className="profile-summary-list">
          <SummaryRow label="Legal name" value={profile.legal_name || 'Not provided'} />
          <SummaryRow label="Date of birth" value={formatDateOfBirth(profile.date_of_birth)} />
          <SummaryRow label="Phone" value={maskPhone(profile.phone)} />
          <SummaryRow label="Email" value={maskEmail(profile.email)} />
          <SummaryRow label="Preferred contact" value={contactPreference(account.preferences)} />
          <SummaryRow label="Residential address" value={profile.residential_address || 'Not provided'} />
        </dl>
        {controller.activeEditor === 'personal' && (
          <div id="profile-personal-editor" className="profile-personal-editor">
            <form className="profile-edit-form" onSubmit={controller.saveDetails}>
              <h3>Personal details</h3>
              <div className="profile-personal-field-grid">
                <div className="profile-personal-field">
                  <label htmlFor="profile-legal-name">Legal name</label>
                  <input
                    autoFocus
                    id="profile-legal-name"
                    name="legal_name"
                    value={controller.detailDraft.legalName}
                    maxLength="120"
                    autoComplete="name"
                    required
                    onChange={(event) => controller.changeDetail('legalName', event.target.value)}
                  />
                </div>
                <div className="profile-personal-field">
                  <label htmlFor="profile-date-of-birth">Date of birth</label>
                  <input
                    id="profile-date-of-birth"
                    name="date_of_birth"
                    type="date"
                    value={controller.detailDraft.dateOfBirth}
                    onChange={(event) => controller.changeDetail('dateOfBirth', event.target.value)}
                  />
                </div>
                <div className="profile-personal-field">
                  <label htmlFor="profile-email">Email</label>
                  <input
                    id="profile-email"
                    name="email"
                    type="email"
                    value={controller.detailDraft.email}
                    maxLength="254"
                    autoComplete="email"
                    required
                    onChange={(event) => controller.changeDetail('email', event.target.value)}
                  />
                </div>
                <div className="profile-personal-field">
                  <label htmlFor="profile-phone">Phone number <span>(optional)</span></label>
                  <input
                    id="profile-phone"
                    name="phone"
                    type="tel"
                    value={controller.detailDraft.phone}
                    maxLength="40"
                    autoComplete="tel"
                    onChange={(event) => controller.changeDetail('phone', event.target.value)}
                  />
                </div>
                <div className="profile-personal-field is-wide">
                  <label htmlFor="profile-residential-address">Residential address <span>(optional)</span></label>
                  <textarea
                    id="profile-residential-address"
                    name="residential_address"
                    value={controller.detailDraft.residentialAddress}
                    maxLength="500"
                    autoComplete="street-address"
                    rows="3"
                    onChange={(event) => controller.changeDetail('residentialAddress', event.target.value)}
                  />
                </div>
              </div>
              <p className="profile-field-limit">Keep these details current so Northwind can use them when you choose a contact preference.</p>
              <button className="primary-button" type="submit" disabled={controller.saving || !controller.detailsDirty}>
                {controller.saving ? 'Saving…' : 'Save personal information'}
              </button>
            </form>
            <form className="profile-edit-form profile-preferences-form" onSubmit={controller.savePreferences}>
              <h3>Contact preferences</h3>
              <label className="profile-check-row">
                <input
                  name="contact_preference"
                  type="radio"
                  value="email"
                  checked={controller.preferenceDraft.email && !controller.preferenceDraft.sms}
                  onChange={() => controller.choosePreference('email')}
                />
                <span><strong>Email</strong><small>Use the saved email address for claim updates.</small></span>
              </label>
              <label className="profile-check-row">
                <input
                  name="contact_preference"
                  type="radio"
                  value="sms"
                  checked={controller.preferenceDraft.sms && !controller.preferenceDraft.email}
                  onChange={() => controller.choosePreference('sms')}
                />
                <span><strong>SMS</strong><small>Use the saved phone number for claim updates.</small></span>
              </label>
              <button className="secondary-button" type="submit" disabled={controller.saving || !controller.preferencesDirty}>
                {controller.saving ? 'Saving…' : 'Save contact preferences'}
              </button>
            </form>
          </div>
        )}
      </section>
    </section>
  )
}
