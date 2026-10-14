import { translate as t } from '../i18n.js'

export function ResourcePageHeader({ title, subtitle, countLabel, titleId }) {
  return (
    <header className="resource-page-header">
      <div className="resource-page-header__copy">
        <h2 id={titleId}>{t(title)}</h2>
        <p>{t(subtitle)}</p>
      </div>
      <span className="resource-page-header__count">{countLabel}</span>
    </header>
  )
}

export default function ResourceEmptyState({ icon: Icon, title, description }) {
  return (
    <div className="resource-empty-state" role="status">
      <Icon className="resource-empty-state__icon" aria-hidden="true" />
      <h3>{t(title)}</h3>
      <p>{t(description)}</p>
    </div>
  )
}
