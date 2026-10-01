import { profilePathForSection, profileSectionFromPath } from './profileRoutes.js'

// Claimant app routes. The app keeps one `page` value plus the workspace flags;
// these helpers translate between that state and the browser path.

export function protectedAccountPageForPath(pathname) {
  if (pathname === '/account/claims') return 'claim-history'
  if (/^\/account\/claims\/[^/]+\/evidence$/.test(pathname)) return 'claim-evidence'
  if (/^\/account\/claims\/[^/]+$/.test(pathname)) return 'claim-features'
  if (pathname === '/files') return 'files'
  return null
}

export function pageForPath(pathname, { authenticated }) {
  if (pathname === '/auth/login') return 'login'
  if (pathname === '/auth/register') return 'register'
  if (pathname === '/profile' || pathname === '/account' || profileSectionFromPath(pathname)) {
    return authenticated ? 'account' : 'login'
  }
  const protectedPage = protectedAccountPageForPath(pathname)
  if (protectedPage) return authenticated ? protectedPage : 'login'
  if (pathname === '/how-it-works') return 'how-it-works'
  return 'home'
}

export function historyClaimIdFromPath(pathname) {
  const match = pathname?.match(/^\/account\/claims\/([^/]+)/)
  return match ? decodeURIComponent(match[1]) : null
}

export function routeForPage(page, {
  profileSection = null,
  historyClaimId = null,
  workspaceActive = false,
  draftWorkspace = false,
  claimId = null,
} = {}) {
  if (page === 'login') return '/auth/login'
  if (page === 'register') return '/auth/register'
  if (page === 'account') return profilePathForSection(profileSection)
  if (page === 'claim-history') return '/account/claims'
  if (page === 'claim-features' && historyClaimId) return `/account/claims/${encodeURIComponent(historyClaimId)}`
  if (page === 'claim-evidence' && historyClaimId) return `/account/claims/${encodeURIComponent(historyClaimId)}/evidence`
  if (page === 'files') return '/files'
  if (page === 'how-it-works') return '/how-it-works'
  if (workspaceActive && draftWorkspace) return '/claims/new'
  if (workspaceActive && claimId) return `/claims/${claimId}`
  return '/'
}
