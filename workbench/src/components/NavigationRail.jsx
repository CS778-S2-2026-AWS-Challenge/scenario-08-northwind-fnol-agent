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
        >
          <BriefcaseBusiness size={19} />
          <span>{t('Workbench')}</span>
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
        <NavLink to="/workbench/conversations"><MessageSquareText size={19} /><span>{t('Claim conversations')}</span></NavLink>
        <button type="button" onClick={onAgent}><Bot size={19} /><span>{t('Staff Agent')}</span></button>
      </nav>
      <AccountMenu profile={effectiveProfile} onLogout={onLogout} />
    </aside>
  )
}
