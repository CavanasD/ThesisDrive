import { describe, expect, it, vi } from 'vitest'
import { MemoryTransferStore, TransferClient } from './transferClient'

const makeFile = (content, name = 'demo.bin') => {
  const blob = new Blob([content], { type: 'application/octet-stream' })
  Object.defineProperties(blob, {
    name: { value: name },
    lastModified: { value: 1234 },
  })
  return blob
}

const response = (status, offset, data = null) => {
  const headers = new Headers({ 'Upload-Offset': String(offset) })
  if (data) headers.set('Content-Type', 'application/json')
  return new Response(data ? JSON.stringify(data) : null, { status, headers })
}

const controlClient = (overrides = {}) => {
  const statuses = [...(overrides.statuses || [{ status: 'completed' }])]
  let statusIndex = 0
  return {
    request: vi.fn(async (action) => {
      if (action === 'prepare_upload') {
        return {
          code: 200,
          data: {
            transfer_id: 'transfer-1',
            upload_url: '/api/v1/transfers/transfer-1',
            ticket: 'upload-ticket',
            chunk_size: 4,
            offset: 0,
            ...overrides.upload,
          },
        }
      }
      if (action === 'prepare_download') {
        return {
          code: 200,
          data: {
            transferId: 'download-1',
            download_url: '/api/v1/transfers/download-1/content',
            token: 'download ticket',
            ...overrides.download,
          },
        }
      }
      if (action === 'get_transfer_status') {
        overrides.onStatus?.()
        const status = statuses[Math.min(statusIndex, statuses.length - 1)]
        statusIndex += 1
        return { code: 200, data: status }
      }
      return { code: 404, message: `unexpected action: ${action}` }
    }),
  }
}

describe('TransferClient', () => {
  it('uploads File.slice chunks with Content-Range and persists completion', async () => {
    const requests = []
    const fetchImpl = vi.fn(async (url, options) => {
      requests.push({ url, options })
      const match = options.headers['Content-Range'].match(/bytes (\d+)-(\d+)\/(\d+)/)
      const nextOffset = Number(match[2]) + 1
      return nextOffset === Number(match[3])
        ? response(201, nextOffset, { status: 'completed' })
        : response(204, nextOffset)
    })
    const store = new MemoryTransferStore()
    const client = new TransferClient({ controlClient: controlClient(), fetchImpl, store })
    client.setCapabilities({ http_transfer: true, resume_upload: true })
    const progress = []

    await client.uploadFile('task-1', makeFile('abcdefghij'), {
      auth: { username: 'alice', token: 'core-token' },
      onProgress: ({ loaded }) => progress.push(loaded),
    })

    expect(requests.map(({ options }) => options.headers['Content-Range'])).toEqual([
      'bytes 0-3/10',
      'bytes 4-7/10',
      'bytes 8-9/10',
    ])
    expect(requests[0].options.headers.Authorization).toBe('Bearer upload-ticket')
    expect(requests[0].options.headers['Idempotency-Key']).toBe('transfer-1:0:4')
    expect(progress).toEqual([4, 8, 10])
    expect(await store.get('task-1')).toMatchObject({ offset: 10, status: 'completed' })
  })

  it('retries transient chunk errors with the same idempotency key', async () => {
    let attempt = 0
    const fetchImpl = vi.fn(async () => {
      attempt += 1
      return attempt === 1 ? response(503, 0) : response(201, 3, { status: 'completed' })
    })
    const client = new TransferClient({
      controlClient: controlClient({ upload: { chunk_size: 3 } }),
      fetchImpl,
      store: new MemoryTransferStore(),
      retryBaseMs: 1,
    })

    await client.uploadFile('task-2', makeFile('abc'))
    expect(fetchImpl).toHaveBeenCalledTimes(2)
    expect(fetchImpl.mock.calls[0][1].headers['Idempotency-Key'])
      .toBe(fetchImpl.mock.calls[1][1].headers['Idempotency-Key'])
  })

  it('waits for Core pending/running states before reporting business completion', async () => {
    const control = controlClient({
      statuses: [{ status: 'pending' }, { status: 'running' }, { status: 'completed' }],
    })
    const store = new MemoryTransferStore()
    const client = new TransferClient({
      controlClient: control,
      fetchImpl: vi.fn(async () => response(201, 3, { status: 'completed' })),
      store,
      finalizationTimeoutMs: 100,
      finalizationPollBaseMs: 1,
      finalizationPollMaxMs: 2,
    })

    const result = await client.uploadFile('task-core', makeFile('abc'))

    expect(control.request.mock.calls.map(([action]) => action)).toEqual([
      'prepare_upload',
      'get_transfer_status',
      'get_transfer_status',
      'get_transfer_status',
    ])
    expect(result.data.status).toBe('completed')
    expect(await store.get('task-core')).toMatchObject({ status: 'completed' })
  })

  it('surfaces a clear error when Core rejects the completed data-plane upload', async () => {
    const store = new MemoryTransferStore()
    const client = new TransferClient({
      controlClient: controlClient({
        statuses: [{ status: 'failed', error: 'quota_exceeded' }],
      }),
      fetchImpl: vi.fn(async () => response(201, 3, { status: 'completed' })),
      store,
    })

    await expect(client.uploadFile('task-rejected', makeFile('abc')))
      .rejects.toThrow('上传业务确认失败：quota_exceeded')
    expect(await store.get('task-rejected')).toMatchObject({ status: 'failed' })
  })

  it('times out instead of treating a non-terminal Core status as completed', async () => {
    const client = new TransferClient({
      controlClient: controlClient({ statuses: [{ status: 'running' }] }),
      fetchImpl: vi.fn(async () => response(201, 3, { status: 'completed' })),
      store: new MemoryTransferStore(),
      finalizationTimeoutMs: 5,
      finalizationPollBaseMs: 1,
      finalizationPollMaxMs: 2,
    })

    await expect(client.uploadFile('task-timeout', makeFile('abc')))
      .rejects.toThrow('等待上传业务确认超时（任务 task-timeout）')
  })

  it('aborts while waiting for Core finalization', async () => {
    const controller = new AbortController()
    const client = new TransferClient({
      controlClient: controlClient({
        statuses: [{ status: 'pending' }],
        onStatus: () => controller.abort(new DOMException('cancelled', 'AbortError')),
      }),
      fetchImpl: vi.fn(async () => response(201, 3, { status: 'completed' })),
      store: new MemoryTransferStore(),
    })

    await expect(client.uploadFile('task-abort', makeFile('abc'), { signal: controller.signal }))
      .rejects.toMatchObject({ name: 'AbortError' })
  })

  it('can be paused while waiting for Core finalization', async () => {
    let client
    const store = new MemoryTransferStore()
    const control = controlClient({
      statuses: [{ status: 'running' }],
      onStatus: () => client.pause('task-pause'),
    })
    client = new TransferClient({
      controlClient: control,
      fetchImpl: vi.fn(async () => response(201, 3, { status: 'completed' })),
      store,
    })

    await expect(client.uploadFile('task-pause', makeFile('abc')))
      .rejects.toMatchObject({ name: 'TransferPausedError', taskId: 'task-pause' })
    expect(await store.get('task-pause')).toMatchObject({ status: 'paused' })
  })

  it('uses the server Upload-Offset to resume rather than re-upload committed bytes', async () => {
    const fetchImpl = vi.fn(async (_url, options) => response(201, 10, { status: 'completed' }))
    const client = new TransferClient({
      controlClient: controlClient({ upload: { chunk_size: 4, offset: 8 } }),
      fetchImpl,
      store: new MemoryTransferStore(),
    })

    await client.uploadFile('task-3', makeFile('abcdefghij'))
    expect(fetchImpl.mock.calls[0][1].headers['Content-Range']).toBe('bytes 8-9/10')
  })

  it('completes an empty file with the data-plane zero-length Content-Range', async () => {
    const fetchImpl = vi.fn(async () => response(201, 0, { status: 'completed' }))
    const client = new TransferClient({
      controlClient: controlClient(),
      fetchImpl,
      store: new MemoryTransferStore(),
    })

    await client.uploadFile('task-empty', makeFile(''))
    expect(fetchImpl.mock.calls[0][1].headers['Content-Range']).toBe('bytes */0')
    expect(fetchImpl.mock.calls[0][1].body.size).toBe(0)
  })

  it('probes the data plane with HEAD when an IndexedDB session is resumed', async () => {
    const store = new MemoryTransferStore()
    await store.put({ taskId: 'task-5', fingerprint: 'demo.bin:10:1234', offset: 4 })
    const fetchImpl = vi.fn(async (_url, options) => {
      if (options.method === 'HEAD') return response(200, 8)
      return response(201, 10, { status: 'completed' })
    })
    const client = new TransferClient({
      controlClient: controlClient({ upload: { offset: undefined } }),
      fetchImpl,
      store,
    })
    client.setCapabilities({ http_transfer: true, resume_upload: true })

    await client.resumeUpload('task-5', makeFile('abcdefghij'))
    expect(fetchImpl.mock.calls[0][1].method).toBe('HEAD')
    expect(fetchImpl.mock.calls[1][1].headers['Content-Range']).toBe('bytes 8-9/10')
  })

  it('retries a failed upload by probing the committed offset before sending more bytes', async () => {
    let failFirstRequest = true
    const fetchImpl = vi.fn(async (_url, options) => {
      if (options.method === 'HEAD') return response(200, 4)
      if (failFirstRequest) {
        failFirstRequest = false
        const error = new Error('network response lost')
        error.retryable = false
        throw error
      }
      return response(201, 8, { status: 'completed' })
    })
    const control = controlClient()
    const client = new TransferClient({
      controlClient: control,
      fetchImpl,
      store: new MemoryTransferStore(),
    })
    client.setCapabilities({ http_transfer: true, resume_upload: true })
    const file = makeFile('abcdefgh')

    await expect(client.uploadFile('task-retry', file)).rejects.toThrow('network response lost')
    await client.resumeUpload('task-retry', file)

    expect(fetchImpl.mock.calls.map(([, options]) => options.method)).toEqual(['PUT', 'HEAD', 'PUT'])
    expect(fetchImpl.mock.calls[2][1].headers['Content-Range']).toBe('bytes 4-7/8')
    expect(control.request.mock.calls.filter(([action]) => action === 'prepare_upload')).toHaveLength(2)
  })

  it('builds a native streaming URL with the short-lived download ticket', async () => {
    const client = new TransferClient({
      controlClient: controlClient(),
      fetchImpl: vi.fn(),
      store: new MemoryTransferStore(),
    })

    const result = await client.nativeDownload('task-4', 'demo.bin', { trigger: false })
    expect(result.url).toBe('/api/v1/transfers/download-1/content?ticket=download%20ticket')
  })

  it('streams a download from an already prepared anonymous share session', async () => {
    const client = new TransferClient({
      controlClient: controlClient(),
      fetchImpl: vi.fn(),
      store: new MemoryTransferStore(),
    })

    const result = await client.nativeDownloadPrepared({
      task_id: 'share-task',
      download_url: '/api/v1/transfers/share-task/content',
      ticket: 'share ticket',
    }, '共享文件', { trigger: false })

    expect(result.url).toBe('/api/v1/transfers/share-task/content?ticket=share%20ticket')
  })
})
