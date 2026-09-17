import { beforeEach, describe, expect, it } from 'vitest'
import {
  forgetAnonymousConversation,
  readAnonymousConversationHistory,
  rememberAnonymousConversation,
} from './anonymousConversationHistory.js'

const resumableClaim = {
  claim_id: 'clm_anonymous_one',
  incident_type: 'home',
  created_at: '2026-09-16T01:00:00Z',
  updated_at: '2026-09-16T01:05:00Z',
  customer_next_step: {
    summary: 'Continue describing what happened.',
    can_resume: true,
  },
  form: {
    'incident.description': { value: 'Private incident detail' },
  },
  messages: [{ content: { text: 'Private conversation text' } }],
}

describe('anonymous conversation history', () => {
  beforeEach(() => {
    globalThis.sessionStorage.clear()
    globalThis.sessionStorage.setItem('northwind.anonymousSession', 'anonymous-session-one')
  })

  it('stores only a minimal resumable projection for the current anonymous session', () => {
    rememberAnonymousConversation(resumableClaim)

    expect(readAnonymousConversationHistory()).toEqual([{
      claim_id: 'clm_anonymous_one',
      incident_type: 'home',
      customer_next_step: {
        summary: 'Continue this conversation.',
        can_resume: true,
      },
      created_at: '2026-09-16T01:00:00Z',
      updated_at: '2026-09-16T01:05:00Z',
      can_resume: true,
    }])
    expect([...Array(globalThis.sessionStorage.length)].map((_, index) => (
      globalThis.sessionStorage.getItem(globalThis.sessionStorage.key(index))
    )).join(' ')).not.toContain('Private incident detail')
    expect([...Array(globalThis.sessionStorage.length)].map((_, index) => (
      globalThis.sessionStorage.getItem(globalThis.sessionStorage.key(index))
    )).join(' ')).not.toContain('Private conversation text')
    expect([...Array(globalThis.sessionStorage.length)].map((_, index) => (
      globalThis.sessionStorage.getItem(globalThis.sessionStorage.key(index))
    )).join(' ')).not.toContain('Continue describing what happened')
  })

  it('does not retain non-resumable Claims', () => {
    rememberAnonymousConversation(resumableClaim)
    rememberAnonymousConversation({
      ...resumableClaim,
      customer_next_step: { summary: 'No further action.', can_resume: false },
    })

    expect(readAnonymousConversationHistory()).toEqual([])
  })

  it('partitions and removes references within the active anonymous session', () => {
    rememberAnonymousConversation(resumableClaim)
    globalThis.sessionStorage.setItem('northwind.anonymousSession', 'anonymous-session-two')
    expect(readAnonymousConversationHistory()).toEqual([])

    globalThis.sessionStorage.setItem('northwind.anonymousSession', 'anonymous-session-one')
    forgetAnonymousConversation(resumableClaim.claim_id)
    expect(readAnonymousConversationHistory()).toEqual([])
  })
})
