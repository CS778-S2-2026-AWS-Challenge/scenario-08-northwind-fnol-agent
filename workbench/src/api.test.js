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

function eventStreamResponse(frames, status = 200) {
  const encoder = new TextEncoder()
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const frame of frames) controller.enqueue(encoder.encode(frame))
        controller.close()
      },
    }),
    { status, headers: { 'Content-Type': 'text/event-stream' } },
  )
}

function staffMessageResponse(claimId, sessionId, claimRevision, messageId) {
  return {
    claim_id: claimId,
    session_id: sessionId,
    claim_revision: claimRevision,
    message: {
      message_id: messageId,
      claim_id: claimId,
      session_id: sessionId,
      actor: 'staff',
      visibility: 'shared',
      content: { type: 'text', text: 'Synthetic staff reply' },
      created_at: '2026-09-16T00:00:00Z',
    },
  }
}


describe('Workbench realtime stream', () => {
  beforeEach(() => {
    clearStoredSession()
    sessionStorage.clear()
    vi.unstubAllGlobals()
  })

  it('parses multiplexed resource hints and sends the staff token in the header', async () => {
    const fetchMock = vi.fn().mockResolvedValue(eventStreamResponse([
      ': connected\n\n',
      'id: staff-cursor-2\nevent: resources.changed\ndata: {"event_id":"evt_staff_2","claim_id":"clm_1","claim_revision":5,"resources":["claim","queue"]}\n\n',
      'event: resync_required\ndata: {"reason":"subscriber_overflow"}\n\n',
    ]))
    vi.stubGlobal('fetch', fetchMock)
    const received = []

    await workbenchApi.realtimeEvents('staff-token', {
      cursor: 'staff-cursor-1',
      signal: new AbortController().signal,
      onEvent: async (event) => received.push(event),
    })

    expect(received).toEqual([
      {
        type: 'resources.changed',
        cursor: 'staff-cursor-2',
        data: expect.objectContaining({
          event_id: 'evt_staff_2',
          claim_id: 'clm_1',
          resources: ['claim', 'queue'],
        }),
      },
      {
        type: 'resync_required',
        cursor: null,
        data: { reason: 'subscriber_overflow' },
      },
    ])
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/workbench/realtime/events?cursor=staff-cursor-1',
      expect.objectContaining({
        headers: {
          Accept: 'text/event-stream',
          Authorization: 'Bearer staff-token',
        },
      }),
    )
  })

  it('surfaces an invalid Workbench cursor for full resynchronization', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(409, {
      error: {
        code: 'INVALID_EVENT_CURSOR',
        message: 'The realtime cursor is unavailable.',
        request_id: 'req_realtime_cursor',
        retryable: true,
      },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(workbenchApi.realtimeEvents('staff-token', {
      cursor: 'expired',
      signal: new AbortController().signal,
      onEvent: vi.fn(),
    })).rejects.toMatchObject({
      status: 409,
      code: 'INVALID_EVENT_CURSOR',
      requestId: 'req_realtime_cursor',
      retryable: true,
    })
  })
})


describe('Workbench API failures', () => {
  beforeEach(() => {
    clearStoredSession()
    sessionStorage.clear()
    vi.unstubAllGlobals()
  })

  it('preserves the backend recovery fields on an API error', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(409, {
      error: {
        code: 'REVISION_CONFLICT',
        message: 'The Claim revision changed.',
        details: [{ field: 'If-Match' }],
        request_id: 'req_conflict_1',
        retryable: false,
        current_revision: 9,
      },
    }))

    vi.stubGlobal('fetch', fetchMock)

    await expect(
      workbenchApi.claim('staff-token', 'clm_1'),
    ).rejects.toMatchObject({
      status: 409,
      code: 'REVISION_CONFLICT',
      requestId: 'req_conflict_1',
      retryable: false,
      currentRevision: 9,
    })
  })

  it('reuses a generic mutation key only for an identical unknown-result retry', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('connection lost'))
      .mockResolvedValueOnce(jsonResponse(200, { accepted: true }))

    vi.stubGlobal('fetch', fetchMock)

    const payload = { reason: 'Need another reviewer' }

    await expect(
      workbenchApi.requestCowork(
        'staff-token',
        'clm_generic',
        4,
        payload,
      ),
    ).rejects.toMatchObject({
      code: 'NETWORK_ERROR',
      retryable: true,
    })

    await workbenchApi.requestCowork(
      'staff-token',
      'clm_generic',
      4,
      payload,
    )

    expect(
      fetchMock.mock.calls[0][1].headers['Idempotency-Key'],
    ).toBe(
      fetchMock.mock.calls[1][1].headers['Idempotency-Key'],
    )
  })

  it('uses a new generic mutation key when the payload changes', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('connection lost'))
      .mockResolvedValueOnce(jsonResponse(200, { accepted: true }))

    vi.stubGlobal('fetch', fetchMock)

    await expect(
      workbenchApi.requestCowork(
        'staff-token',
        'clm_generic_payload',
        4,
        { reason: 'First request' },
      ),
    ).rejects.toMatchObject({ code: 'NETWORK_ERROR' })

    await workbenchApi.requestCowork(
      'staff-token',
      'clm_generic_payload',
      4,
      { reason: 'Revised request' },
    )

    expect(
      fetchMock.mock.calls[0][1].headers['Idempotency-Key'],
    ).not.toBe(
      fetchMock.mock.calls[1][1].headers['Idempotency-Key'],
    )
  })
})

describe('workbenchApi external task actions', () => {
  beforeEach(() => {
    clearStoredSession()
    sessionStorage.clear()
    vi.unstubAllGlobals()
  })

  it('submits external review acceptance only through the staff-facing Workbench route', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(201, {
      action: { action_id: 'act_1' },
      revision: 8,
    }))
    vi.stubGlobal('fetch', fetchMock)

    await workbenchApi.acceptExternalTaskReview(
      'staff-token',
      'clm_1',
      'tsk_1',
      7,
      {},
    )

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/workbench/claims/clm_1/external-tasks/tsk_1/accept-review')
    expect(url).not.toContain('/internal/v1/')
    expect(options.method).toBe('POST')
    expect(options.headers.Authorization).toBe('Bearer staff-token')
    expect(options.headers['If-Match']).toBe('7')
    expect(options.headers['Idempotency-Key']).toEqual(expect.any(String))
    expect(options.body).toBe('{}')
  })

  it('reuses the reconciliation idempotency identity after an ambiguous network outcome', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('connection lost'))
      .mockResolvedValueOnce(jsonResponse(200, {
        claim_id: 'clm_1',
        task_id: 'tsk_1',
        revision: 8,
      }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      workbenchApi.reconcileExternalTaskResponse(
        'staff-token',
        'clm_1',
        'tsk_1',
        7,
      ),
    ).rejects.toMatchObject({
      code: 'NETWORK_ERROR',
      retryable: true,
    })

    await workbenchApi.reconcileExternalTaskResponse(
      'staff-token',
      'clm_1',
      'tsk_1',
      7,
    )

    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/workbench/claims/clm_1/external-tasks/tsk_1/reconcile')
    expect(fetchMock.mock.calls[0][0]).not.toContain('/internal/v1/')
    expect(fetchMock.mock.calls[0][1].headers['If-Match']).toBe('7')
    expect(fetchMock.mock.calls[0][1].headers['Idempotency-Key']).toBe(
      fetchMock.mock.calls[1][1].headers['Idempotency-Key'],
    )
    expect(fetchMock.mock.calls[0][1].body).toBeUndefined()
  })
})

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
      .mockResolvedValueOnce(jsonResponse(200, staffMessageResponse(
        'clm_retry', 'ses_retry', 5, 'msg_retry',
      )))
      .mockResolvedValueOnce(jsonResponse(200, staffMessageResponse(
        'clm_retry', 'ses_retry', 6, 'msg_next',
      )))
    vi.stubGlobal('fetch', fetchMock)
    const operation = { message: 'Same staff reply', sessionId: 'ses_retry' }

    await expect(
      workbenchApi.sendMessage('staff-token', 'clm_retry', operation, 4),
    ).rejects.toMatchObject({ code: 'NETWORK_ERROR' })

    // The page may already have refreshed to revision 5 after the
    // ambiguous first response. The logical retry must still replay the
    // original request identity, including its original revision.
    await workbenchApi.sendMessage('staff-token', 'clm_retry', operation, 5)

    const firstKey = fetchMock.mock.calls[0][1].headers['Idempotency-Key']
    const retryKey = fetchMock.mock.calls[1][1].headers['Idempotency-Key']

    expect(retryKey).toBe(firstKey)
    expect(fetchMock.mock.calls[0][1].headers['If-Match']).toBe('4')
    expect(fetchMock.mock.calls[1][1].headers['If-Match']).toBe('4')

    expect(workbenchApi.pendingMessageDelivery('clm_retry', 'ses_retry')).toMatchObject({
      message_id: 'msg_retry',
    })
    expect(
      workbenchApi.confirmMessageDelivery('clm_retry', 'ses_retry', 'msg_other'),
    ).toBeNull()
    expect(workbenchApi.pendingMessageDelivery('clm_retry', 'ses_retry')).toMatchObject({
      message_id: 'msg_retry',
    })
    workbenchApi.confirmMessageDelivery('clm_retry', 'ses_retry', 'msg_retry')
    expect(workbenchApi.pendingMessageDelivery('clm_retry', 'ses_retry')).toBeNull()

    await workbenchApi.sendMessage('staff-token', 'clm_retry', operation, 5)

    const nextOperationKey =
      fetchMock.mock.calls[2][1].headers['Idempotency-Key']

    expect(nextOperationKey).not.toBe(firstKey)
    expect(fetchMock.mock.calls[2][1].headers['If-Match']).toBe('5')
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
      .mockResolvedValueOnce(jsonResponse(200, staffMessageResponse(
        'clm_stale', 'ses_stale', 8, 'msg_stale_retry',
      )))
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
      .mockResolvedValueOnce(jsonResponse(200, staffMessageResponse(
        'clm_identity', 'ses_identity', 5, 'msg_identity',
      )))
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
      .mockResolvedValueOnce(jsonResponse(200, staffMessageResponse(
        'clm_replace', 'ses_replace', 9, 'msg_replace',
      )))
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


describe('workbenchApi Staff Agent draft execution', () => {
  beforeEach(() => {
    clearStoredSession()
    sessionStorage.clear()
    vi.unstubAllGlobals()
  })

  it('sends saved draft identity, fresh revision, payload, and an idempotency key', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(200, {
      claim_id: 'clm_1',
      action_code: 'work_item.update',
      runtime_execution: { resulting_revision: 10 },
    }))
    vi.stubGlobal('fetch', fetchMock)

    const payload = { status: 'in_progress', note: 'Staff confirmed.' }
    await workbenchApi.executeStaffAgentDraft(
      'staff-token',
      'sas_1',
      'sam_1',
      'sad_1',
      9,
      payload,
    )

    expect(fetchMock).toHaveBeenCalledOnce()
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe(
      '/api/v1/workbench/agent/sessions/sas_1/messages/sam_1/drafts/sad_1/execute',
    )
    expect(options.method).toBe('POST')
    expect(options.headers.Authorization).toBe('Bearer staff-token')
    expect(options.headers['If-Match']).toBe('9')
    expect(options.headers['Idempotency-Key']).toEqual(expect.any(String))
    expect(JSON.parse(options.body)).toEqual({
      confirmed: true,
      payload,
    })
  })

  it('replays the original draft operation after an ambiguous result even when the Claim revision advanced', async () => {
    const authoritative = {
      claim_id: 'clm_1',
      action_code: 'work_item.update',
      outcome: 'executed',
      result: {
        action: { action_id: 'wki_1', status: 'in_progress' },
        revision: 10,
      },
      runtime_execution: {
        outcome: 'executed',
        resulting_revision: 10,
        result: {
          action: { action_id: 'wki_1', status: 'in_progress' },
          revision: 10,
        },
      },
    }
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('connection lost'))
      .mockResolvedValueOnce(jsonResponse(200, authoritative))
    vi.stubGlobal('fetch', fetchMock)

    const source = [
      'staff-token',
      'sas_retry',
      'sam_retry',
      'sad_retry',
    ]
    const payload = { status: 'in_progress' }

    await expect(
      workbenchApi.executeStaffAgentDraft(...source, 9, payload),
    ).rejects.toMatchObject({
      code: 'NETWORK_ERROR',
      retryable: true,
    })

    const replay = await workbenchApi.executeStaffAgentDraft(
      ...source,
      10,
      payload,
    )

    expect(replay).toEqual(authoritative)
    expect(fetchMock.mock.calls[1][1].headers['Idempotency-Key']).toBe(
      fetchMock.mock.calls[0][1].headers['Idempotency-Key'],
    )
    expect(fetchMock.mock.calls[0][1].headers['If-Match']).toBe('9')
    expect(fetchMock.mock.calls[1][1].headers['If-Match']).toBe('9')
    expect(fetchMock.mock.calls[1][1].body).toBe(fetchMock.mock.calls[0][1].body)
    expect(sessionStorage.getItem('northwind.workbench.staff-draft-execution-operations.v1')).toBe('{}')
  })
})
