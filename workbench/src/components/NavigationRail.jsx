import { Bot, BriefcaseBusiness, MessageSquareText } from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { storedProfileOverrides } from '../account/settings-gateway.js'
import { translate as t, useLanguage } from '../i18n.js'
import AccountMenu from './AccountMenu.jsx'

export default function NavigationRail({ profile, onLogout, onAgent }) {
  useLanguage()
  const effectiveProfile = storedProfileOverrides(profile)
  return (
    <aside className="navigation-rail">
      <div className="navigation-brand" aria-label={t('Northwind Claims')}>
        <BriefcaseBusiness size={22} />
        <span>Northwind</span>
      </div>
      <nav aria-label={t('Workbench navigation')}>
        <NavLink to="/workbench" end><BriefcaseBusiness size={19} /><span>{t('Workbench')}</span></NavLink>
        <NavLink to="/workbench/conversations"><MessageSquareText size={19} /><span>{t('Claim conversations')}</span></NavLink>
        <button type="button" onClick={onAgent}><Bot size={19} /><span>{t('Staff Agent')}</span></button>
      </nav>
      <AccountMenu profile={effectiveProfile} onLogout={onLogout} />
    </aside>
  )
}
