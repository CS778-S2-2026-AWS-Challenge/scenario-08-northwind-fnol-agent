import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  applyEvidenceHistoryAction,
  createClaim,
  listEvidenceHistory,
  listClaims,
  requestEvidenceUpload,
  setClaimantAccessToken,
  streamClaimUpdates,
  streamRealtimeEvents,
} from './api.js'


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


function trackedOpenEventStreamResponse(frame, order, label) {
  const encoder = new TextEncoder()
  return new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(frame))
      },
      cancel() {
        order.push(`${label}:cancel`)
      },
    }),
    { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
  )
}


describe('claimant live-update stream', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    setClaimantAccessToken(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    setClaimantAccessToken(null)
  })

  it('parses claimant-safe update frames and authenticates an anonymous session', async () => {
    fetch.mockResolvedValue(eventStreamResponse([
      'retry: 1500\n: connected\n\n',
      'id: 4\nevent: claim.updated\ndata: {"event_id":"4","claim_id":"clm_1",\n',
      'data: "session_id":"ses_1","claim_revision":4,"resources":["claim","messages"]}\n\n',
    ]))
    const received = []

    await streamClaimUpdates({
      claimId: 'clm_1',
      sessionId: 'ses_1',
      afterRevision: 3,
      signal: new AbortController().signal,
      onEvent: async (event) => received.push(event),
    })

    expect(received).toEqual([
      expect.objectContaining({ claim_revision: 4, resources: ['claim', 'messages'] }),
    ])
    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/claims/clm_1/sessions/ses_1/events?after_revision=3',
      expect.objectContaining({
        headers: expect.objectContaining({
          Accept: 'text/event-stream',
          'X-Northwind-Anonymous-Session': expect.any(String),
        }),
      }),
    )
  })

  it('uses the claimant bearer token without exposing it in the stream URL', async () => {
    setClaimantAccessToken('claimant-session-token')
    fetch.mockResolvedValue(eventStreamResponse([': connected\n\n']))

    await streamClaimUpdates({
      claimId: 'clm_2',
      sessionId: 'ses_2',
      afterRevision: 8,
      signal: new AbortController().signal,
      onEvent: vi.fn(),
    })

    const [url, request] = fetch.mock.calls[0]
    expect(url).not.toContain('claimant-session-token')
    expect(request.headers.Authorization).toBe('Bearer claimant-session-token')
    expect(request.headers['X-Northwind-Anonymous-Session']).toBeUndefined()
  })

  it('tracks only opaque durable cursors while preserving legacy revision events', async () => {
    fetch.mockResolvedValue(eventStreamResponse([
      'id: 4\nevent: claim.updated\ndata: {"event_id":"4","claim_revision":4}\n\n',
      'id: eyJldmVudF9pZCI6InJ0ZV8xIn0\nevent: agent.turn.progress\ndata: {"turn_id":"message-1","session_id":"ses_1","stage":"model.waiting","state":"running","ordinal":2}\n\n',
    ]))
    const onCursor = vi.fn()
    const onEvent = vi.fn()

    await streamClaimUpdates({
      claimId: 'clm_1',
      sessionId: 'ses_1',
      afterRevision: 3,
      signal: new AbortController().signal,
      onEvent,
      onCursor,
    })

    expect(onEvent).toHaveBeenCalledTimes(2)
    expect(onCursor).toHaveBeenCalledOnce()
    expect(onCursor).toHaveBeenCalledWith('eyJldmVudF9pZCI6InJ0ZV8xIn0')
  })

  it('does not advance an opaque cursor and cancels the legacy stream when the handler fails', async () => {
    const order = []
    fetch.mockResolvedValue(trackedOpenEventStreamResponse(
      'id: eyJldmVudF9pZCI6InJ0ZV8yIn0\nevent: agent.turn.progress\ndata: {"turn_id":"message-2","session_id":"ses_1","stage":"model.waiting","state":"running","ordinal":2}\n\n',
      order,
      'legacy',
    ))
    const onCursor = vi.fn()
    const handlerFailure = new Error('Authoritative readback failed.')

    await expect(streamClaimUpdates({
      claimId: 'clm_1',
      sessionId: 'ses_1',
      afterRevision: 3,
      signal: new AbortController().signal,
      onEvent: vi.fn(async () => {
        order.push('handler')
        throw handlerFailure
      }),
      onCursor,
    })).rejects.toBe(handlerFailure)

    expect(onCursor).not.toHaveBeenCalled()
    expect(order).toEqual(['handler', 'legacy:cancel'])
  })
})

describe('claim creation contract', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    setClaimantAccessToken(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    setClaimantAccessToken(null)
  })

  it('sends the selected product family to the backend when starting a claim', async () => {
    fetch.mockResolvedValue(new Response(JSON.stringify({ claim: {}, session: {} }), { status: 201 }))

    await createClaim({
      idempotencyKey: 'claim-family-contract',
      incidentType: 'home',
      modelProfileId: 'qwen-local',
    })

    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/claims',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Idempotency-Key': 'claim-family-contract' }),
        body: JSON.stringify({
          channel: 'web_agent',
          locale: 'en-NZ',
          incident_type: 'home',
          model_profile_id: 'qwen-local',
        }),
      }),
    )
  })
})

describe('claimant multiplexed realtime stream', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    setClaimantAccessToken(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    setClaimantAccessToken(null)
  })

  it('parses resource and resync frames from one claimant-scoped stream', async () => {
    fetch.mockResolvedValue(eventStreamResponse([
      ': connected\n\n',
      'id: cursor-2\nevent: resources.changed\ndata: {"event_id":"evt_2","claim_id":"clm_1","claim_revision":2,"resources":["messages"]}\n\n',
      'event: resync_required\ndata: {"reason":"replay_window_exceeded"}\n\n',
    ]))
    const received = []

    await streamRealtimeEvents({
      cursor: 'cursor-1',
      signal: new AbortController().signal,
      onEvent: async (event) => received.push(event),
    })

    expect(received).toEqual([
      {
        type: 'resources.changed',
        cursor: 'cursor-2',
        data: expect.objectContaining({
          event_id: 'evt_2',
          claim_id: 'clm_1',
          resources: ['messages'],
        }),
      },
      {
        type: 'resync_required',
        cursor: null,
        data: { reason: 'replay_window_exceeded' },
      },
    ])
    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/realtime/events?cursor=cursor-1',
      expect.objectContaining({
        headers: expect.objectContaining({
          Accept: 'text/event-stream',
          'X-Northwind-Anonymous-Session': expect.any(String),
        }),
      }),
    )
  })

  it('keeps claimant bearer credentials out of the realtime URL', async () => {
    setClaimantAccessToken('claimant-realtime-token')
    fetch.mockResolvedValue(eventStreamResponse([': connected\n\n']))

    await streamRealtimeEvents({
      cursor: null,
      signal: new AbortController().signal,
      onEvent: vi.fn(),
    })

    const [url, request] = fetch.mock.calls[0]
    expect(url).toBe('/api/v1/realtime/events')
    expect(url).not.toContain('claimant-realtime-token')
    expect(request.headers.Authorization).toBe('Bearer claimant-realtime-token')
    expect(request.headers['X-Northwind-Anonymous-Session']).toBeUndefined()
  })

  it('surfaces an unavailable replay cursor for authoritative resync', async () => {
    fetch.mockResolvedValue(new Response(JSON.stringify({
      error: {
        code: 'INVALID_EVENT_CURSOR',
        message: 'The realtime cursor is no longer available.',
        retryable: true,
      },
    }), {
      status: 409,
      headers: { 'Content-Type': 'application/json' },
    }))

    await expect(streamRealtimeEvents({
      cursor: 'expired-cursor',
      signal: new AbortController().signal,
      onEvent: vi.fn(),
    })).rejects.toMatchObject({
      status: 409,
      code: 'INVALID_EVENT_CURSOR',
      retryable: true,
    })
  })
  it('delivers Agent progress through the multiplexed stream and acknowledges only after handling', async () => {
    fetch.mockResolvedValue(eventStreamResponse([
      'id: cursor-progress\nevent: agent.turn.progress\ndata: {"event_id":"evt_progress","claim_id":"clm_1","session_id":"ses_1","turn_id":"message-1","stage":"model.waiting","state":"running","ordinal":2}\n\n',
    ]))
    const order = []
    const onCursor = vi.fn((cursor) => order.push(`cursor:${cursor}`))

    await streamRealtimeEvents({
      cursor: null,
      signal: new AbortController().signal,
      onEvent: vi.fn(async (event) => {
        expect(event).toMatchObject({
          type: 'agent.turn.progress',
          cursor: 'cursor-progress',
          data: {
            turn_id: 'message-1',
            session_id: 'ses_1',
            stage: 'model.waiting',
          },
        })
        order.push('handler')
      }),
      onCursor,
    })

    expect(order).toEqual(['handler', 'cursor:cursor-progress'])
    expect(onCursor).toHaveBeenCalledWith('cursor-progress')
  })

  it('does not acknowledge a multiplexed cursor when the applicable handler fails', async () => {
    fetch.mockResolvedValue(eventStreamResponse([
      'id: cursor-progress-fail\nevent: agent.turn.progress\ndata: {"event_id":"evt_progress_fail","claim_id":"clm_1","session_id":"ses_1","turn_id":"message-2","stage":"model.waiting","state":"running","ordinal":2}\n\n',
    ]))
    const handlerFailure = new Error('Progress handler failed.')
    const onCursor = vi.fn()

    await expect(streamRealtimeEvents({
      cursor: null,
      signal: new AbortController().signal,
      onEvent: vi.fn().mockRejectedValue(handlerFailure),
      onCursor,
    })).rejects.toBe(handlerFailure)

    expect(onCursor).not.toHaveBeenCalled()
  })

  it('cancels a failed claimant stream before a reconnect can open', async () => {
    const order = []
    const handlerFailure = new Error('Authoritative claimant refetch failed.')

    fetch
      .mockImplementationOnce(async () => {
        order.push('first:fetch')
        return trackedOpenEventStreamResponse(
          'id: cursor-refetch-fail\nevent: resources.changed\ndata: {"event_id":"evt_refetch_fail","claim_id":"clm_1","claim_revision":3,"resources":["claim"]}\n\n',
          order,
          'first',
        )
      })
      .mockImplementationOnce(async () => {
        order.push('second:fetch')
        return eventStreamResponse([': connected\n\n'])
      })

    await expect(streamRealtimeEvents({
      cursor: null,
      signal: new AbortController().signal,
      onEvent: vi.fn(async () => {
        order.push('handler')
        throw handlerFailure
      }),
    })).rejects.toBe(handlerFailure)

    order.push('reconnect')

    await streamRealtimeEvents({
      cursor: null,
      signal: new AbortController().signal,
      onEvent: vi.fn(),
    })

    expect(order).toEqual([
      'first:fetch',
      'handler',
      'first:cancel',
      'reconnect',
      'second:fetch',
    ])
  })

})


describe('Evidence history contract', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    setClaimantAccessToken('claimant-session-token')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    setClaimantAccessToken(null)
  })

  it('uses the account-scoped route, opaque cursor, bearer identity, and abort signal', async () => {
    const controller = new AbortController()
    fetch.mockResolvedValue(new Response(JSON.stringify({
      items: [],
      page: { next_cursor: null },
    }), { status: 200 }))

    await listEvidenceHistory({ cursor: 'opaque-cursor', limit: 10, signal: controller.signal })

    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/evidence?limit=10&cursor=opaque-cursor',
      expect.objectContaining({
        signal: controller.signal,
        headers: expect.objectContaining({ Authorization: 'Bearer claimant-session-token' }),
      }),
    )
  })

  it('posts a revision-checked governed Evidence action with claimant references', async () => {
    fetch.mockResolvedValue(new Response(JSON.stringify({ status: 'succeeded' }), { status: 200 }))
    const controller = new AbortController()

    await applyEvidenceHistoryAction({
      claimId: 'clm_target',
      evidenceId: 'evd_source',
      action: 'reuse',
      sourceClaimId: 'clm_source',
      revision: 7,
      proposalRef: 'proposal-1',
      confirmationRef: 'confirmation-1',
      idempotencyKey: 'evidence-action-1',
      signal: controller.signal,
    })

    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/claims/clm_target/evidence/evd_source/reuse',
      expect.objectContaining({
        method: 'POST',
        signal: controller.signal,
        headers: expect.objectContaining({
          Authorization: 'Bearer claimant-session-token',
          'Idempotency-Key': 'evidence-action-1',
          'If-Match': '7',
        }),
        body: JSON.stringify({
          source_claim_id: 'clm_source',
          proposal_ref: 'proposal-1',
          confirmation_ref: 'confirmation-1',
        }),
      }),
    )
  })
})

describe('Evidence upload contract', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    setClaimantAccessToken('claimant-session-token')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    setClaimantAccessToken(null)
  })

  it('targets the original Evidence requirement when its identity is supplied', async () => {
    fetch.mockResolvedValue(new Response(JSON.stringify({ evidence_id: 'evd_required' }), { status: 201 }))
    const file = new File(['quote'], 'repair-quote.pdf', { type: 'application/pdf' })

    await requestEvidenceUpload({
      claimId: 'clm_1',
      revision: 7,
      file,
      kind: 'repair_quote',
      evidenceId: 'evd_required',
      idempotencyKey: 'requirement-upload',
    })

    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/claims/clm_1/evidence/uploads',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          'Idempotency-Key': 'requirement-upload',
          'If-Match': '7',
        }),
        body: JSON.stringify({
          evidence_id: 'evd_required',
          kind: 'repair_quote',
          original_filename: 'repair-quote.pdf',
          media_type: 'application/pdf',
          size_bytes: file.size,
        }),
      }),
    )
  })
})

describe('Claim history contract', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    setClaimantAccessToken('claimant-session-token')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    setClaimantAccessToken(null)
  })

  it('passes the opaque page cursor and cancellation signal to the claimant Claim list', async () => {
    const controller = new AbortController()
    fetch.mockResolvedValue(new Response(JSON.stringify({
      items: [],
      page: { next_cursor: null },
    }), { status: 200 }))

    await listClaims({ cursor: 'claim-cursor', limit: 10, signal: controller.signal })

    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/claims?limit=10&cursor=claim-cursor',
      expect.objectContaining({
        signal: controller.signal,
        headers: expect.objectContaining({ Authorization: 'Bearer claimant-session-token' }),
      }),
    )
  })
})
