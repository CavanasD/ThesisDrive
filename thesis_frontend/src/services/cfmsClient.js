const FRAME_TYPE_PROCESS = 0
const FRAME_TYPE_CONCLUSION = 1

const encoder = new TextEncoder()
const decoder = new TextDecoder()

const nowSeconds = () => Date.now() / 1000

const randomNonce = () => {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

const base64ToBytes = (base64) => {
  const raw = atob(base64)
  const out = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i += 1) {
    out[i] = raw.charCodeAt(i)
  }
  return out
}

const sha256Hex = async (bytes) => {
  const hashBuffer = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(hashBuffer), (b) => b.toString(16).padStart(2, '0')).join('')
}

const toUtf8 = (bytes) => decoder.decode(bytes)

const parseMaybeJson = (bytes) => {
  try {
    return JSON.parse(toUtf8(bytes))
  } catch {
    return null
  }
}

export class CfmsClient {
  constructor(options = {}) {
    this.url = options.url || 'wss://localhost:5104'
    this.onServerEvent = options.onServerEvent || (() => {})
    this.onConnectionState = options.onConnectionState || (() => {})
    this.ws = null
    this.connected = false

    this.nextFrameId = 1
    this.streams = new Map()
    this.pendingServerEvents = []
    this.onWafBlock = options.onWafBlock || null
  }

  setUrl(url) {
    this.url = url
  }

  connect() {
    if (this.connected && this.ws) {
      return Promise.resolve()
    }

    return new Promise((resolve, reject) => {
      const ws = new WebSocket(this.url)
      ws.binaryType = 'arraybuffer'

      ws.onopen = () => {
        this.ws = ws
        this.connected = true
        this.onConnectionState({ connected: true })
        resolve()
      }

      ws.onclose = () => {
        this.connected = false
        this.onConnectionState({ connected: false })
      }

      ws.onerror = () => {
        reject(
          new Error(
            'WebSocket 连接失败。若是本地自签证书，请先在浏览器中信任该证书后再连接。',
          ),
        )
      }

      ws.onmessage = async (event) => {
        try {
          const arrayBuffer =
            event.data instanceof ArrayBuffer
              ? event.data
              : await event.data.arrayBuffer()
          this.handleIncomingFrame(arrayBuffer)
        } catch {
          // Ignore malformed frames.
        }
      }
    })
  }

  disconnect() {
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
    this.connected = false
    this.onConnectionState({ connected: false })
  }

  getNextFrameId() {
    const id = this.nextFrameId
    this.nextFrameId += 2
    return id
  }

  ensureStream(frameId) {
    if (!this.streams.has(frameId)) {
      this.streams.set(frameId, { queue: [], waiters: [] })
    }
    return this.streams.get(frameId)
  }

  releaseStream(frameId) {
    this.streams.delete(frameId)
  }

  handleIncomingFrame(buffer) {
    if (!(buffer instanceof ArrayBuffer) || buffer.byteLength < 5) {
      return
    }

    const view = new DataView(buffer)
    const frameId = view.getUint32(0, false)
    const frameType = view.getUint8(4)
    const payload = new Uint8Array(buffer.slice(5))

    const stream = this.ensureStream(frameId)
    const frame = { frameId, frameType, payload }

    if (stream.waiters.length > 0) {
      const waiter = stream.waiters.shift()
      waiter(frame)
    } else {
      stream.queue.push(frame)
    }

    if (frameId % 2 === 0) {
      const serverEvent = parseMaybeJson(payload)
      if (serverEvent?.event) {
        this.pendingServerEvents.push(serverEvent)
        this.onServerEvent(serverEvent)
      }
    }

    if (frameType === FRAME_TYPE_CONCLUSION) {
      const parsed = parseMaybeJson(payload)
      if (parsed?.waf === true && parsed?.code === 403) {
        if (typeof this.onWafBlock === 'function') this.onWafBlock(parsed.data)
      }
    }
  }

  waitFrame(frameId, timeoutMs = 20000) {
    const stream = this.ensureStream(frameId)

    if (stream.queue.length > 0) {
      return Promise.resolve(stream.queue.shift())
    }

    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        const index = stream.waiters.indexOf(handleResolve)
        if (index >= 0) stream.waiters.splice(index, 1)
        reject(new Error('等待服务端响应超时'))
      }, timeoutMs)

      const handleResolve = (frame) => {
        clearTimeout(timer)
        resolve(frame)
      }

      stream.waiters.push(handleResolve)
    })
  }

  sendFrame(frameId, frameType, payload) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('WebSocket 尚未连接')
    }

    let payloadBytes
    if (typeof payload === 'string') {
      payloadBytes = encoder.encode(payload)
    } else if (payload instanceof Uint8Array) {
      payloadBytes = payload
    } else if (payload instanceof ArrayBuffer) {
      payloadBytes = new Uint8Array(payload)
    } else {
      payloadBytes = encoder.encode(JSON.stringify(payload))
    }

    const out = new Uint8Array(5 + payloadBytes.length)
    const view = new DataView(out.buffer)
    view.setUint32(0, frameId, false)
    view.setUint8(4, frameType)
    out.set(payloadBytes, 5)
    this.ws.send(out.buffer)
  }

  async openRequestStream(action, data = {}, auth = null) {
    await this.connect()
    const frameId = this.getNextFrameId()

    const envelope = {
      action,
      data,
    }

    if (auth?.username && auth?.token) {
      envelope.username = auth.username
      envelope.token = auth.token
      envelope.nonce = randomNonce()
      envelope.timestamp = nowSeconds()
    }

    this.sendFrame(frameId, FRAME_TYPE_PROCESS, JSON.stringify(envelope))
    return frameId
  }

  async request(action, data = {}, auth = null, timeoutMs = 20000) {
    const frameId = await this.openRequestStream(action, data, auth)

    while (true) {
      const frame = await this.waitFrame(frameId, timeoutMs)
      if (frame.frameType !== FRAME_TYPE_CONCLUSION) {
        continue
      }

      const payload = parseMaybeJson(frame.payload)
      this.releaseStream(frameId)
      if (!payload) {
        throw new Error('服务端返回了非 JSON 响应')
      }
      return payload
    }
  }

  async uploadFileByTask(taskId, file, auth = null, onProgress = null) {
    const frameId = await this.openRequestStream('upload_file', { task_id: taskId }, auth)

    const first = await this.waitFrame(frameId)
    const handshake = parseMaybeJson(first.payload)
    if (!handshake || handshake.action !== 'transfer_file') {
      this.releaseStream(frameId)
      if (handshake && typeof handshake.code === 'number') {
        throw new Error(`上传握手失败: ${handshake.code} ${handshake.message || ''}`.trim())
      }
      throw new Error('上传握手失败')
    }

    const fileBuffer = await file.arrayBuffer()
    const fileBytes = new Uint8Array(fileBuffer)
    const hashBuffer = await crypto.subtle.digest('SHA-256', fileBuffer)
    const sha256 = Array.from(new Uint8Array(hashBuffer), (b) =>
      b.toString(16).padStart(2, '0'),
    ).join('')

    this.sendFrame(frameId, FRAME_TYPE_PROCESS, {
      action: 'transfer_file',
      data: {
        sha256,
        file_size: file.size,
        max_chunk_size: 65536,
      },
    })

    const readyFrame = await this.waitFrame(frameId)
    const readyText = toUtf8(readyFrame.payload)

    if (readyText.startsWith('stop')) {
      const conclude = parseMaybeJson((await this.waitFrame(frameId)).payload)
      this.releaseStream(frameId)
      return conclude
    }

    const matched = readyText.match(/^ready\s+(\d+)$/)
    if (!matched) {
      this.releaseStream(frameId)
      throw new Error(`服务端未进入上传状态：${readyText}`)
    }

    const chunkSize = Number.parseInt(matched[1], 10)
    let offset = 0
    while (offset < fileBytes.length) {
      const end = Math.min(offset + chunkSize, fileBytes.length)
      this.sendFrame(frameId, FRAME_TYPE_PROCESS, fileBytes.slice(offset, end))
      offset = end
      if (onProgress) onProgress({ loaded: offset, total: fileBytes.length })
    }

    const conclude = parseMaybeJson((await this.waitFrame(frameId, 60000)).payload)
    this.releaseStream(frameId)
    return conclude
  }

  async downloadFileByTask(taskId, options = {}, auth = null) {
    // End-to-end AES-256-GCM: CFMS streams ciphertext file_chunks then sends
    // a single aes_key envelope with key/nonce/tag. We buffer ciphertext,
    // decrypt in one shot via SubtleCrypto (GCM auth requires the full blob),
    // and verify SHA-256 of the plaintext against transfer_file metadata.
    const strictIntegrity = options.strictIntegrity !== false
    const maxBytes = Number(options.maxBytes || 0)
    const frameId = await this.openRequestStream('download_file', { task_id: taskId }, auth)

    const first = await this.waitFrame(frameId)
    const transferMeta = parseMaybeJson(first.payload)
    if (!transferMeta || transferMeta.action !== 'transfer_file') {
      this.releaseStream(frameId)
      if (transferMeta && typeof transferMeta.code === 'number') {
        throw new Error(`下载握手失败: ${transferMeta.code} ${transferMeta.message || ''}`.trim())
      }
      throw new Error('下载握手失败')
    }

    const expectedSize = Number(transferMeta.data?.file_size || 0)
    if (maxBytes > 0 && expectedSize > maxBytes) {
      this.releaseStream(frameId)
      throw new Error(`文件过大(${expectedSize} bytes)，已跳过下载`)
    }

    this.sendFrame(frameId, FRAME_TYPE_PROCESS, 'ready')

    // Empty files: CFMS skips the encrypted-stream branch entirely.
    if (expectedSize === 0) {
      this.releaseStream(frameId)
      return { fileBytes: new Uint8Array(0), fileSize: 0, sha256: transferMeta.data?.sha256 || '' }
    }

    const cipherChunks = []
    let cipherBytes = 0
    let keyEnvelope = null

    while (true) {
      const frame = await this.waitFrame(frameId, 60000)

      if (frame.frameType === FRAME_TYPE_CONCLUSION) {
        // CFMS does not normally send a conclusion for downloads. If we get
        // one before aes_key, it's an error envelope (e.g. permission denied).
        const errPayload = parseMaybeJson(frame.payload)
        this.releaseStream(frameId)
        const code = errPayload?.code
        throw new Error(`下载失败: ${code ?? '?'} ${errPayload?.message || ''}`.trim())
      }

      const payload = parseMaybeJson(frame.payload)
      if (!payload?.action) continue

      if (payload.action === 'file_chunk') {
        const cipher = base64ToBytes(payload.data.chunk)
        cipherChunks.push(cipher)
        cipherBytes += cipher.length
        if (options.onProgress && expectedSize > 0) {
          options.onProgress({
            loaded: Math.min(cipherBytes, expectedSize),
            total: expectedSize,
          })
        }
      } else if (payload.action === 'aes_key') {
        keyEnvelope = payload.data
        break
      }
    }

    this.releaseStream(frameId)

    if (typeof options.onChunksComplete === 'function') {
      options.onChunksComplete()
    }

    if (!keyEnvelope?.key || !keyEnvelope?.nonce || !keyEnvelope?.tag) {
      throw new Error('AES 密钥信封缺失 key/nonce/tag')
    }

    const key = base64ToBytes(keyEnvelope.key)
    const nonce = base64ToBytes(keyEnvelope.nonce)
    const tag = base64ToBytes(keyEnvelope.tag)

    // SubtleCrypto AES-GCM expects ciphertext || tag concatenated; PyCryptodome
    // gives them separately so we splice here.
    const sealed = new Uint8Array(cipherBytes + tag.length)
    let cursor = 0
    for (const c of cipherChunks) {
      sealed.set(c, cursor)
      cursor += c.length
    }
    sealed.set(tag, cipherBytes)

    const cryptoKey = await crypto.subtle.importKey(
      'raw',
      key,
      { name: 'AES-GCM' },
      false,
      ['decrypt'],
    )

    let plaintext
    try {
      const buffer = await crypto.subtle.decrypt(
        { name: 'AES-GCM', iv: nonce, tagLength: tag.length * 8 },
        cryptoKey,
        sealed,
      )
      plaintext = new Uint8Array(buffer)
    } catch (e) {
      throw new Error(`GCM 解密失败（密钥/nonce/tag 不匹配或密文被篡改）: ${e.message}`)
    }

    const fileBytes = expectedSize > 0 && plaintext.length > expectedSize
      ? plaintext.slice(0, expectedSize)
      : plaintext

    const expectedSha256 = String(transferMeta.data?.sha256 || '').toLowerCase()
    if (strictIntegrity && expectedSha256) {
      const actual = await sha256Hex(fileBytes)
      if (actual.toLowerCase() !== expectedSha256) {
        throw new Error('文件完整性校验失败：SHA-256 不匹配')
      }
    }

    return {
      fileBytes,
      fileSize: expectedSize,
      sha256: transferMeta.data?.sha256 || '',
    }
  }
}
