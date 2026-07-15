import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ADMIN_TOKEN_STORAGE_KEY,
  AdminApiError,
  adminFetch,
  clearAdminToken,
  downloadAdminFile,
  getAdminToken,
  requireAdminResponse,
  setAdminToken,
  streamAdminSse,
  subscribeAdminToken,
} from './adminApi'

const fakeSessionStorage = () => {
  const values = new Map()
  return {
    getItem: vi.fn((key) => values.get(key) ?? null),
    setItem: vi.fn((key, value) => values.set(key, String(value))),
    removeItem: vi.fn((key) => values.delete(key)),
  }
}

describe('adminApi', () => {
  beforeEach(() => {
    vi.stubGlobal('sessionStorage', fakeSessionStorage())
    clearAdminToken()
  })

  afterEach(() => {
    clearAdminToken()
    vi.unstubAllGlobals()
  })

  it('keeps the token in sessionStorage and notifies both panels', () => {
    const listener = vi.fn()
    const unsubscribe = subscribeAdminToken(listener)

    setAdminToken('  session-secret  ')

    expect(getAdminToken()).toBe('session-secret')
    expect(sessionStorage.setItem).toHaveBeenCalledWith(ADMIN_TOKEN_STORAGE_KEY, 'session-secret')
    expect(listener).toHaveBeenCalledWith('session-secret')
    unsubscribe()
  })

  it('adds X-Admin-Token without placing the secret in the URL', async () => {
    setAdminToken('header-only-secret')
    const fetchImpl = vi.fn(async () => new Response('{}', {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))

    await adminFetch('/api/waf/events?limit=500', {
      headers: { Accept: 'application/json' },
    }, fetchImpl)

    const [url, init] = fetchImpl.mock.calls[0]
    expect(url).toBe('/api/waf/events?limit=500')
    expect(url).not.toContain('header-only-secret')
    expect(init.headers.get('X-Admin-Token')).toBe('header-only-secret')
    expect(init.headers.get('Accept')).toBe('application/json')
  })

  it('parses named SSE events split across network chunks with an auth header', async () => {
    setAdminToken('sse-secret')
    const encoder = new TextEncoder()
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode('event: waf-event\ndata: {"id":'))
        controller.enqueue(encoder.encode('7}\nid: evt-7\n\n'))
        controller.close()
      },
    })
    const fetchImpl = vi.fn(async (_url, init) => {
      expect(init.headers.get('X-Admin-Token')).toBe('sse-secret')
      expect(init.headers.get('Accept')).toBe('text/event-stream')
      return new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
    })
    const events = []

    await streamAdminSse('/api/waf/events/stream', {
      fetchImpl,
      onEvent: (event) => events.push(event),
    })

    expect(events).toEqual([{ event: 'waf-event', data: '{"id":7}', id: 'evt-7' }])
  })

  it('downloads an authenticated export through a temporary object URL', async () => {
    setAdminToken('export-secret')
    const anchor = { click: vi.fn(), remove: vi.fn(), style: {} }
    const documentRef = {
      createElement: vi.fn(() => anchor),
      body: { appendChild: vi.fn() },
    }
    const urlApi = {
      createObjectURL: vi.fn(() => 'blob:export'),
      revokeObjectURL: vi.fn(),
    }
    const fetchImpl = vi.fn(async (_url, init) => {
      expect(init.headers.get('X-Admin-Token')).toBe('export-secret')
      return new Response('id,status\n1,blocked', { status: 200 })
    })

    await downloadAdminFile('/api/waf/events/export', 'waf.csv', {
      fetchImpl,
      document: documentRef,
      urlApi,
    })

    expect(anchor.href).toBe('blob:export')
    expect(anchor.download).toBe('waf.csv')
    expect(anchor.click).toHaveBeenCalledOnce()
    expect(urlApi.revokeObjectURL).toHaveBeenCalledWith('blob:export')
  })

  it('turns 401 responses into an explicit authentication error', async () => {
    await expect(requireAdminResponse(new Response(null, { status: 401 })))
      .rejects.toMatchObject({ name: 'AdminApiError', status: 401 })
    await expect(requireAdminResponse(new Response(null, { status: 401 })))
      .rejects.toBeInstanceOf(AdminApiError)
  })
})
