import { describe, expect, it } from 'vitest'

import {
  historyClaimIdFromPath,
  pageForPath,
  routeForPage,
  workspaceClaimIdFromPath,
} from './appRoutes.js'

describe('claimant app routes', () => {
  it.each([
    ['/auth/login', 'login', 'login'],
    ['/profile', 'account', 'login'],
    ['/profile/policies', 'account', 'login'],
    ['/account/claims', 'claim-history', 'login'],
    ['/account/claims/clm_1', 'claim-features', 'login'],
    ['/account/claims/clm_1/messages', 'claim-messages', 'login'],
    ['/account/claims/clm_1/evidence', 'claim-evidence', 'login'],
    ['/files', 'files', 'login'],
    ['/how-it-works', 'how-it-works', 'how-it-works'],
    ['/claims/new', 'home', 'home'],
    ['/claims/clm_1', 'home', 'home'],
    ['/', 'home', 'home'],
  ])('maps %s to %s when signed in and %s when not', (path, signedIn, anonymous) => {
    expect(pageForPath(path, { authenticated: true })).toBe(signedIn)
    expect(pageForPath(path, { authenticated: false })).toBe(anonymous)
  })

  it('reads and writes the history Claim id with encoding', () => {
    expect(historyClaimIdFromPath('/account/claims/clm%2Fa/evidence')).toBe('clm/a')
    expect(historyClaimIdFromPath('/claims/clm_1')).toBeNull()
    expect(routeForPage('claim-messages', { historyClaimId: 'clm/a' })).toBe('/account/claims/clm%2Fa/messages')
    expect(routeForPage('claim-evidence', { historyClaimId: 'clm/a' })).toBe('/account/claims/clm%2Fa/evidence')
  })

  it('reads the main workspace Claim id without confusing account routes', () => {
    expect(workspaceClaimIdFromPath('/claims/clm%2Fa')).toBe('clm/a')
    expect(workspaceClaimIdFromPath('/claims/new')).toBeNull()
    expect(workspaceClaimIdFromPath('/account/claims/clm_1/messages')).toBeNull()
  })

  it('routes home to the start page or the open conversation', () => {
    expect(routeForPage('home')).toBe('/')
    expect(routeForPage('home', { workspaceActive: true, draftWorkspace: true })).toBe('/claims/new')
    expect(routeForPage('home', { workspaceActive: true, claimId: 'clm_1' })).toBe('/claims/clm_1')
    expect(routeForPage('home', { workspaceActive: false, claimId: 'clm_1' })).toBe('/')
    expect(routeForPage('account', { profileSection: 'policies' })).toBe('/profile/policies')
  })
})
