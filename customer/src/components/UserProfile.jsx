import { PROFILE_CATEGORIES } from '../profileRoutes.js'
import AssetsSection from '../profile/AssetsSection.jsx'
import PaymentDetailsSection from '../profile/PaymentDetailsSection.jsx'
import PersonalDetailsSection from '../profile/PersonalDetailsSection.jsx'
import PoliciesSection from '../profile/PoliciesSection.jsx'
import { SectionHeading, SummaryRow } from '../profile/ProfilePrimitives.jsx'
import usePersonalDetailsEditor from '../profile/usePersonalDetailsEditor.js'
import ClaimAutoFillChoices from './ClaimAutoFillChoices.jsx'
import IdentityDocuments from './IdentityDocuments.jsx'

function ProfileNavigation({ activeSection, onOpenClaims, onSelectSection, mobile = false }) {
  return (
    <nav className={`profile-category-nav ${mobile ? 'is-mobile-index' : ''}`} aria-label="Profile navigation">
      <ul>
        {PROFILE_CATEGORIES.map(({ key, label }) => {
          const selected = !mobile && activeSection === key
          return (
            <li key={key}>
              <button
                className={selected ? 'is-active' : ''}
                type="button"
                aria-current={selected ? 'page' : undefined}
                onClick={() => onSelectSection(key)}
              >
                <span>{label}</span><span aria-hidden="true">›</span>
              </button>
            </li>
          )
        })}
        {onOpenClaims && (
          <li className="profile-claim-history-link">
            <button type="button" onClick={onOpenClaims}>
              <span>Claim history</span><span aria-hidden="true">›</span>
            </button>
          </li>
        )}
      </ul>
    </nav>
  )
}

function AutoFillUnavailable({ headingAs }) {
  return (
    <section className="profile-section" aria-labelledby="profile-claim-auto-fill">
      <SectionHeading
        as={headingAs}
        id="profile-claim-auto-fill"
        title="Claim auto-fill"
        description="Choose which saved information may be suggested when you start a future claim."
      />
      <div className="profile-availability-note">
        <strong>Unavailable</strong>
        <p>Northwind could not load these choices from your account. Reload Profile and try again.</p>
      </div>
      <p className="profile-helper-copy">Saved Profile information may only be suggested or prefilled. You must review and confirm it before it becomes claim information.</p>
      <dl className="profile-summary-list profile-compact-summary-list">
        {['Personal details', 'Policy number', 'Saved assets', 'Payment details', 'Identity information'].map((category) => (
          <SummaryRow key={category} label={category} value="Not configured" />
        ))}
      </dl>
    </section>
  )
}

export default function UserProfile({
  account,
  activeSection,
  assets = null,
  assetsError = '',
  autoFillChoices,
  autoFillDirty = false,
  autoFillError = '',
  autoFillNotice = '',
  autoFillSaving = false,
  controller,
  embedded = false,
  onChangeAutoFillChoice,
  onCreateAsset,
  onOpenClaims,
  onReloadAssets,
  onSaveAutoFillChoices,
  onSavePreferences,
  onSaveProfile,
  onSelectSection,
  onSignOut,
  onUpdateAsset,
}) {
  const currentSection = activeSection || 'personal-details'
  const SectionTitle = activeSection ? 'h1' : 'h2'
  const resolvedController = controller || {
    resources: {
      assets: { items: assets, error: assetsError, loading: assets === null, stale: false },
      policies: { items: [], error: '', loading: false, stale: false },
      payments: { items: [], error: '', loading: false, stale: false },
      identities: { items: [], error: '', loading: false, stale: false },
    },
    pending: {},
    beginCreate: (resource) => `${resource}-attempt-${globalThis.crypto?.randomUUID?.() || Date.now()}`,
    abandonCreate: () => {},
    saveProfile: onSaveProfile,
    savePreferences: onSavePreferences,
    createAsset: ({ asset }) => onCreateAsset(asset),
    saveAsset: onUpdateAsset,
    createPolicy: async () => {},
    savePolicy: async () => {},
    createPayment: async () => {},
    savePayment: async () => {},
    createIdentity: async () => {},
    saveIdentity: async () => {},
    reloadAssets: onReloadAssets,
    reloadPolicies: async () => [],
    reloadPayments: async () => [],
    reloadIdentities: async () => [],
  }
  const personalController = usePersonalDetailsEditor({
    account,
    onSaveProfile: resolvedController.saveProfile,
    onSavePreferences: resolvedController.savePreferences,
  })

  function selectProfileSection(section) {
    onSelectSection(section)
  }

  function renderSection() {
    if (currentSection === 'personal-details') {
      return (
        <PersonalDetailsSection
          account={account}
          controller={personalController}
          headingAs={SectionTitle}
        />
      )
    }
    if (currentSection === 'insured-assets') {
      return (
        <AssetsSection
          resource={resolvedController.resources.assets}
          pending={resolvedController.pending}
          headingAs={SectionTitle}
          onBeginCreate={resolvedController.beginCreate}
          onAbandonCreate={resolvedController.abandonCreate}
          onCreate={resolvedController.createAsset}
          onReload={resolvedController.reloadAssets}
          onUpdate={resolvedController.saveAsset}
        />
      )
    }
    if (currentSection === 'policies') {
      return (
        <PoliciesSection
          resource={resolvedController.resources.policies}
          pending={resolvedController.pending}
          headingAs={SectionTitle}
          onBeginCreate={resolvedController.beginCreate}
          onAbandonCreate={resolvedController.abandonCreate}
          onCreate={resolvedController.createPolicy}
          onReload={resolvedController.reloadPolicies}
          onUpdate={resolvedController.savePolicy}
        />
      )
    }
    if (currentSection === 'payment-details') {
      return (
        <PaymentDetailsSection
          resource={resolvedController.resources.payments}
          pending={resolvedController.pending}
          headingAs={SectionTitle}
          onBeginCreate={resolvedController.beginCreate}
          onAbandonCreate={resolvedController.abandonCreate}
          onCreate={resolvedController.createPayment}
          onReload={resolvedController.reloadPayments}
          onUpdate={resolvedController.savePayment}
        />
      )
    }
    if (currentSection === 'identity-verification') {
      return (
        <section className="profile-section" aria-labelledby="profile-identity-verification">
          <SectionHeading
            as={SectionTitle}
            id="profile-identity-verification"
            title="Identity & verification"
            description="Only add an identity document when Northwind needs it for a supported purpose."
          />
          <IdentityDocuments
            resource={resolvedController.resources.identities}
            pending={resolvedController.pending}
            onBeginCreate={resolvedController.beginCreate}
            onAbandonCreate={resolvedController.abandonCreate}
            onCreate={resolvedController.createIdentity}
            onReload={resolvedController.reloadIdentities}
            onUpdate={resolvedController.saveIdentity}
          />
        </section>
      )
    }
    if (autoFillChoices && onChangeAutoFillChoice && onSaveAutoFillChoices) {
      return (
        <section className="profile-section" aria-labelledby="profile-claim-auto-fill">
          <SectionHeading
            as={SectionTitle}
            id="profile-claim-auto-fill"
            title="Claim auto-fill"
            description="Choose which saved information may be suggested when you start a future claim."
          />
          <ClaimAutoFillChoices
            choices={autoFillChoices}
            dirty={autoFillDirty}
            saving={autoFillSaving}
            error={autoFillError}
            notice={autoFillNotice}
            onChange={onChangeAutoFillChoice}
            onSave={onSaveAutoFillChoices}
          />
        </section>
      )
    }
    return <AutoFillUnavailable headingAs={SectionTitle} />
  }

  return (
    <article
      className={`user-profile ${embedded ? 'is-embedded' : ''} ${activeSection ? 'has-selected-section' : 'is-category-index'}`}
      aria-label="Profile"
    >
      <div className="profile-workspace">
        <aside className="profile-sidebar">
          <ProfileNavigation activeSection={currentSection} onOpenClaims={onOpenClaims} onSelectSection={selectProfileSection} />
        </aside>
        <section className="profile-mobile-index" aria-label="Profile overview">
          <ProfileNavigation activeSection={null} onOpenClaims={onOpenClaims} onSelectSection={selectProfileSection} mobile />
        </section>
        <div className="profile-content">
          <button className="profile-mobile-back" type="button" onClick={() => selectProfileSection(null)}>
            <span aria-hidden="true">←</span> Back to profile
          </button>
          {renderSection()}
        </div>
      </div>
      {onSignOut && (
        <footer className="profile-footer">
          <button type="button" onClick={onSignOut} disabled={Boolean(Object.keys(resolvedController.pending).length)}>Log out</button>
        </footer>
      )}
    </article>
  )
}
