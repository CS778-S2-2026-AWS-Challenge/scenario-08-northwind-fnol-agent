import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clearStoredSession, workbenchApi } from './api.js'

function response(status, payload) {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: vi.fn().mockResolvedValue(payload),
  }
}

describe('Workbench API failures', () => {
  beforeEach(() => {
    clearStoredSession()
    vi.restoreAllMocks()
  })

  it('preserves the backend recovery fields on an API error', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(409, {
      error: {
        code: 'REVISION_CONFLICT',
        message: 'The Claim revision changed.',
        details: [{ field: 'If-Match' }],
        request_id: 'req_conflict_1',
        retryable: false,
        current_revision: 9,
      },
    }))

    await expect(workbenchApi.claim('staff-token', 'clm_1')).rejects.toMatchObject({
      status: 409,
      code: 'REVISION_CONFLICT',
      requestId: 'req_conflict_1',
      retryable: false,
      currentRevision: 9,
    })
  })

  it('reuses the operation key only for an identical retry after an unknown result', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch')
      .mockRejectedValueOnce(new TypeError('connection lost'))
      .mockResolvedValueOnce(response(200, { message_id: 'msg_1' }))

    await expect(workbenchApi.sendMessage('staff-token', 'clm_1', 'Hello', 4))
      .rejects.toMatchObject({ code: 'NETWORK_ERROR', retryable: true })
    await workbenchApi.sendMessage('staff-token', 'clm_1', 'Hello', 4)

    expect(fetch.mock.calls[0][1].headers['Idempotency-Key']).toBe(
      fetch.mock.calls[1][1].headers['Idempotency-Key'],
    )
  })

  it('uses a new operation key when the payload changes', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch')
      .mockRejectedValueOnce(new TypeError('connection lost'))
      .mockResolvedValueOnce(response(200, { message_id: 'msg_2' }))

    await expect(workbenchApi.sendMessage('staff-token', 'clm_1', 'First draft', 4))
      .rejects.toThrow('could not be reached')
    await workbenchApi.sendMessage('staff-token', 'clm_1', 'Revised draft', 4)

    expect(fetch.mock.calls[0][1].headers['Idempotency-Key']).not.toBe(
      fetch.mock.calls[1][1].headers['Idempotency-Key'],
    )
  })
})
