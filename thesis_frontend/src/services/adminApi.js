export const ADMIN_TOKEN_STORAGE_KEY = 'thesis-drive:carapace-admin-token'

const tokenListeners = new Set()
let memoryToken = ''

const sessionStore = () => {
  try {
    return globalThis.sessionStorage || null
  } catch {
    return null
  }
}

export const getAdminToken = () => {
  const store = sessionStore()
  if (!store) return memoryToken
  try {
    return store.getItem(ADMIN_TOKEN_STORAGE_KEY) || ''
  } catch {
    return memoryToken
  }
}

export const setAdminToken = (token) => {
  const normalized = String(token || '').trim()
  memoryToken = normalized
  const store = sessionStore()
  try {
    if (normalized) store?.setItem(ADMIN_TOKEN_STORAGE_KEY, normalized)
    else store?.removeItem(ADMIN_TOKEN_STORAGE_KEY)
  } catch {
    // In-memory fallback still keeps the current tab functional.
  }
  tokenListeners.forEach((listener) => listener(normalized))
  return normalized
}

export const clearAdminToken = () => setAdminToken('')

export const subscribeAdminToken = (listener) => {
  tokenListeners.add(listener)
  return () => tokenListeners.delete(listener)
}

export class AdminApiError extends Error {
  constructor(message, status = 0) {
    super(message)
    this.name = 'AdminApiError'
    this.status = status
  }
}

export const adminFetch = (input, init = {}, fetchImpl = globalThis.fetch?.bind(globalThis)) => {
  if (!fetchImpl) throw new Error('当前环境不支持 fetch')
  const headers = new Headers(init.headers || {})
  const token = getAdminToken()
  if (token) headers.set('X-Admin-Token', token)
  return fetchImpl(input, { ...init, headers })
}

export const requireAdminResponse = async (response) => {
  if (response.ok) return response
  if (response.status === 401 || response.status === 403) {
    throw new AdminApiError('管理令牌无效或权限不足', response.status)
  }
  let message = ''
  try {
    const payload = await response.json()
    message = payload?.message || ''
  } catch {
    // Non-JSON management errors use the status line below.
  }
  throw new AdminApiError(message || `管理接口请求失败: HTTP ${response.status}`, response.status)
}

const dispatchSseBlock = (block, onEvent) => {
  let event = 'message'
  let id = ''
  const data = []
  for (const line of block.split(/\r?\n/)) {
    if (!line || line.startsWith(':')) continue
    const separator = line.indexOf(':')
    const field = separator < 0 ? line : line.slice(0, separator)
    let value = separator < 0 ? '' : line.slice(separator + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') event = value
    else if (field === 'data') data.push(value)
    else if (field === 'id') id = value
  }
  if (data.length) onEvent?.({ event, data: data.join('\n'), id })
}

export const streamAdminSse = async (url, options = {}) => {
  const response = await adminFetch(url, {
    method: 'GET',
    headers: { Accept: 'text/event-stream', ...(options.headers || {}) },
    cache: 'no-store',
    signal: options.signal,
  }, options.fetchImpl)
  await requireAdminResponse(response)
  if (!response.body) throw new AdminApiError('浏览器不支持流式管理事件')
  options.onOpen?.(response)

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    const blocks = buffer.split(/\r?\n\r?\n/)
    buffer = blocks.pop() || ''
    blocks.forEach((block) => dispatchSseBlock(block, options.onEvent))
    if (done) break
  }
  if (buffer.trim()) dispatchSseBlock(buffer, options.onEvent)
}

export const downloadAdminFile = async (url, filename, options = {}) => {
  const response = await adminFetch(url, { method: 'GET' }, options.fetchImpl)
  await requireAdminResponse(response)
  const blob = await response.blob()
  const documentRef = options.document || globalThis.document
  const urlApi = options.urlApi || globalThis.URL
  if (!documentRef || !urlApi) throw new Error('当前环境无法保存导出文件')

  const objectUrl = urlApi.createObjectURL(blob)
  try {
    const anchor = documentRef.createElement('a')
    anchor.href = objectUrl
    anchor.download = filename
    anchor.rel = 'noopener'
    anchor.style.display = 'none'
    documentRef.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
  } finally {
    urlApi.revokeObjectURL(objectUrl)
  }
}

export const carapaceBaseUrl = () =>
  String(import.meta.env.VITE_CARAPACE_URL || '').trim().replace(/\/$/, '')
