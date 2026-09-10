import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  clearStoredSession,
  storeSession,
  workbenchApi,
} from './api.js'

function jsonResponse(status, payload) {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: vi.fn().mockResolvedValue(payload),
  }
}


describe('workbenchApi Claim session resolution', () => {
  beforeEach(() => {
    clearStoredSession()
    sessionStorage.clear()
    vi.unstubAllGlobals()
  })

  it('follows pagination until the requested session is found', async () => {
    const firstPage = Array.from({ length: 25 }, (_, index) => ({
      session_id: `ses_${index + 1}`,
    }))

    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(200, {
        items: firstPage,
        page: { next_cursor: 'page-2' },
      }))
      .mockResolvedValueOnce(jsonResponse(200, {
        items: [{ session_id: 'ses_26' }],
        page: { next_cursor: null },
      }))

    vi.stubGlobal('fetch', fetchMock)

    const result = await workbenchApi.sessionsForTarget(
      'staff-token',
      'clm_many',
      'ses_26',
    )

    expect(result.resolved_session?.session_id).toBe('ses_26')
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls[1][0]).toContain('cursor=page-2')
  })

  it('does not substitute another session when the requested one is unknown', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(200, {
        items: [{ session_id: 'ses_old' }],
        page: { next_cursor: 'next' },
      }))
      .mockResolvedValueOnce(jsonResponse(200, {
        items: [{ session_id: 'ses_other' }],
        page: { next_cursor: null },
      }))

    vi.stubGlobal('fetch', fetchMock)

    const result = await workbenchApi.sessionsForTarget(
      'staff-token',
      'clm_unknown',
      'ses_missing',
    )

    expect(result.resolved_session).toBeNull()
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})

describe('workbenchApi staff message retries', () => {
  beforeEach(() => {
    clearStoredSession()
    sessionStorage.clear()
    vi.unstubAllGlobals()
  })

  it('reuses one idempotency key after an ambiguous network failure', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('network unavailable'))
      .mockResolvedValueOnce(jsonResponse(200, { claim_revision: 5 }))
      .mockResolvedValueOnce(jsonResponse(200, { claim_revision: 6 }))
    vi.stubGlobal('fetch', fetchMock)
    const operation = { message: 'Same staff reply', sessionId: 'ses_retry' }

    await expect(
      workbenchApi.sendMessage('staff-token', 'clm_retry', operation, 4),
    ).rejects.toMatchObject({ code: 'NETWORK_ERROR' })

    await workbenchApi.sendMessage('staff-token', 'clm_retry', operation, 4)

    const firstKey = fetchMock.mock.calls[0][1].headers['Idempotency-Key']
    const retryKey = fetchMock.mock.calls[1][1].headers['Idempotency-Key']
    expect(retryKey).toBe(firstKey)

    await workbenchApi.sendMessage('staff-token', 'clm_retry', operation, 5)
    const nextOperationKey = fetchMock.mock.calls[2][1].headers['Idempotency-Key']
    expect(nextOperationKey).not.toBe(firstKey)
  })

  it('does not let a different displayed session bypass an unknown delivery outcome', async () => {
    const fetchMock = vi.fn().mockRejectedValueOnce(new TypeError('network unavailable'))
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      workbenchApi.sendMessage(
        'staff-token',
        'clm_session_scope',
        { message: 'Same text', sessionId: 'ses_first' },
        4,
      ),
    ).rejects.toMatchObject({ code: 'NETWORK_ERROR' })

    await expect(
      workbenchApi.sendMessage(
        'staff-token',
        'clm_session_scope',
        { message: 'Same text', sessionId: 'ses_second' },
        4,
      ),
    ).rejects.toMatchObject({ code: 'MESSAGE_DELIVERY_UNKNOWN' })

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('does not let an edited payload bypass an unknown delivery outcome', async () => {
    const fetchMock = vi.fn().mockRejectedValueOnce(new TypeError('network unavailable'))
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      workbenchApi.sendMessage(
        'staff-token',
        'clm_payload_scope',
        { message: 'Original staff reply', sessionId: 'ses_payload' },
        4,
      ),
    ).rejects.toMatchObject({ code: 'NETWORK_ERROR' })

    await expect(
      workbenchApi.sendMessage(
        'staff-token',
        'clm_payload_scope',
        { message: 'Edited staff reply', sessionId: 'ses_payload' },
        4,
      ),
    ).rejects.toMatchObject({ code: 'MESSAGE_DELIVERY_UNKNOWN' })

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('discards the retry key after a definite stale-revision rejection', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(409, {
        error: {
          code: 'REVISION_CONFLICT',
          message: 'The Claim changed after this page was loaded.',
          details: [],
        },
      }))
      .mockResolvedValueOnce(jsonResponse(200, { claim_revision: 8 }))
    vi.stubGlobal('fetch', fetchMock)
    const operation = { message: 'Review update', sessionId: 'ses_stale' }

    await expect(
      workbenchApi.sendMessage('staff-token', 'clm_stale', operation, 6),
    ).rejects.toMatchObject({ code: 'REVISION_CONFLICT' })

    await workbenchApi.sendMessage('staff-token', 'clm_stale', operation, 7)

    const staleKey = fetchMock.mock.calls[0][1].headers['Idempotency-Key']
    const refreshedKey = fetchMock.mock.calls[1][1].headers['Idempotency-Key']
    expect(refreshedKey).not.toBe(staleKey)
  })

  it('clears an ambiguous operation across logout', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('network unavailable'))
      .mockResolvedValueOnce(jsonResponse(200, { claim_revision: 5 }))
    vi.stubGlobal('fetch', fetchMock)

    const operation = {
      message: 'Identity-bound reply',
      sessionId: 'ses_identity',
    }

    await expect(
      workbenchApi.sendMessage(
        'staff-a-token',
        'clm_identity',
        operation,
        4,
      ),
    ).rejects.toMatchObject({ code: 'NETWORK_ERROR' })

    const firstKey =
      fetchMock.mock.calls[0][1].headers['Idempotency-Key']

    clearStoredSession()

    await workbenchApi.sendMessage(
      'staff-b-token',
      'clm_identity',
      operation,
      4,
    )

    const secondKey =
      fetchMock.mock.calls[1][1].headers['Idempotency-Key']

    expect(secondKey).not.toBe(firstKey)
  })

  it('clears an ambiguous operation when the staff session is replaced', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('network unavailable'))
      .mockResolvedValueOnce(jsonResponse(200, { claim_revision: 9 }))
    vi.stubGlobal('fetch', fetchMock)

    const operation = {
      message: 'Replacement-session reply',
      sessionId: 'ses_replace',
    }

    await expect(
      workbenchApi.sendMessage(
        'old-token',
        'clm_replace',
        operation,
        8,
      ),
    ).rejects.toMatchObject({ code: 'NETWORK_ERROR' })

    const firstKey =
      fetchMock.mock.calls[0][1].headers['Idempotency-Key']

    storeSession({
      access_token: 'new-token',
      expires_at: '2099-01-01T00:00:00Z',
    })

    await workbenchApi.sendMessage(
      'new-token',
      'clm_replace',
      operation,
      8,
    )

    const secondKey =
      fetchMock.mock.calls[1][1].headers['Idempotency-Key']

    expect(secondKey).not.toBe(firstKey)
  })

})
