export const DEFAULT_TRANSFER_CHUNK_SIZE = 8 * 1024 * 1024

const TRANSFER_DB_NAME = 'thesis-drive-transfers'
const TRANSFER_STORE_NAME = 'sessions'
const COMPLETE_UPLOAD_STATUSES = new Set([200, 201, 204, 308])
const DEFAULT_FINALIZATION_TIMEOUT_MS = 30_000
const DEFAULT_FINALIZATION_POLL_BASE_MS = 250
const DEFAULT_FINALIZATION_POLL_MAX_MS = 2_000

const abortReason = (signal) =>
  signal?.reason || new DOMException('Aborted', 'AbortError')

const wait = (milliseconds, signal) =>
  new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortReason(signal))
      return
    }
    const finish = (callback, value) => {
      signal?.removeEventListener('abort', onAbort)
      callback(value)
    }
    const timer = setTimeout(() => finish(resolve), milliseconds)
    const onAbort = () => {
      clearTimeout(timer)
      finish(reject, abortReason(signal))
    }
    signal?.addEventListener('abort', onAbort, { once: true })
  })

const withAbort = (promise, signal) => {
  if (!signal) return promise
  if (signal.aborted) return Promise.reject(abortReason(signal))
  return new Promise((resolve, reject) => {
    const settle = (callback, value) => {
      signal.removeEventListener('abort', onAbort)
      callback(value)
    }
    const onAbort = () => settle(reject, abortReason(signal))
    signal.addEventListener('abort', onAbort, { once: true })
    Promise.resolve(promise).then(
      (value) => settle(resolve, value),
      (error) => settle(reject, error),
    )
  })
}

const fileFingerprint = (file) =>
  `${file.name || 'blob'}:${file.size}:${file.lastModified || 0}`

const firstDefined = (source, names, fallback = undefined) => {
  for (const name of names) {
    if (source?.[name] !== undefined && source[name] !== null) return source[name]
  }
  return fallback
}

const positiveInteger = (value, fallback) => {
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : fallback
}

const parseOffset = (response, payload, fallback) => {
  const direct = response.headers.get('Upload-Offset')
    || response.headers.get('X-Upload-Offset')
    || firstDefined(payload, ['offset', 'upload_offset', 'uploaded_bytes'])
  const parsed = Number(direct)
  if (Number.isSafeInteger(parsed) && parsed >= 0) return parsed

  const range = response.headers.get('Range')
  const match = range?.match(/bytes=0-(\d+)/i)
  return match ? Number(match[1]) + 1 : fallback
}

const jsonOrNull = async (response) => {
  const contentType = response.headers.get('Content-Type') || ''
  if (!contentType.includes('json')) return null
  try {
    return await response.json()
  } catch {
    return null
  }
}

const sha256Hex = async (blob) => {
  if (!globalThis.crypto?.subtle) return ''
  const digest = await globalThis.crypto.subtle.digest('SHA-256', await blob.arrayBuffer())
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

export class TransferPausedError extends Error {
  constructor(taskId) {
    super(`传输已暂停: ${taskId}`)
    this.name = 'TransferPausedError'
    this.taskId = taskId
  }
}

export class MemoryTransferStore {
  constructor() {
    this.sessions = new Map()
  }

  async get(taskId) {
    const session = this.sessions.get(taskId)
    return session ? { ...session } : null
  }

  async put(session) {
    this.sessions.set(session.taskId, { ...session })
    return session
  }

  async delete(taskId) {
    this.sessions.delete(taskId)
  }

  async list() {
    return Array.from(this.sessions.values(), (session) => ({ ...session }))
  }
}

export class IndexedDbTransferStore {
  constructor(indexedDb = globalThis.indexedDB) {
    this.indexedDb = indexedDb
    this.fallback = new MemoryTransferStore()
    this.databasePromise = null
  }

  async database() {
    if (!this.indexedDb) return null
    if (!this.databasePromise) {
      this.databasePromise = new Promise((resolve, reject) => {
        const request = this.indexedDb.open(TRANSFER_DB_NAME, 1)
        request.onupgradeneeded = () => {
          if (!request.result.objectStoreNames.contains(TRANSFER_STORE_NAME)) {
            request.result.createObjectStore(TRANSFER_STORE_NAME, { keyPath: 'taskId' })
          }
        }
        request.onsuccess = () => resolve(request.result)
        request.onerror = () => reject(request.error)
      }).catch(() => null)
    }
    return this.databasePromise
  }

  async run(mode, operation, fallback) {
    const database = await this.database()
    if (!database) return fallback()
    return new Promise((resolve, reject) => {
      const transaction = database.transaction(TRANSFER_STORE_NAME, mode)
      const request = operation(transaction.objectStore(TRANSFER_STORE_NAME))
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
  }

  get(taskId) {
    return this.run('readonly', (store) => store.get(taskId), () => this.fallback.get(taskId))
  }

  put(session) {
    return this.run('readwrite', (store) => store.put(session), () => this.fallback.put(session))
  }

  delete(taskId) {
    return this.run('readwrite', (store) => store.delete(taskId), () => this.fallback.delete(taskId))
  }

  list() {
    return this.run('readonly', (store) => store.getAll(), () => this.fallback.list())
  }
}

export class TransferClient {
  constructor(options = {}) {
    if (!options.controlClient) throw new Error('TransferClient 需要 controlClient')
    this.controlClient = options.controlClient
    this.fetch = options.fetchImpl || globalThis.fetch?.bind(globalThis)
    this.store = options.store || new IndexedDbTransferStore()
    this.defaultChunkSize = positiveInteger(options.chunkSize, DEFAULT_TRANSFER_CHUNK_SIZE)
    this.maxRetries = Number.isSafeInteger(options.maxRetries) ? options.maxRetries : 3
    this.retryBaseMs = positiveInteger(options.retryBaseMs, 250)
    this.finalizationTimeoutMs = positiveInteger(
      options.finalizationTimeoutMs,
      DEFAULT_FINALIZATION_TIMEOUT_MS,
    )
    this.finalizationPollBaseMs = positiveInteger(
      options.finalizationPollBaseMs,
      DEFAULT_FINALIZATION_POLL_BASE_MS,
    )
    this.finalizationPollMaxMs = positiveInteger(
      options.finalizationPollMaxMs,
      DEFAULT_FINALIZATION_POLL_MAX_MS,
    )
    this.capabilities = Object.freeze({})
    this.activeUploads = new Map()
  }

  setCapabilities(capabilities) {
    const normalized = Array.isArray(capabilities)
      ? Object.fromEntries(capabilities.map((name) => [name, true]))
      : capabilities && typeof capabilities === 'object'
        ? { ...capabilities }
        : {}
    this.capabilities = Object.freeze(normalized)
  }

  supportsHttpTransfer() {
    return this.capabilities.http_transfer === true
  }

  supportsResumeUpload() {
    return this.supportsHttpTransfer() && this.capabilities.resume_upload === true
  }

  async requestControl(action, data, auth) {
    const response = await this.controlClient.request(action, data, auth)
    if (!response || Number(response.code) >= 400) {
      throw new Error(response?.message || `${action} 失败`)
    }
    return response.data || {}
  }

  async prepareUpload(taskId, file, auth = null) {
    const data = await this.requestControl('prepare_upload', {
      task_id: taskId,
      filename: file.name || 'blob',
      size: file.size,
      content_type: file.type || 'application/octet-stream',
    }, auth)

    const previous = await this.store.get(taskId)
    const fingerprint = fileFingerprint(file)
    const serverOffset = firstDefined(data, ['offset', 'upload_offset', 'uploaded_bytes'])
    const session = {
      taskId,
      transferId: String(firstDefined(data, ['transfer_id', 'transferId', 'task_id'], taskId)),
      uploadUrl: firstDefined(data, ['upload_url', 'url']),
      completeUrl: firstDefined(data, ['complete_url', 'completeUrl'], ''),
      ticket: firstDefined(data, ['ticket', 'token'], ''),
      chunkSize: positiveInteger(firstDefined(data, ['chunk_size', 'chunkSize']), this.defaultChunkSize),
      offset: serverOffset === undefined && previous?.fingerprint === fingerprint
        ? Number(previous.offset || 0)
        : Math.max(0, Number(serverOffset || 0)),
      fingerprint,
      size: file.size,
      status: 'pending',
      updatedAt: Date.now(),
      needsProbe: this.supportsResumeUpload() && previous?.fingerprint === fingerprint,
    }
    if (!session.uploadUrl) throw new Error('prepare_upload 未返回 upload_url')
    await this.store.put(session)
    return session
  }

  async prepareDownload(taskId, auth = null) {
    const data = await this.requestControl('prepare_download', { task_id: taskId }, auth)
    const session = {
      taskId,
      transferId: String(firstDefined(data, ['transfer_id', 'transferId', 'task_id'], taskId)),
      downloadUrl: firstDefined(data, ['download_url', 'url']),
      ticket: firstDefined(data, ['ticket', 'token'], ''),
      size: Number(firstDefined(data, ['size', 'file_size'], 0)),
      sha256: String(firstDefined(data, ['sha256'], '')),
    }
    if (!session.downloadUrl) throw new Error('prepare_download 未返回 download_url')
    return session
  }

  getTransferStatus(taskId, auth = null) {
    return this.requestControl('get_transfer_status', { task_id: taskId }, auth)
  }

  pause(taskId) {
    const active = this.activeUploads.get(taskId)
    if (!active) return false
    active.paused = true
    active.controller.abort(new TransferPausedError(taskId))
    return true
  }

  resumeUpload(taskId, file, options = {}) {
    return this.uploadFile(taskId, file, options)
  }

  listPersistedTransfers() {
    return this.store.list()
  }

  async uploadFile(taskId, file, options = {}) {
    if (!this.fetch) throw new Error('当前环境不支持 fetch')
    const session = await this.prepareUpload(taskId, file, options.auth)
    const controller = new AbortController()
    const active = { controller, paused: false }
    this.activeUploads.set(taskId, active)

    const abortFromCaller = () => controller.abort(options.signal.reason)
    if (options.signal?.aborted) {
      controller.abort(options.signal.reason)
    } else {
      options.signal?.addEventListener('abort', abortFromCaller, { once: true })
    }

    try {
      session.status = 'running'
      await this.store.put(session)
      if (session.needsProbe) {
        session.offset = await this.probeUploadOffset(session, controller.signal)
      }
      let offset = Math.min(session.offset, file.size)

      if (file.size === 0) {
        await this.sendChunk(session, file.slice(0, 0), 0, 0, 0, controller.signal)
        options.onProgress?.({ loaded: 0, total: 0, taskId })
      }

      while (offset < file.size) {
        const endExclusive = Math.min(offset + session.chunkSize, file.size)
        const chunk = file.slice(offset, endExclusive)
        const nextOffset = await this.sendChunk(session, chunk, offset, endExclusive, file.size, controller.signal)
        if (nextOffset <= offset) throw new Error('上传服务未推进 Upload-Offset')
        offset = Math.min(nextOffset, file.size)
        session.offset = offset
        session.updatedAt = Date.now()
        await this.store.put(session)
        options.onProgress?.({ loaded: offset, total: file.size, taskId })
      }

      if (session.completeUrl) await this.completeUpload(session, controller.signal)
      session.status = 'finalizing'
      session.updatedAt = Date.now()
      await this.store.put(session)
      const finalStatus = await this.waitForUploadCompletion(
        taskId,
        options.auth,
        controller.signal,
        options.finalizationTimeoutMs,
      )
      session.status = 'completed'
      session.updatedAt = Date.now()
      await this.store.put(session)
      return {
        code: 201,
        data: {
          ...finalStatus,
          task_id: taskId,
          transfer_id: session.transferId,
          status: 'completed',
        },
      }
    } catch (error) {
      session.status = active.paused ? 'paused' : 'failed'
      session.updatedAt = Date.now()
      await this.store.put(session)
      if (active.paused) throw new TransferPausedError(taskId)
      throw error
    } finally {
      options.signal?.removeEventListener('abort', abortFromCaller)
      this.activeUploads.delete(taskId)
    }
  }

  async waitForUploadCompletion(taskId, auth, signal, timeoutOverride) {
    const timeoutMs = positiveInteger(timeoutOverride, this.finalizationTimeoutMs)
    const deadline = Date.now() + timeoutMs
    let pollDelayMs = this.finalizationPollBaseMs
    let firstPoll = true

    while (true) {
      if (signal?.aborted) throw abortReason(signal)
      if (!firstPoll && Date.now() >= deadline) {
        throw new Error(`等待上传业务确认超时（任务 ${taskId}）`)
      }
      firstPoll = false

      const result = await withAbort(this.getTransferStatus(taskId, auth), signal)
      const status = String(result?.status || '').toLowerCase()
      if (status === 'completed') return result
      if (status === 'failed') {
        const reason = result?.error || result?.message || 'Core 拒绝了上传'
        throw new Error(`上传业务确认失败：${reason}`)
      }

      const remainingMs = deadline - Date.now()
      if (remainingMs <= 0) {
        throw new Error(`等待上传业务确认超时（任务 ${taskId}）`)
      }
      await wait(Math.min(pollDelayMs, remainingMs), signal)
      pollDelayMs = Math.min(pollDelayMs * 2, this.finalizationPollMaxMs)
    }
  }

  async sendChunk(session, chunk, start, endExclusive, total, signal) {
    const chunkSha256 = await sha256Hex(chunk)
    let lastError

    for (let attempt = 0; attempt <= this.maxRetries; attempt += 1) {
      try {
        const headers = {
          'Content-Type': 'application/octet-stream',
          'Content-Range': total === 0 ? 'bytes */0' : `bytes ${start}-${endExclusive - 1}/${total}`,
          'Idempotency-Key': `${session.transferId}:${start}:${endExclusive}`,
        }
        if (session.ticket) headers.Authorization = `Bearer ${session.ticket}`
        if (chunkSha256) headers['X-Chunk-SHA256'] = chunkSha256

        const response = await this.fetch(session.uploadUrl, {
          method: 'PUT',
          headers,
          body: chunk,
          signal,
        })
        const payload = await jsonOrNull(response)
        if (!COMPLETE_UPLOAD_STATUSES.has(response.status)) {
          const error = new Error(payload?.message || `上传分块失败: HTTP ${response.status}`)
          error.retryable = response.status === 429 || response.status >= 500
          throw error
        }
        return parseOffset(response, payload, endExclusive)
      } catch (error) {
        if (signal.aborted) throw signal.reason || error
        lastError = error
        const retryable = error.retryable !== false
        if (!retryable || attempt >= this.maxRetries) break
        await wait(this.retryBaseMs * (2 ** attempt), signal)
      }
    }
    throw lastError
  }

  async probeUploadOffset(session, signal) {
    const headers = session.ticket ? { Authorization: `Bearer ${session.ticket}` } : {}
    const response = await this.fetch(session.uploadUrl, { method: 'HEAD', headers, signal })
    if (!response.ok) throw new Error(`查询续传位置失败: HTTP ${response.status}`)
    return parseOffset(response, null, session.offset)
  }

  async completeUpload(session, signal) {
    const headers = session.ticket ? { Authorization: `Bearer ${session.ticket}` } : {}
    const response = await this.fetch(session.completeUrl, { method: 'POST', headers, signal })
    if (!response.ok) throw new Error(`确认上传失败: HTTP ${response.status}`)
  }

  async nativeDownload(taskId, filename, options = {}) {
    const session = await this.prepareDownload(taskId, options.auth)
    return this.nativeDownloadPrepared(session, filename, options)
  }

  async nativeDownloadPrepared(session, filename, options = {}) {
    if (!session?.downloadUrl && !session?.download_url) {
      throw new Error('下载会话未返回 download_url')
    }
    const normalized = {
      ...session,
      downloadUrl: session.downloadUrl || session.download_url,
      ticket: session.ticket || session.token || '',
    }
    let url = normalized.downloadUrl
    if (normalized.ticket && !/[?&]ticket=/.test(url)) {
      url += `${url.includes('?') ? '&' : '?'}ticket=${encodeURIComponent(normalized.ticket)}`
    }

    if (options.trigger !== false) {
      const documentRef = options.document || globalThis.document
      if (!documentRef) throw new Error('当前环境无法触发浏览器下载')
      const anchor = documentRef.createElement('a')
      anchor.href = url
      anchor.download = filename || ''
      anchor.rel = 'noopener'
      anchor.referrerPolicy = 'no-referrer'
      anchor.style.display = 'none'
      documentRef.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
    }

    return { ...normalized, url }
  }
}
