import CryptoJS from 'crypto-js'

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

const bytesToWordArray = (bytes) => {
  const words = []
  for (let i = 0; i < bytes.length; i += 1) {
    words[(i / 4) | 0] |= bytes[i] << (24 - 8 * (i % 4))
  }
  return CryptoJS.lib.WordArray.create(words, bytes.length)
}

const wordArrayToBytes = (wordArray) => {
  const { words, sigBytes } = wordArray
  const result = new Uint8Array(sigBytes)
  for (let i = 0; i < sigBytes; i += 1) {
    result[i] = (words[(i / 4) | 0] >>> (24 - 8 * (i % 4))) & 0xff
  }
  return result
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

const aesEcbEncryptBlock = (keyWordArray, blockBytes) => {
  const encrypted = CryptoJS.AES.encrypt(bytesToWordArray(blockBytes), keyWordArray, {
    mode: CryptoJS.mode.ECB,
    padding: CryptoJS.pad.NoPadding,
  })
  return wordArrayToBytes(encrypted.ciphertext)
}

const decryptCfb8Manual = (cipherBytes, keyWordArray, ivBytes) => {
  const output = new Uint8Array(cipherBytes.length)
  const state = new Uint8Array(ivBytes)

  for (let i = 0; i < cipherBytes.length; i += 1) {
    const keystream = aesEcbEncryptBlock(keyWordArray, state)
    output[i] = cipherBytes[i] ^ keystream[0]

    state.copyWithin(0, 1)
    state[state.length - 1] = cipherBytes[i]
  }

  return output
}

const decryptAesCfb = (cipherWordArray, keyWordArray, ivWordArray, segmentSize) => {
  const options = {
    iv: ivWordArray,
    mode: CryptoJS.mode.CFB,
    padding: CryptoJS.pad.NoPadding,
  }

  if (typeof segmentSize === 'number') {
    options.segmentSize = segmentSize
  }

  const decryptedWordArray = CryptoJS.AES.decrypt(
    { ciphertext: cipherWordArray },
    keyWordArray,
    options,
  )

  return wordArrayToBytes(decryptedWordArray)
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

    const encryptedChunks = []
    let ivBase64 = ''
    let aesKeyBase64 = ''
    let receivedBytes = 0

    while (true) {
      const frame = await this.waitFrame(frameId, 60000)
      const payload = parseMaybeJson(frame.payload)

      if (!payload?.action) {
        continue
      }

      if (payload.action === 'file_chunk') {
        const chunk = base64ToBytes(payload.data.chunk)
        encryptedChunks.push(chunk)
        receivedBytes += chunk.length
        if (!ivBase64 && payload.data.iv) {
          ivBase64 = payload.data.iv
        }
        if (options.onProgress && expectedSize > 0) {
          options.onProgress({ loaded: Math.min(receivedBytes, expectedSize), total: expectedSize })
        }
      } else if (payload.action === 'aes_key') {
        aesKeyBase64 = payload.data.key
        break
      } else if (frame.frameType === FRAME_TYPE_CONCLUSION && payload.code) {
        break
      }
    }

    this.releaseStream(frameId)

    if (!aesKeyBase64 || !ivBase64) {
      throw new Error('下载数据不完整，缺少解密参数')
    }

    if (typeof options.onChunksComplete === 'function') {
      options.onChunksComplete()
    }

    const encryptedLength = encryptedChunks.reduce((sum, c) => sum + c.length, 0)
    const encryptedAll = new Uint8Array(encryptedLength)
    let cursor = 0
    for (const c of encryptedChunks) {
      encryptedAll.set(c, cursor)
      cursor += c.length
    }

    const cipherWordArray = bytesToWordArray(encryptedAll)
    const keyWordArray = bytesToWordArray(base64ToBytes(aesKeyBase64))
    const ivWordArray = bytesToWordArray(base64ToBytes(ivBase64))

    const expectedSha256 = String(transferMeta.data?.sha256 || '').toLowerCase()
    const strategies = strictIntegrity
      ? [
      () => decryptCfb8Manual(encryptedAll, keyWordArray, base64ToBytes(ivBase64)),
      () => decryptAesCfb(cipherWordArray, keyWordArray, ivWordArray, 8),
      () => decryptAesCfb(cipherWordArray, keyWordArray, ivWordArray, 128),
      () => decryptAesCfb(cipherWordArray, keyWordArray, ivWordArray, undefined),
      ]
      : [
       () => decryptCfb8Manual(encryptedAll, keyWordArray, base64ToBytes(ivBase64)),
      ]
    let decryptedBytes = null
    let fallbackBytes = null
    
    for (const runStrategy of strategies) {
      try {
        const candidate = runStrategy()
        const sliced = candidate.slice(0, expectedSize)

        if (!sliced.length && expectedSize > 0) {
          continue
        }

        if (!strictIntegrity || !expectedSha256) {
          decryptedBytes = sliced
          break
        }

        const candidateSha256 = await sha256Hex(sliced)
        if (candidateSha256.toLowerCase() === expectedSha256) {
          decryptedBytes = sliced
          break
        }

        if (!fallbackBytes) {
          fallbackBytes = sliced
        }
      } catch {
        // Try next strategy.
      }
    }

    if (!decryptedBytes && !strictIntegrity && fallbackBytes) {
      decryptedBytes = fallbackBytes
    }

    if (!decryptedBytes) {
      throw new Error('文件解密失败：无法通过完整性校验')
    }

    return {
      fileBytes: decryptedBytes,
      fileSize: expectedSize,
      sha256: transferMeta.data?.sha256 || '',
    }
  }
}
