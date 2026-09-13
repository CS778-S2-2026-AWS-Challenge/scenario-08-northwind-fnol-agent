import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createClaim, setClaimantAccessToken, streamClaimUpdates } from './api.js'


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
