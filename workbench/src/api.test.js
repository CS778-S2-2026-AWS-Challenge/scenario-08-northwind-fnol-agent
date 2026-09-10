import { beforeEach, describe, expect, it, vi } from 'vitest'
import { workbenchApi } from './api.js'

function jsonResponse(status, payload) {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: vi.fn().mockResolvedValue(payload),
  }
}

describe('workbenchApi staff message retries', () => {
  beforeEach(() => {
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
})
