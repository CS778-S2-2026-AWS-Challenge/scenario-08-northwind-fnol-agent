import { Bot, BriefcaseBusiness, LogOut, MessageSquareText } from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { initials } from '../format.js'

export default function NavigationRail({ profile, onLogout, onAgent }) {
  return (
    <aside className="navigation-rail">
      <div className="navigation-brand" aria-label="Northwind Claims">
        <BriefcaseBusiness size={22} />
        <span>Northwind</span>
      </div>
      <nav aria-label="Workbench navigation">
        <NavLink to="/workbench" end><BriefcaseBusiness size={19} /><span>Workbench</span></NavLink>
        <NavLink to="/workbench/conversations"><MessageSquareText size={19} /><span>Claim conversations</span></NavLink>
        <button type="button" onClick={onAgent}><Bot size={19} /><span>Staff Agent</span></button>
      </nav>
      <div className="navigation-profile">
        <span className="profile-avatar">{initials(profile?.display_name)}</span>
        <div><strong>{profile?.display_name || 'Claims professional'}</strong><small>{profile?.roles?.[0]?.replaceAll('_', ' ') || 'Staff'}</small></div>
        <button className="icon-button" type="button" onClick={onLogout} aria-label="Sign out"><LogOut size={17} /></button>
      </div>
    </aside>
  )
}
