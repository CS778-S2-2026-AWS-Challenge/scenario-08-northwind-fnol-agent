import { Bot, BriefcaseBusiness, FileClock, MessageSquareText } from 'lucide-react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import { storedProfileOverrides } from '../account/settings-gateway.js'
import { translate as t, useLanguage } from '../i18n.js'
import AccountMenu from './AccountMenu.jsx'

export default function NavigationRail({ profile, onLogout, onAgent, draftCount = null }) {
  useLanguage()
  const location = useLocation()
  const effectiveProfile = storedProfileOverrides(profile)
  const draftSelected = location.pathname.startsWith('/workbench/drafts')
  const workbenchSelected = location.pathname === '/workbench'
    || location.pathname.startsWith('/workbench/claims/')
  const workbenchLabel = t('Workbench')
  const conversationsLabel = t('Claim conversations')
  const agentLabel = t('Staff Agent')
  const draftLabel = t('Draft claims')
  const draftAccessibleLabel = Number.isInteger(draftCount)
    ? t('{count} Draft claims', { count: draftCount })
    : draftLabel
  return (
    <aside className="navigation-rail">
      <div className="navigation-brand" aria-label={t('Northwind Claims')}>
        <BriefcaseBusiness size={22} />
        <span>Northwind</span>
      </div>
      <nav aria-label={t('Workbench navigation')}>
        <Link
          to="/workbench"
          className={workbenchSelected ? 'active' : undefined}
          aria-current={workbenchSelected ? 'page' : undefined}
          aria-label={workbenchLabel}
        >
          <BriefcaseBusiness size={19} />
          <span>{workbenchLabel}</span>
        </Link>
        <Link
          to="/workbench/drafts"
          className={draftSelected ? 'active' : undefined}
          aria-current={draftSelected ? 'page' : undefined}
          aria-label={draftAccessibleLabel}
        >
          <FileClock size={19} />
          <span>{draftLabel}</span>
          {Number.isInteger(draftCount) && (
            <span className="navigation-rail__count">
              {draftCount}
            </span>
          )}
        </Link>
        <NavLink to="/workbench/conversations" aria-label={conversationsLabel}><MessageSquareText size={19} /><span>{conversationsLabel}</span></NavLink>
        <button type="button" onClick={onAgent} aria-label={agentLabel}><Bot size={19} /><span>{agentLabel}</span></button>
      </nav>
      <AccountMenu profile={effectiveProfile} onLogout={onLogout} />
    </aside>
  )
}
