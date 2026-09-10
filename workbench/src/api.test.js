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
    localStorage.clear()
    sessionStorage.clear()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('continues pagination until the requested Claim session is found', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(200, {
        items: Array.from({ length: 25 }, (_, index) => ({
          session_id: `ses_${index + 1}`,
        })),
        page: { next_cursor: 'page-2' },
      }))
      .mockResolvedValueOnce(jsonResponse(200, {
        items: [
          { session_id: 'ses_26' },
          { session_id: 'ses_27' },
        ],
        page: { next_cursor: null },
      }))

    vi.stubGlobal('fetch', fetchMock)

    const result = await workbenchApi.sessionsForTarget(
      'staff-token',
      'clm_many_sessions',
      'ses_26',
    )

    expect(result.resolved_session).toEqual({
      session_id: 'ses_26',
    })
    expect(result.items).toHaveLength(27)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls[1][0]).toContain(
      'cursor=page-2',
    )
  })

  it('returns no resolved session when the requested session does not exist', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(200, {
        items: [{ session_id: 'ses_old' }],
        page: { next_cursor: 'page-2' },
      }))
      .mockResolvedValueOnce(jsonResponse(200, {
        items: [{ session_id: 'ses_other' }],
        page: { next_cursor: null },
      }))

    vi.stubGlobal('fetch', fetchMock)

    const result = await workbenchApi.sessionsForTarget(
      'staff-token',
      'clm_unknown_session',
      'ses_missing',
    )

    expect(result.resolved_session).toBeNull()
    expect(result.items.map((item) => item.session_id)).toEqual([
      'ses_old',
      'ses_other',
    ])
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})

describe('workbenchApi staff message retries', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    clearStoredSession()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('reuses one idempotency key after an ambiguous network failure', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('network unavailable'))
      .mockResolvedValueOnce(jsonResponse(200, { claim_revision: 5 }))
      .mockResolvedValueOnce(jsonResponse(200, { claim_revision: 6 }))

    vi.stubGlobal('fetch', fetchMock)

    const operation = {
      message: 'Same staff reply',
      sessionId: 'ses_retry',
    }

    await expect(
      workbenchApi.sendMessage(
        'staff-token',
        'clm_retry',
        operation,
        4,
      ),
    ).rejects.toMatchObject({
      code: 'NETWORK_ERROR',
    })

    await workbenchApi.sendMessage(
      'staff-token',
      'clm_retry',
      operation,
      4,
    )

    const firstKey =
      fetchMock.mock.calls[0][1].headers['Idempotency-Key']
    const retryKey =
      fetchMock.mock.calls[1][1].headers['Idempotency-Key']

    expect(retryKey).toBe(firstKey)

    await workbenchApi.sendMessage(
      'staff-token',
      'clm_retry',
      operation,
      5,
    )

    const nextKey =
      fetchMock.mock.calls[2][1].headers['Idempotency-Key']

    expect(nextKey).not.toBe(firstKey)
  })

  it('does not let another displayed session bypass an unknown outcome', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('network unavailable'))

    vi.stubGlobal('fetch', fetchMock)

    await expect(
      workbenchApi.sendMessage(
        'staff-token',
        'clm_session_scope',
        {
          message: 'Same text',
          sessionId: 'ses_first',
        },
        4,
      ),
    ).rejects.toMatchObject({
      code: 'NETWORK_ERROR',
    })

    await expect(
      workbenchApi.sendMessage(
        'staff-token',
        'clm_session_scope',
        {
          message: 'Same text',
          sessionId: 'ses_second',
        },
        4,
      ),
    ).rejects.toMatchObject({
      code: 'MESSAGE_DELIVERY_UNKNOWN',
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('does not let an edited payload bypass an unknown outcome', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('network unavailable'))

    vi.stubGlobal('fetch', fetchMock)

    await expect(
      workbenchApi.sendMessage(
        'staff-token',
        'clm_payload_scope',
        {
          message: 'Original staff reply',
          sessionId: 'ses_payload',
        },
        4,
      ),
    ).rejects.toMatchObject({
      code: 'NETWORK_ERROR',
    })

    await expect(
      workbenchApi.sendMessage(
        'staff-token',
        'clm_payload_scope',
        {
          message: 'Edited staff reply',
          sessionId: 'ses_payload',
        },
        4,
      ),
    ).rejects.toMatchObject({
      code: 'MESSAGE_DELIVERY_UNKNOWN',
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('discards the retry key after a stale-revision rejection', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(409, {
        error: {
          code: 'REVISION_CONFLICT',
          message: 'The Claim changed after this page was loaded.',
          details: [],
        },
      }))
      .mockResolvedValueOnce(jsonResponse(200, {
        claim_revision: 8,
      }))

    vi.stubGlobal('fetch', fetchMock)

    const operation = {
      message: 'Review update',
      sessionId: 'ses_stale',
    }

    await expect(
      workbenchApi.sendMessage(
        'staff-token',
        'clm_stale',
        operation,
        6,
      ),
    ).rejects.toMatchObject({
      code: 'REVISION_CONFLICT',
    })

    await workbenchApi.sendMessage(
      'staff-token',
      'clm_stale',
      operation,
      7,
    )

    const staleKey =
      fetchMock.mock.calls[0][1].headers['Idempotency-Key']
    const refreshedKey =
      fetchMock.mock.calls[1][1].headers['Idempotency-Key']

    expect(refreshedKey).not.toBe(staleKey)
  })

  it('does not carry an ambiguous operation across logout', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('network unavailable'))
      .mockResolvedValueOnce(jsonResponse(200, {
        claim_revision: 5,
      }))

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
    ).rejects.toMatchObject({
      code: 'NETWORK_ERROR',
    })

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

  it('clears pending operations when a new staff session replaces the old one', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('network unavailable'))
      .mockResolvedValueOnce(jsonResponse(200, {
        claim_revision: 9,
      }))

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
    ).rejects.toMatchObject({
      code: 'NETWORK_ERROR',
    })

    const oldKey =
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

    const newKey =
      fetchMock.mock.calls[1][1].headers['Idempotency-Key']

    expect(newKey).not.toBe(oldKey)
  })
})
