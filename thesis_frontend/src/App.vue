<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { CfmsClient } from './services/cfmsClient'

import navDashboardIcon from './assets/icons/nav/dashboard.svg'
import navFilesIcon from './assets/icons/nav/files.svg'
import navTransferIcon from './assets/icons/nav/transfer.svg'
import navProfileIcon from './assets/icons/nav/profile.svg'

import toastSuccessIcon from './assets/icons/toast/success.png'
import toastWarningIcon from './assets/icons/toast/warning.png'
import toastDangerIcon from './assets/icons/toast/danger.png'

const ROOT_ID = '/'

function resolveCfmsWsUrl() {
  const raw = import.meta.env.VITE_WS_URL
  const v = typeof raw === 'string' ? raw.trim() : ''
  const useAuto = !v || v.toLowerCase() === 'auto'

  if (!useAuto) return v

  if (import.meta.env.DEV) {
    return 'ws://127.0.0.1:10085'
  }

  if (typeof window === 'undefined') {
    return 'wss://127.0.0.1/ws'
  }

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws`
}

const wsUrl = ref(resolveCfmsWsUrl())
const isConnected = ref(false)
const isConnecting = ref(false)
const busy = ref(false)
const authMode = ref('login')
const activeTab = ref('dashboard')

const auth = reactive({
  username: 'admin',
  password: '',
})

const registerForm = reactive({
  username: '',
  password: '',
  confirmPassword: '',
  nickname: '',
})

const loginStage = reactive({
  need2fa: false,
  needForcePassword: false,
})

const twoFaForm = reactive({ token: '' })
const forcePasswordForm = reactive({ newPassword: '', confirmPassword: '' })

const session = reactive({
  username: '',
  token: '',
  nickname: '',
  exp: 0,
  avatarId: '',
  permissions: [],
  groups: [],
})

const drive = reactive({
  totalBytes: 20 * 1024 * 1024 * 1024,
  usedBytes: 0,
  folders: [],
  files: [],
  recentFiles: [],
  recycleFolders: [],
  recycleFiles: [],
})

const fileQuery = ref('')
const fileCategory = ref('all')
const fileSortKey = ref('title')
const fileSortOrder = ref('asc')
const filePage = ref(1)
const filePageSize = ref(8)

const logs = ref([])
const logSeq = ref(0)
const showLogModal = ref(false)

const toasts = ref([])
const toastSeq = ref(0)

const navItems = [
  { key: 'dashboard', label: '主页', icon: navDashboardIcon },
  { key: 'files', label: '文件', icon: navFilesIcon },
  { key: 'transfer', label: '传输', icon: navTransferIcon },
  { key: 'profile', label: '我的', icon: navProfileIcon },
]

const toastIconByType = {
  success: toastSuccessIcon,
  warning: toastWarningIcon,
  danger: toastDangerIcon,
  info: toastWarningIcon,
}

const isAuthed = computed(() => Boolean(session.username && session.token))
const remainingBytes = computed(() => Math.max(0, drive.totalBytes - drive.usedBytes))
const transferLogs = computed(() => logs.value.slice(0, 12))
const dashboardUsagePercent = ref(43)
const selectedRecentFileId = ref('')
const lastSyncAt = ref(0)
const avatarImageUrl = ref('')
const avatarFileInput = ref(null)
const showAvatarCropModal = ref(false)
const avatarLoading = ref(false)
const THEME_MODE_KEY = 'thesis-theme-mode'
const themeMode = ref('light')
const AVATAR_CACHE_PREFIX = 'thesis-avatar-cache:'
const AVATAR_DB_NAME = 'thesis-avatar-cache-db'
const AVATAR_DB_STORE = 'avatars'
const avatarMemoryCache = new Map()
let avatarLoadingPromise = null
const servicePillCollapsed = ref(false)
let servicePillTimer = null
const navRef = ref(null)
const navGlow = reactive({
  active: false,
  pressing: false,
  x: 0,
  y: 0,
})
const navDeform = reactive({ sx: 1, sy: 1, ox: '50%', oy: '50%' })

const avatarDraft = reactive({
  sourceUrl: '',
  zoom: 1,
  offsetX: 0,
  offsetY: 0,
})

const profileForm = reactive({
  nickname: '',
  oldPassword: '',
  newPassword: '',
  confirmPassword: '',
})

const twoFaState = reactive({
  enabled: false,
  method: null,
  backupCodesCount: 0,
  setupSecret: '',
  setupUri: '',
  setupBackupCodes: [],
  verifyToken: '',
  disablePassword: '',
})

const dashboardUsedBytes = computed(() => Math.round((drive.totalBytes * dashboardUsagePercent.value) / 100))
const dashboardRemainingBytes = computed(() => Math.max(0, drive.totalBytes - dashboardUsedBytes.value))
const isDarkMode = computed(() => themeMode.value === 'dark')
const ringRadius = 42
const ringLength = computed(() => 2 * Math.PI * ringRadius)
const ringOffset = computed(() => ringLength.value * (1 - dashboardUsagePercent.value / 100))

const pickRecentByModified = (documents = [], limit = 20) => {
  if (!Array.isArray(documents) || !documents.length) return []

  const top = []
  for (const doc of documents) {
    const current = Number(doc?.last_modified || 0)
    let inserted = false
    for (let i = 0; i < top.length; i += 1) {
      const score = Number(top[i]?.last_modified || 0)
      if (current > score) {
        top.splice(i, 0, doc)
        inserted = true
        break
      }
    }

    if (!inserted && top.length < limit) {
      top.push(doc)
    }

    if (top.length > limit) {
      top.length = limit
    }
  }

  return top
}

const recentDisplayFiles = computed(() => {
  const base = [...pickRecentByModified(drive.recentFiles, 20)]

  const mockPool = [
    '毕业设计封面.psd',
    '答辩录屏.mp4',
    '调研访谈音频.wav',
    '实验日志-03.md',
    '参考文献整理.docx',
    '测试样例集.zip',
    '课题海报.png',
    '周报-第7周.pdf',
  ]

  while (base.length < 14) {
    const title = mockPool[base.length % mockPool.length]
    base.push({
      id: `mock-${base.length}`,
      title,
      size: 18 * 1024 * 1024 + base.length * 1024,
      last_modified: Date.now() / 1000 - base.length * 3600,
    })
  }

  return base
})

const fileCategoryOf = (title = '') => {
  const idx = String(title).lastIndexOf('.')
  const ext = idx >= 0 ? String(title).slice(idx + 1).toLowerCase() : ''
  if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'heic'].includes(ext)) return 'album'
  if (['mp4', 'mov', 'mkv', 'avi', 'webm'].includes(ext)) return 'video'
  if (['mp3', 'wav', 'flac', 'm4a', 'aac'].includes(ext)) return 'music'
  return 'document'
}

const categoryStats = computed(() => {
  const stats = {
    album: 0,
    video: 0,
    music: 0,
    document: 0,
  }

  for (const item of drive.files) {
    const category = fileCategoryOf(item.title)
    if (category === 'album') {
      stats.album += 1
    } else if (category === 'video') {
      stats.video += 1
    } else if (category === 'music') {
      stats.music += 1
    } else {
      stats.document += 1
    }
  }

  return stats
})

const filteredFiles = computed(() => {
  const q = fileQuery.value.trim().toLowerCase()
  let list = [...drive.files]

  if (q) {
    list = list.filter((f) => (f.title || '').toLowerCase().includes(q))
  }

  if (fileCategory.value !== 'all') {
    list = list.filter((f) => fileCategoryOf(f.title || '') === fileCategory.value)
  }

  const order = fileSortOrder.value === 'asc' ? 1 : -1
  list.sort((a, b) => {
    if (fileSortKey.value === 'size') {
      return (Number(a.size || 0) - Number(b.size || 0)) * order
    }
    if (fileSortKey.value === 'last_modified') {
      return (Number(a.last_modified || 0) - Number(b.last_modified || 0)) * order
    }
    return String(a.title || '').localeCompare(String(b.title || '')) * order
  })

  return list
})

const totalFilePages = computed(() => Math.max(1, Math.ceil(filteredFiles.value.length / filePageSize.value)))
const pagedFiles = computed(() => {
  const page = Math.min(filePage.value, totalFilePages.value)
  const start = (page - 1) * filePageSize.value
  return filteredFiles.value.slice(start, start + filePageSize.value)
})

const formatGB = (bytes) => `${(bytes / (1024 ** 3)).toFixed(2)} GB`
const formatMB = (bytes) => `${(bytes / (1024 ** 2)).toFixed(2)} MB`
const formatDateTime = (seconds) => {
  if (!seconds) return '-'
  const date = new Date(Number(seconds) * 1000)
  return Number.isNaN(date.getTime()) ? '-' : date.toLocaleString()
}

const fileTypeLabel = (title = '') => {
  const category = fileCategoryOf(title)
  if (category === 'album') return '图片'
  if (category === 'video') return '视频'
  if (category === 'music') return '音频'
  return '文档'
}

const avatarCropStyle = computed(() => ({
  transform: `translate(${avatarDraft.offsetX * 24}px, ${avatarDraft.offsetY * 24}px) scale(${avatarDraft.zoom})`,
}))

const groupTagClass = (groupName = '') => {
  const group = String(groupName || '').toLowerCase()
  if (group === 'sysop') return 'group-pill role-sysop'
  if (group === 'user') return 'group-pill role-user'
  if (group === 'admin') return 'group-pill role-admin'
  return 'group-pill role-other'
}

const pushLog = (text, type = 'info') => {
  logs.value.unshift({
    id: ++logSeq.value,
    text,
    type,
    time: new Date().toLocaleTimeString(),
  })
  logs.value = logs.value.slice(0, 30)
}

const pushToast = (text, type = 'info') => {
  const id = ++toastSeq.value
  toasts.value.push({ id, text, type })
  setTimeout(() => {
    toasts.value = toasts.value.filter((t) => t.id !== id)
  }, 2800)
}

const authHeader = () => ({ username: session.username, token: session.token })

const setThemeMode = (mode) => {
  const next = mode === 'dark' ? 'dark' : 'light'
  themeMode.value = next
  localStorage.setItem(THEME_MODE_KEY, next)
}

const toggleThemeMode = (event) => {
  const next = isDarkMode.value ? 'light' : 'dark'

  const fallbackX = window.innerWidth - 34
  const fallbackY = window.innerHeight - 34
  const x = event?.clientX ?? fallbackX
  const y = event?.clientY ?? fallbackY
  document.documentElement.style.setProperty('--theme-reveal-x', `${x}px`)
  document.documentElement.style.setProperty('--theme-reveal-y', `${y}px`)

  if (document.startViewTransition) {
    document.startViewTransition(() => {
      setThemeMode(next)
    })
    return
  }

  setThemeMode(next)
}

const expandServicePillThenAutoCollapse = () => {
  servicePillCollapsed.value = false
  if (servicePillTimer) {
    clearTimeout(servicePillTimer)
  }

  servicePillTimer = setTimeout(() => {
    servicePillCollapsed.value = true
  }, 7000)
}

const client = new CfmsClient({
  url: wsUrl.value,
  onConnectionState: (state) => {
    if (isConnected.value !== state.connected) {
      isConnected.value = state.connected
      expandServicePillThenAutoCollapse()
      if (state.connected) {
        pushLog('连接成功', 'success')
        pushToast('连接成功', 'success')
      } else {
        pushLog('连接断开', 'warning')
        pushToast('连接断开', 'warning')
      }
    }
  },
  onServerEvent: (event) => {
    pushLog(`服务端事件: ${event.event}`, 'info')
  },
})

const runBusy = async (fn) => {
  busy.value = true
  try {
    await fn()
  } finally {
    busy.value = false
  }
}

const connectWs = async () => {
  if (isConnected.value || isConnecting.value) return
  isConnecting.value = true
  try {
    client.setUrl(wsUrl.value)
    await client.connect()
  } finally {
    isConnecting.value = false
  }
}

const callAction = async (action, data = {}, useAuth = true, throwOnError = true) => {
  const response = await client.request(action, data, useAuth ? authHeader() : null)
  if (throwOnError && response.code >= 400 && response.code !== 202) {
    throw new Error(`${response.code}: ${response.message}`)
  }
  return response
}

const loadServerInfo = async () => {
  const response = await callAction('server_info', {}, false)
  pushLog(`服务信息已刷新: 协议 ${response.data.protocol_version}`, 'info')
}

const loadFileList = async () => {
  const response = await callAction('list_directory', { folder_id: null }, true)
  drive.folders = response.data.folders || []
  drive.files = response.data.documents || []
  drive.usedBytes = drive.files.reduce((sum, item) => sum + Number(item.size || 0), 0)
  drive.recentFiles = pickRecentByModified(drive.files, 20)
  filePage.value = 1
}

const runWhenIdle = (fn, timeout = 1500) => {
  if (typeof window !== 'undefined' && typeof window.requestIdleCallback === 'function') {
    window.requestIdleCallback(() => {
      fn()
    }, { timeout })
    return
  }

  setTimeout(() => {
    fn()
  }, 280)
}

const loadProfileSettings = async () => {
  if (!session.username) return

  const info = await callAction('get_user_info', { username: session.username }, true)
  profileForm.nickname = info.data.nickname || ''

  const twoFa = await callAction('get_2fa_status', {}, true)
  twoFaState.enabled = Boolean(twoFa.data.enabled)
  twoFaState.method = twoFa.data.method || null
  twoFaState.backupCodesCount = Number(twoFa.data.backup_codes_count || 0)
}

const loadRecycle = async () => {
  try {
    const response = await callAction('list_deleted_items', { folder_id: ROOT_ID }, true)
    drive.recycleFolders = response.data.folders || []
    drive.recycleFiles = response.data.documents || []
  } catch {
    drive.recycleFolders = []
    drive.recycleFiles = []
    pushLog('回收站读取失败或无权限', 'warning')
  }
}

const loadDriveOverview = async () => {
  await loadFileList()
  await loadRecycle()
  lastSyncAt.value = Date.now() / 1000
}

const revokeUrl = (value) => {
  if (value) {
    URL.revokeObjectURL(value)
  }
}

const openAvatarDb = () =>
  new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') {
      resolve(null)
      return
    }

    const request = indexedDB.open(AVATAR_DB_NAME, 1)

    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains(AVATAR_DB_STORE)) {
        db.createObjectStore(AVATAR_DB_STORE)
      }
    }

    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error || new Error('头像缓存数据库打开失败'))
  })

const idbGetAvatarBlob = async (key) => {
  const db = await openAvatarDb()
  if (!db) return null

  return new Promise((resolve, reject) => {
    const tx = db.transaction(AVATAR_DB_STORE, 'readonly')
    const store = tx.objectStore(AVATAR_DB_STORE)
    const req = store.get(key)

    req.onsuccess = () => {
      const value = req.result
      resolve(value instanceof Blob ? value : null)
    }
    req.onerror = () => reject(req.error || new Error('读取头像缓存失败'))
  }).finally(() => {
    db.close()
  })
}

const idbSetAvatarBlob = async (key, blob) => {
  const db = await openAvatarDb()
  if (!db) return

  await new Promise((resolve, reject) => {
    const tx = db.transaction(AVATAR_DB_STORE, 'readwrite')
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error || new Error('写入头像缓存失败'))
    tx.objectStore(AVATAR_DB_STORE).put(blob, key)
  }).finally(() => {
    db.close()
  })
}

const idbDeleteByPrefix = async (prefix, keepKey = '') => {
  const db = await openAvatarDb()
  if (!db) return

  await new Promise((resolve, reject) => {
    const tx = db.transaction(AVATAR_DB_STORE, 'readwrite')
    const store = tx.objectStore(AVATAR_DB_STORE)
    const cursorReq = store.openCursor()

    cursorReq.onsuccess = () => {
      const cursor = cursorReq.result
      if (!cursor) return
      const key = String(cursor.key || '')
      if (key.startsWith(prefix) && key !== keepKey) {
        cursor.delete()
      }
      cursor.continue()
    }

    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error || new Error('清理头像缓存失败'))
  }).finally(() => {
    db.close()
  })
}

const avatarCacheKey = () => {
  if (!session.username || !session.avatarId) return ''
  return `${AVATAR_CACHE_PREFIX}${session.username}:${session.avatarId}`
}

const clearAvatarCacheByUser = (username, keepKey = '') => {
  if (!username) return
  const prefix = `${AVATAR_CACHE_PREFIX}${username}:`

  for (const key of Array.from(avatarMemoryCache.keys())) {
    if (key.startsWith(prefix) && key !== keepKey) {
      avatarMemoryCache.delete(key)
    }
  }

  for (let i = localStorage.length - 1; i >= 0; i -= 1) {
    const key = localStorage.key(i)
    if (key && key.startsWith(prefix) && key !== keepKey) {
      localStorage.removeItem(key)
    }
  }

  runSafe(async () => {
    await idbDeleteByPrefix(prefix, keepKey)
  })
}

const loadAvatarFromCache = async () => {
  const key = avatarCacheKey()
  if (!key) return false

  const memBlob = avatarMemoryCache.get(key)
  if (memBlob instanceof Blob) {
    applyAvatarUrl(URL.createObjectURL(memBlob))
    return true
  }

  try {
    const dbBlob = await idbGetAvatarBlob(key)
    if (dbBlob) {
      avatarMemoryCache.set(key, dbBlob)
      applyAvatarUrl(URL.createObjectURL(dbBlob))
      return true
    }
  } catch {
    // Ignore IndexedDB read errors and fallback to localStorage compatibility cache.
  }

  const dataUrl = localStorage.getItem(key)
  if (!dataUrl) return false
  applyAvatarUrl(dataUrl)
  return true
}

const blobToDataUrl = (blob) =>
  new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(new Error('头像缓存转换失败'))
    reader.readAsDataURL(blob)
  })

const saveAvatarToCache = async (blob) => {
  const key = avatarCacheKey()
  if (!key || !blob) return
  clearAvatarCacheByUser(session.username, key)
  avatarMemoryCache.set(key, blob)

  try {
    await idbSetAvatarBlob(key, blob)
  } catch {
    // Fallback to localStorage below.
  }

  const dataUrl = await blobToDataUrl(blob)
  localStorage.setItem(key, dataUrl)
}

const applyAvatarUrl = (url) => {
  revokeUrl(avatarImageUrl.value)
  avatarImageUrl.value = url
}

const onAvatarImageError = () => {
  revokeUrl(avatarImageUrl.value)
  avatarImageUrl.value = ''
}

const detectImageMime = (bytes) => {
  if (!bytes || bytes.length < 4) return ''
  if (bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47) return 'image/png'
  if (bytes[0] === 0xff && bytes[1] === 0xd8) return 'image/jpeg'
  if (bytes[0] === 0x47 && bytes[1] === 0x49 && bytes[2] === 0x46) return 'image/gif'
  if (bytes[0] === 0x42 && bytes[1] === 0x4d) return 'image/bmp'
  if (
    bytes.length > 12
    && bytes[0] === 0x52
    && bytes[1] === 0x49
    && bytes[2] === 0x46
    && bytes[3] === 0x46
    && bytes[8] === 0x57
    && bytes[9] === 0x45
    && bytes[10] === 0x42
    && bytes[11] === 0x50
  ) {
    return 'image/webp'
  }
  return ''
}

const loadAvatarPreview = async () => {
  const guardUsername = session.username
  const guardAvatarId = session.avatarId

  if (!session.username) return
  if (!session.avatarId) return
  if (avatarLoading.value) return
  if (avatarLoadingPromise) return avatarLoadingPromise

  avatarLoadingPromise = (async () => {
    avatarLoading.value = true

    try {
      const avatarResp = await callAction(
        'get_user_avatar',
        { username: session.username },
        true,
        false,
      )

      if (avatarResp.code >= 400) {
        revokeUrl(avatarImageUrl.value)
        avatarImageUrl.value = ''
        clearAvatarCacheByUser(session.username)
        return
      }

      const taskId = avatarResp.data?.task_data?.task_id
      if (!taskId) return

      const { fileBytes } = await client.downloadFileByTask(
        taskId,
        {
          strictIntegrity: false,
          maxBytes: 1024 * 1024,
        },
        authHeader(),
      )
      if (!fileBytes || !fileBytes.length) {
        throw new Error('头像数据为空')
      }

      const mime = detectImageMime(fileBytes) || 'application/octet-stream'
      const blob = new Blob([fileBytes], { type: mime })

      if (session.username !== guardUsername || session.avatarId !== guardAvatarId) {
        return
      }

      const objectUrl = URL.createObjectURL(blob)
      applyAvatarUrl(objectUrl)
      await saveAvatarToCache(blob)
    } catch (error) {
      // 保留旧头像，避免临时下载失败导致闪回默认字母。
      pushLog(`头像加载失败: ${error?.message || 'unknown error'}`, 'warning')
    } finally {
      avatarLoading.value = false
      avatarLoadingPromise = null
    }
  })()

  return avatarLoadingPromise
}

const warmupAvatarInBackground = (delay = 360) => {
  if (!session.username || !session.avatarId) return
  if (avatarLoading.value) return

  setTimeout(() => {
    runWhenIdle(() => {
      runSafe(loadAvatarPreview)
    }, 2200)
  }, delay)
}

const openAvatarUpload = () => {
  avatarFileInput.value?.click()
}

const closeAvatarCrop = () => {
  showAvatarCropModal.value = false
  revokeUrl(avatarDraft.sourceUrl)
  avatarDraft.sourceUrl = ''
  avatarDraft.zoom = 1
  avatarDraft.offsetX = 0
  avatarDraft.offsetY = 0
  if (avatarFileInput.value) {
    avatarFileInput.value.value = ''
  }
}

const onAvatarFileChange = (event) => {
  const file = event.target?.files?.[0]
  if (!file) return
  if (!file.type.startsWith('image/')) {
    pushToast('请选择图片文件', 'warning')
    return
  }

  revokeUrl(avatarDraft.sourceUrl)
  avatarDraft.sourceUrl = URL.createObjectURL(file)
  avatarDraft.zoom = 1
  avatarDraft.offsetX = 0
  avatarDraft.offsetY = 0
  showAvatarCropModal.value = true
}

const loadImageFromUrl = (url) =>
  new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('图片读取失败'))
    img.src = url
  })

const buildAvatarBlob = async () => {
  const img = await loadImageFromUrl(avatarDraft.sourceUrl)
  const canvas = document.createElement('canvas')
  const outSize = 512
  canvas.width = outSize
  canvas.height = outSize
  const ctx = canvas.getContext('2d')

  if (!ctx) throw new Error('浏览器不支持图片裁剪')

  const baseCrop = Math.min(img.width, img.height)
  const cropSize = baseCrop / Math.max(1, avatarDraft.zoom)
  const maxDx = Math.max(0, (img.width - cropSize) / 2)
  const maxDy = Math.max(0, (img.height - cropSize) / 2)
  const sourceX = (img.width - cropSize) / 2 + avatarDraft.offsetX * maxDx
  const sourceY = (img.height - cropSize) / 2 + avatarDraft.offsetY * maxDy

  ctx.drawImage(
    img,
    Math.max(0, Math.min(img.width - cropSize, sourceX)),
    Math.max(0, Math.min(img.height - cropSize, sourceY)),
    cropSize,
    cropSize,
    0,
    0,
    outSize,
    outSize,
  )

  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (!blob) {
          reject(new Error('裁剪失败，请重试'))
          return
        }
        resolve(blob)
      },
      'image/png',
      0.95,
    )
  })
}

const submitAvatarUpload = async () => {
  await runBusy(async () => {
    if (!avatarDraft.sourceUrl) {
      throw new Error('请先选择头像图片')
    }

    const blob = await buildAvatarBlob()
    const file = new File([blob], `avatar-${Date.now()}.png`, { type: 'image/png' })

    const localPreview = URL.createObjectURL(blob)
    applyAvatarUrl(localPreview)

    const createResp = await callAction(
      'create_document',
      {
        folder_id: null,
        title: file.name,
        inherit_parent: true,
      },
      true,
    )

    const taskId = createResp.data?.task_data?.task_id
    const documentId = createResp.data?.document_id

    if (!taskId || !documentId) {
      throw new Error('头像上传任务创建失败')
    }

    const uploadResp = await client.uploadFileByTask(taskId, file, authHeader())
    if (uploadResp?.code >= 400) {
      throw new Error(uploadResp.message || '头像文件上传失败')
    }

    await callAction(
      'set_user_avatar',
      {
        username: session.username,
        document_id: documentId,
      },
      true,
    )

    const refreshed = await callAction('get_user_info', { username: session.username }, true)
    session.avatarId = refreshed.data?.avatar_id || session.avatarId
    await saveAvatarToCache(blob)

    // 上传后先用本地预览图，不在这里触发下载解密，避免页面卡顿。
    closeAvatarCrop()
    pushToast('头像已更新并同步', 'success')
  })
}

const handleLogin = async () => {
  await runBusy(async () => {
    // 防止上一次流程遗留的弹层状态影响本次登录交互。
    showLogModal.value = false
    showAvatarCropModal.value = false

    await connectWs()
    const response = await callAction(
      'login',
      {
        username: auth.username,
        password: auth.password,
        '2fa_token': loginStage.need2fa ? twoFaForm.token : undefined,
      },
      false,
      false,
    )

    if (response.code === 202) {
      loginStage.need2fa = true
      pushLog('需要 2FA 验证', 'warning')
      pushToast('请输入 2FA 验证码', 'warning')
      return
    }

    if (response.code === 4001 || response.code === 4002) {
      loginStage.needForcePassword = true
      pushLog('需要强制改密', 'warning')
      pushToast('请先修改密码', 'warning')
      return
    }

    if (response.code >= 400) {
      throw new Error(`${response.code}: ${response.message}`)
    }

    session.username = auth.username
    session.token = response.data.token
    session.nickname = response.data.nickname || ''
    session.exp = response.data.exp || 0
    session.avatarId = response.data.avatar_id || ''
    session.permissions = response.data.permissions || []
    session.groups = response.data.groups || []
    activeTab.value = 'dashboard'

    loginStage.need2fa = false
    loginStage.needForcePassword = false
    twoFaForm.token = ''

    pushLog('登录成功', 'success')
    pushToast('登录成功', 'success')

    runSafe(async () => {
      const loadedFromCache = await loadAvatarFromCache()
      if (!loadedFromCache) {
        warmupAvatarInBackground(220)
      }
    })

  })
}

const submitForcePassword = async () => {
  await runBusy(async () => {
    if (!forcePasswordForm.newPassword) {
      throw new Error('请输入新密码')
    }
    if (forcePasswordForm.newPassword !== forcePasswordForm.confirmPassword) {
      throw new Error('两次新密码不一致')
    }

    await callAction(
      'set_passwd',
      {
        username: auth.username,
        old_passwd: auth.password,
        new_passwd: forcePasswordForm.newPassword,
      },
      false,
    )

    auth.password = forcePasswordForm.newPassword
    forcePasswordForm.newPassword = ''
    forcePasswordForm.confirmPassword = ''
    loginStage.needForcePassword = false

    pushLog('强制改密完成', 'success')
    pushToast('改密成功，请重新登录', 'success')
  })
}

const submitRegister = async () => {
  await runBusy(async () => {
    if (!registerForm.username || !registerForm.password) {
      throw new Error('请填写完整注册信息')
    }
    if (registerForm.password !== registerForm.confirmPassword) {
      throw new Error('两次密码不一致')
    }

    await callAction(
      'register',
      {
        username: registerForm.username.trim(),
        password: registerForm.password,
        nickname: registerForm.nickname?.trim() || null,
      },
      false,
    )

    auth.username = registerForm.username.trim()
    auth.password = ''

    registerForm.username = ''
    registerForm.password = ''
    registerForm.confirmPassword = ''
    registerForm.nickname = ''

    authMode.value = 'login'
    pushLog('注册成功，请登录', 'success')
    pushToast('注册成功，请使用新账号登录', 'success')
  })
}

const restoreRecycleDoc = async (documentId) => {
  await callAction('restore_document', { document_id: documentId }, true)
  pushToast('文档已恢复', 'success')
  await loadRecycle()
  await loadFileList()
}

const purgeRecycleDoc = async (documentId) => {
  await callAction('purge_document', { document_id: documentId }, true)
  pushToast('文档已永久删除', 'warning')
  await loadRecycle()
}

const restoreRecycleFolder = async (folderId) => {
  await callAction('restore_directory', { folder_id: folderId }, true)
  pushToast('目录已恢复', 'success')
  await loadRecycle()
  await loadFileList()
}

const purgeRecycleFolder = async (folderId) => {
  await callAction('purge_directory', { folder_id: folderId }, true)
  pushToast('目录已永久删除', 'warning')
  await loadRecycle()
}

const goPrevPage = () => {
  filePage.value = Math.max(1, filePage.value - 1)
}

const goNextPage = () => {
  filePage.value = Math.min(totalFilePages.value, filePage.value + 1)
}

const selectRecentFile = (file) => {
  selectedRecentFileId.value = file.id
}

const handleRecentAction = async (file, actionKey) => {
  if (!file) return
  const actionText = {
    preview: '预览',
    download: '下载',
    share: '分享',
    recycle: '移入回收站',
  }[actionKey] || '操作'
  pushToast(`${actionText}: ${file.title}`, 'info')
}

const handleFileAction = async (file, actionKey) => {
  await handleRecentAction(file, actionKey)
}

const jumpToCategory = async (category) => {
  fileCategory.value = category
  filePage.value = 1
  await changeTab('files')
}

const submitNickname = async () => {
  await runBusy(async () => {
    await callAction(
      'rename_user',
      {
        username: session.username,
        nickname: profileForm.nickname || null,
      },
      true,
    )
    session.nickname = profileForm.nickname || session.username
    pushToast('昵称已更新', 'success')
  })
}

const submitPasswordUpdate = async () => {
  await runBusy(async () => {
    if (!profileForm.oldPassword || !profileForm.newPassword) {
      throw new Error('请填写旧密码和新密码')
    }
    if (profileForm.newPassword !== profileForm.confirmPassword) {
      throw new Error('两次新密码不一致')
    }

    await callAction(
      'set_passwd',
      {
        username: session.username,
        old_passwd: profileForm.oldPassword,
        new_passwd: profileForm.newPassword,
      },
      true,
    )

    profileForm.oldPassword = ''
    profileForm.newPassword = ''
    profileForm.confirmPassword = ''
    pushToast('密码更新成功', 'success')
  })
}

const setupTwoFa = async () => {
  await runBusy(async () => {
    const response = await callAction('setup_2fa', { method: 'totp' }, true)
    twoFaState.setupSecret = response.data.secret || ''
    twoFaState.setupUri = response.data.provisioning_uri || ''
    twoFaState.setupBackupCodes = response.data.backup_codes || []
    twoFaState.verifyToken = ''
    pushToast('2FA 配置已生成', 'success')
  })
}

const verifyTwoFaSetup = async () => {
  await runBusy(async () => {
    if (!twoFaState.verifyToken) {
      throw new Error('请输入验证码')
    }
    await callAction('validate_2fa', { token: twoFaState.verifyToken }, true)
    twoFaState.setupSecret = ''
    twoFaState.setupUri = ''
    twoFaState.setupBackupCodes = []
    twoFaState.verifyToken = ''
    await loadProfileSettings()
    pushToast('2FA 已启用', 'success')
  })
}

const disableTwoFa = async () => {
  await runBusy(async () => {
    if (!twoFaState.disablePassword) {
      throw new Error('请输入登录密码')
    }
    await callAction('disable_2fa', { password: twoFaState.disablePassword }, true)
    twoFaState.disablePassword = ''
    await loadProfileSettings()
    pushToast('2FA 已关闭', 'warning')
  })
}

const changeTab = async (tab) => {
  if (tab === activeTab.value) return
  activeTab.value = tab

  if (tab === 'files') {
    await runSafe(loadFileList)
    await runSafe(loadRecycle)
  } else if (tab === 'profile') {
    await runSafe(loadProfileSettings)
    if (!avatarImageUrl.value) {
      warmupAvatarInBackground(120)
    }
  }
}

const logout = () => {
  session.username = ''
  session.token = ''
  session.nickname = ''
  session.exp = 0
  session.avatarId = ''
  session.permissions = []
  session.groups = []
  activeTab.value = 'dashboard'
  selectedRecentFileId.value = ''
  revokeUrl(avatarImageUrl.value)
  avatarImageUrl.value = ''
  closeAvatarCrop()
  showLogModal.value = false
  loginStage.need2fa = false
  loginStage.needForcePassword = false
  pushLog('已退出登录', 'info')
  pushToast('已退出登录', 'info')
}

const runSafe = async (fn) => {
  try {
    await fn()
  } catch (error) {
    pushLog(error.message || '操作失败', 'danger')
    pushToast(error.message || '操作失败', 'danger')
  }
}

const GLOW_CLAMP_MARGIN = 24
const DEFORM_SCALE_MAX = 0.025

const clampGlow = (val, min, max) => Math.max(min - GLOW_CLAMP_MARGIN, Math.min(max + GLOW_CLAMP_MARGIN, val))

const updateNavGlowPos = (e) => {
  if (!navRef.value) return
  const rect = navRef.value.getBoundingClientRect()
  const rawX = e.clientX - rect.left
  const rawY = e.clientY - rect.top
  navGlow.x = clampGlow(rawX, 0, rect.width)
  navGlow.y = clampGlow(rawY, 0, rect.height)

  let dx = 0
  let dy = 0
  if (e.clientX < rect.left) dx = (e.clientX - rect.left) / rect.width
  else if (e.clientX > rect.right) dx = (e.clientX - rect.right) / rect.width
  if (e.clientY < rect.top) dy = (e.clientY - rect.top) / rect.height
  else if (e.clientY > rect.bottom) dy = (e.clientY - rect.bottom) / rect.height

  const absDx = Math.min(Math.abs(dx), 1)
  const absDy = Math.min(Math.abs(dy), 1)
  navDeform.sx = 1 + absDx * DEFORM_SCALE_MAX
  navDeform.sy = 1 + absDy * DEFORM_SCALE_MAX
  navDeform.ox = dx < 0 ? '100%' : dx > 0 ? '0%' : '50%'
  navDeform.oy = dy < 0 ? '100%' : dy > 0 ? '0%' : '50%'
}

const onNavGlowMove = (e) => {
  if (!navGlow.pressing) return
  updateNavGlowPos(e)
}

const onNavGlowUp = () => {
  navGlow.pressing = false
  navGlow.active = false
  navDeform.sx = 1
  navDeform.sy = 1
  document.removeEventListener('pointermove', onNavGlowMove)
  document.removeEventListener('pointerup', onNavGlowUp)
}

const onNavPointerDown = (e) => {
  updateNavGlowPos(e)
  navGlow.active = true
  navGlow.pressing = true
  document.addEventListener('pointermove', onNavGlowMove)
  document.addEventListener('pointerup', onNavGlowUp)
}

const navTransform = computed(() => {
  if (navDeform.sx === 1 && navDeform.sy === 1) return ''
  return `scale(${navDeform.sx}, ${navDeform.sy})`
})

const navOrigin = computed(() => `${navDeform.ox} ${navDeform.oy}`)

onMounted(() => {
  const savedThemeMode = localStorage.getItem(THEME_MODE_KEY)
  if (savedThemeMode === 'dark' || savedThemeMode === 'light') {
    themeMode.value = savedThemeMode
  }

  expandServicePillThenAutoCollapse()
  runSafe(async () => {
    await connectWs()
    await loadServerInfo()
  })
})

onBeforeUnmount(() => {
  if (servicePillTimer) clearTimeout(servicePillTimer)
  document.removeEventListener('pointermove', onNavGlowMove)
  document.removeEventListener('pointerup', onNavGlowUp)
})
</script>

<template>
  <div class="page" :class="{ 'theme-dark': isDarkMode }">
    <div class="bg-glow"></div>

    <Transition name="shell-switch" mode="out-in">
      <main v-if="!isAuthed" key="auth" class="login-shell">
        <section class="auth-panel centered" :class="{ expanded: authMode === 'register' }">
        <h1>登录 Thesis Drive</h1>
        <p class="subtitle">个人网盘入口</p>

        <div class="mode-switch" :class="authMode">
          <span class="mode-thumb"></span>
          <button :class="{ active: authMode === 'login' }" @click="authMode = 'login'">登录</button>
          <button :class="{ active: authMode === 'register' }" @click="authMode = 'register'">注册</button>
        </div>

        <Transition name="auth-form" mode="out-in">
          <div v-if="authMode === 'login'" key="login" class="form-grid">
            <label>
              用户名
              <input v-model="auth.username" type="text" placeholder="请输入用户名" />
            </label>
            <label>
              密码
              <input v-model="auth.password" type="password" placeholder="请输入密码" />
            </label>
            <button :disabled="busy" @click="runSafe(handleLogin)">立即登录</button>
          </div>

          <div v-else key="register" class="form-grid">
            <label>
              用户名
              <input v-model="registerForm.username" type="text" placeholder="注册用户名" />
            </label>
            <label>
              昵称
              <input v-model="registerForm.nickname" type="text" placeholder="昵称（可选）" />
            </label>
            
            <label>
              密码
              <input v-model="registerForm.password" type="password" placeholder="注册密码" />
            </label>
            <label>
              确认密码
              <input v-model="registerForm.confirmPassword" type="password" placeholder="再次输入密码" />
            </label>
            <button :disabled="busy" @click="runSafe(submitRegister)">提交注册</button>
            <p class="tip">注册后默认加入 user 用户组。</p>
          </div>
        </Transition>
        </section>
      </main>

      <main v-else key="drive" class="drive-shell">
        <header class="topbar">
        <div>
          <h2>Thesis Drive</h2>
          
        </div>
      </header>
      <div class="scroll-blur-mask" aria-hidden="true"></div>
      <div class="topbar-spacer" aria-hidden="true"></div>

      <Transition name="page-switch" mode="out-in">
        <section v-if="activeTab === 'dashboard'" key="dashboard" class="dashboard-layout">
          <div class="dashboard-top">
            <article class="card capacity-card">
              <div>
                <h3>容量占用</h3>
                
                <p class="capacity-numbers">{{ formatGB(dashboardUsedBytes) }} / {{ formatGB(drive.totalBytes) }}</p>
                <small>剩余 {{ formatGB(dashboardRemainingBytes) }}</small>
              </div>
              <div class="capacity-ring">
                <svg viewBox="0 0 100 100" class="ring-svg" aria-hidden="true">
                  <circle class="ring-track" cx="50" cy="50" :r="ringRadius" />
                  <circle
                    class="ring-progress"
                    cx="50"
                    cy="50"
                    :r="ringRadius"
                    :stroke-dasharray="ringLength"
                    :stroke-dashoffset="ringOffset"
                  />
                </svg>
                <div class="capacity-ring-inner">
                  <strong>{{ dashboardUsagePercent }}%</strong>
                  <small>已使用</small>
                </div>
              </div>
            </article>

            <article class="card category-card">
              <h3>文件分类</h3>
              <ul class="category-list">
                <li @click="runSafe(() => jumpToCategory('album'))">
                  <span>相册</span>
                  <strong>{{ categoryStats.album }}</strong>
                </li>
                <li @click="runSafe(() => jumpToCategory('video'))">
                  <span>视频</span>
                  <strong>{{ categoryStats.video }}</strong>
                </li>
                <li @click="runSafe(() => jumpToCategory('music'))">
                  <span>音乐</span>
                  <strong>{{ categoryStats.music }}</strong>
                </li>
                <li @click="runSafe(() => jumpToCategory('document'))">
                  <span>文档</span>
                  <strong>{{ categoryStats.document }}</strong>
                </li>
              </ul>
            </article>

            <div class="dashboard-side">
              <article class="card profile-quick-card" @click="runSafe(() => changeTab('profile'))">
                <div class="profile-quick-main">
                  <div class="avatar-wrap">
                    <img v-if="avatarImageUrl" :src="avatarImageUrl" alt="avatar" class="avatar-image avatar-image-lg" @error="onAvatarImageError" />
                    <span v-else class="avatar-lg">{{ (session.nickname || session.username).slice(0, 1).toUpperCase() }}</span>
                  </div>
                  <div class="profile-quick-meta">
                    <strong>{{ session.nickname || session.username }}</strong>
                    <small>{{ session.username }}</small>
                    <div class="group-badges">
                      <span
                        v-for="g in session.groups"
                        :key="g"
                        :class="groupTagClass(g)"
                      >
                        {{ g.toUpperCase() }}
                      </span>
                      <span v-if="!session.groups.length" class="group-pill role-other">NO GROUP</span>
                    </div>
                  </div>
                </div>
              </article>

              <article class="card sync-mini-card">
                <p>上次同步：{{ formatDateTime(lastSyncAt) }}</p>
                <p>会话到期：{{ formatDateTime(session.exp) }}</p>
                <button class="ghost" @click="runSafe(loadDriveOverview)">立即同步</button>
              </article>
            </div>
          </div>

          <article class="card recent-card">
            <h3>最近文件</h3>
            <p class="subtitle">选中某一条后，在该行右侧显示操作图标。</p>
            <ul class="recent-list">
              <li
                v-for="f in recentDisplayFiles"
                :key="f.id"
                class="recent-row"
                :class="{ selected: selectedRecentFileId === f.id }"
                @click="selectRecentFile(f)"
              >
                <div class="recent-main">
                  <strong>{{ f.title }}</strong>
                  <p class="subtitle">{{ formatMB(Number(f.size || 0)) }}</p>
                </div>

                <div class="recent-right">
                  <small class="recent-time">{{ formatDateTime(f.last_modified) }}</small>
                  <div v-if="selectedRecentFileId === f.id" class="recent-inline-actions" @click.stop>
                    <button class="ghost icon-btn" title="预览" @click="runSafe(() => handleRecentAction(f, 'preview'))">⧉</button>
                    <button class="ghost icon-btn" title="下载" @click="runSafe(() => handleRecentAction(f, 'download'))">⤓</button>
                    <button class="ghost icon-btn" title="分享" @click="runSafe(() => handleRecentAction(f, 'share'))">↗</button>
                    <button class="ghost icon-btn" title="回收站" @click="runSafe(() => handleRecentAction(f, 'recycle'))">⌫</button>
                  </div>
                </div>
              </li>
            </ul>
          </article>
        </section>

        <section v-else-if="activeTab === 'files'" key="files" class="card split tall">
          <div>
            <h3>文件列表</h3>
            <div class="file-category-filter">
              <button class="ghost" :class="{ active: fileCategory === 'all' }" @click="fileCategory = 'all'; filePage = 1">全部</button>
              <button class="ghost" :class="{ active: fileCategory === 'album' }" @click="fileCategory = 'album'; filePage = 1">相册</button>
              <button class="ghost" :class="{ active: fileCategory === 'video' }" @click="fileCategory = 'video'; filePage = 1">视频</button>
              <button class="ghost" :class="{ active: fileCategory === 'music' }" @click="fileCategory = 'music'; filePage = 1">音乐</button>
              <button class="ghost" :class="{ active: fileCategory === 'document' }" @click="fileCategory = 'document'; filePage = 1">文档</button>
            </div>
            <div class="tools">
              <input
                v-model="fileQuery"
                type="text"
                placeholder="按文件名快速筛选"
                @input="filePage = 1"
              />
              <select v-model="fileSortKey" @change="filePage = 1">
                <option value="title">按名称</option>
                <option value="size">按大小</option>
                <option value="last_modified">按时间</option>
              </select>
              <select v-model="fileSortOrder" @change="filePage = 1">
                <option value="asc">升序</option>
                <option value="desc">降序</option>
              </select>
            </div>

            <p class="subtitle">已全部加载，共 {{ filteredFiles.length }} 个</p>

            <div class="file-table" role="table" aria-label="文件列表">
              <div class="file-table-head" role="row">
                <div class="col-name"><input type="checkbox" aria-label="全选" />文件</div>
                <div class="col-size">大小</div>
                <div class="col-type">类型</div>
                <div class="col-time">修改时间</div>
              </div>

              <div v-if="pagedFiles.length" class="file-table-body">
                <div v-for="file in pagedFiles" :key="file.id" class="file-row" role="row">
                  <div class="col-name">
                    <input type="checkbox" :aria-label="`选择 ${file.title}`" />
                    <span class="file-glyph">{{ fileTypeLabel(file.title) === '图片' ? '🖼' : fileTypeLabel(file.title) === '视频' ? '🎬' : fileTypeLabel(file.title) === '音频' ? '🎵' : '📄' }}</span>
                    <span class="file-title">{{ file.title }}</span>
                    <div class="file-hover-actions" @click.stop>
                      <button class="ghost icon-btn" title="预览" @click="runSafe(() => handleFileAction(file, 'preview'))">⧉</button>
                      <button class="ghost icon-btn" title="下载" @click="runSafe(() => handleFileAction(file, 'download'))">⤓</button>
                      <button class="ghost icon-btn" title="分享" @click="runSafe(() => handleFileAction(file, 'share'))">↗</button>
                      <button class="ghost icon-btn" title="回收站" @click="runSafe(() => handleFileAction(file, 'recycle'))">⌫</button>
                    </div>
                  </div>
                  <div class="col-size">{{ formatMB(Number(file.size || 0)) }}</div>
                  <div class="col-type">{{ fileTypeLabel(file.title) }}</div>
                  <div class="col-time">{{ formatDateTime(file.last_modified) }}</div>
                </div>
              </div>

              <div v-else class="file-empty">没有匹配文件</div>
            </div>

            <div class="pager">
              <button class="ghost" :disabled="filePage <= 1" @click="goPrevPage">上一页</button>
              <span>第 {{ filePage }} / {{ totalFilePages }} 页</span>
              <button class="ghost" :disabled="filePage >= totalFilePages" @click="goNextPage">下一页</button>
            </div>
          </div>

          <div>
            <h3>目录</h3>
            <ul class="simple-list">
              <li v-for="folder in drive.folders" :key="folder.id">{{ folder.name }}</li>
              <li v-if="!drive.folders.length">暂无目录</li>
            </ul>

            <h3>回收站目录</h3>
            <ul class="simple-list">
              <li v-for="folder in drive.recycleFolders" :key="folder.id">
                <div>
                  <strong>{{ folder.name }}</strong>
                </div>
                <div class="row-actions">
                  <button class="ghost" @click="runSafe(() => restoreRecycleFolder(folder.id))">恢复</button>
                  <button class="danger" @click="runSafe(() => purgeRecycleFolder(folder.id))">永久删除</button>
                </div>
              </li>
              <li v-if="!drive.recycleFolders.length">暂无已删除目录</li>
            </ul>

            <h3>回收站文件</h3>
            <ul class="simple-list">
              <li v-for="doc in drive.recycleFiles" :key="doc.id">
                <div>
                  <strong>{{ doc.title }}</strong>
                </div>
                <div class="row-actions">
                  <button class="ghost" @click="runSafe(() => restoreRecycleDoc(doc.id))">恢复</button>
                  <button class="danger" @click="runSafe(() => purgeRecycleDoc(doc.id))">永久删除</button>
                </div>
              </li>
              <li v-if="!drive.recycleFiles.length">暂无已删除文件</li>
            </ul>
          </div>
        </section>

        <section v-else-if="activeTab === 'transfer'" key="transfer" class="card tall">
          <h3>传输</h3>
          <p class="subtitle">显示最近任务与系统传输相关消息。</p>
          <ul class="simple-list">
            <li v-for="row in transferLogs" :key="row.id">
              <div>
                <strong>{{ row.text }}</strong>
                <p class="subtitle">{{ row.time }}</p>
              </div>
            </li>
            <li v-if="!transferLogs.length">暂无传输记录</li>
          </ul>
        </section>

        <section v-else key="profile" class="profile-grid">
          <article class="card">
            <div class="profile-top">
              <button class="avatar-edit-trigger" @click="openAvatarUpload">
                <img v-if="avatarImageUrl" :src="avatarImageUrl" alt="avatar" class="avatar-image avatar-image-lg" @error="onAvatarImageError" />
                <span v-else class="avatar-lg">{{ (session.nickname || session.username).slice(0, 1).toUpperCase() }}</span>
                <span class="avatar-edit-mask">修改头像</span>
              </button>
              <div>
                <h3>{{ session.nickname || session.username }}</h3>
                <p class="subtitle">基础资料</p>
              </div>
            </div>
            <p>用户名：{{ session.username }}</p>
            <label>
              昵称
              <input v-model="profileForm.nickname" type="text" placeholder="输入新的昵称" />
            </label>
            <button :disabled="busy" @click="runSafe(submitNickname)">保存昵称</button>
          </article>

          <article class="card">
            <h3>密码设置</h3>
            <label>
              旧密码
              <input v-model="profileForm.oldPassword" type="password" placeholder="当前登录密码" />
            </label>
            <label>
              新密码
              <input v-model="profileForm.newPassword" type="password" placeholder="输入新密码" />
            </label>
            <label>
              确认新密码
              <input v-model="profileForm.confirmPassword" type="password" placeholder="再次输入新密码" />
            </label>
            <button :disabled="busy" @click="runSafe(submitPasswordUpdate)">更新密码</button>
          </article>

          <article class="card">
            <h3>两步验证 (2FA)</h3>
            <p>状态：{{ twoFaState.enabled ? '已开启' : '未开启' }}</p>
            <small v-if="twoFaState.enabled">备份码数量：{{ twoFaState.backupCodesCount }}</small>
            <button v-if="!twoFaState.enabled" :disabled="busy" @click="runSafe(setupTwoFa)">开始配置 2FA</button>

            <div v-if="twoFaState.setupUri" class="profile-subsection">
              <p class="subtitle">请将以下链接导入你的验证器：</p>
              <code class="inline-code">{{ twoFaState.setupUri }}</code>
              <p class="subtitle">手动密钥：{{ twoFaState.setupSecret }}</p>
              <label>
                验证码
                <input v-model="twoFaState.verifyToken" type="text" placeholder="输入 6 位验证码" />
              </label>
              <button :disabled="busy" @click="runSafe(verifyTwoFaSetup)">确认启用</button>
            </div>

            <div v-if="twoFaState.enabled" class="profile-subsection">
              <label>
                登录密码
                <input v-model="twoFaState.disablePassword" type="password" placeholder="用于关闭 2FA" />
              </label>
              <button class="ghost" :disabled="busy" @click="runSafe(disableTwoFa)">关闭 2FA</button>
            </div>
          </article>

          <article class="card">
            <h3>账号信息</h3>
            <p>Token 到期：{{ formatDateTime(session.exp) }}</p>
            <p>权限数量：{{ session.permissions.length }}</p>
            <p>所在组：{{ session.groups.join(', ') || '-' }}</p>
            <div class="profile-subsection theme-toggle-row">
              <p class="subtitle">界面主题：{{ isDarkMode ? '暗夜模式' : '日间模式' }}</p>
              <button class="ghost" @click="toggleThemeMode">{{ isDarkMode ? '切换到日间' : '切换到暗夜' }}</button>
            </div>
            <div class="profile-subsection theme-toggle-row">
              <p class="subtitle">运行日志</p>
              <button class="ghost" @click="showLogModal = true">查看日志</button>
            </div>
            <button class="logout-btn" @click="logout">退出登录</button>
          </article>
        </section>
        </Transition>
      </main>
    </Transition>

    <div class="toast-layer" aria-live="polite">
      <TransitionGroup name="drop" tag="div" class="toast-stack">
        <div v-for="t in toasts" :key="t.id" class="toast" :class="t.type">
          <img class="toast-icon" :src="toastIconByType[t.type] || toastWarningIcon" alt="" />
          <p class="toast-text">{{ t.text }}</p>
        </div>
      </TransitionGroup>
    </div>

    <div class="service-pill left" :class="{ online: isConnected, offline: !isConnected, collapsed: servicePillCollapsed }">
      <span class="dot"></span>
      <span class="service-label">{{ isConnected ? 'Service Online' : 'Service Offline' }}</span>
    </div>

    <div v-if="showLogModal" class="overlay" @click.self="showLogModal = false">
      <div class="modal-card">
        <div class="modal-head">
          <h3>运行日志</h3>
          <button class="ghost" @click="showLogModal = false">关闭</button>
        </div>
        <div class="log-list">
          <article v-for="row in logs" :key="row.id" class="log-item">
            <p>[{{ row.time }}] {{ row.text }}</p>
          </article>
          <p v-if="!logs.length">暂无日志</p>
        </div>
      </div>
    </div>

    <div v-if="loginStage.need2fa" class="overlay" @click.self="loginStage.need2fa = false">
      <div class="modal-card small">
        <h3>两步验证</h3>
        <p>登录需要 2FA 验证码。</p>
        <input v-model="twoFaForm.token" type="text" placeholder="6 位验证码" />
        <div class="actions">
          <button class="ghost" @click="loginStage.need2fa = false">取消</button>
          <button :disabled="busy" @click="runSafe(handleLogin)">继续登录</button>
        </div>
      </div>
    </div>

    <div v-if="loginStage.needForcePassword" class="overlay" @click.self="loginStage.needForcePassword = false">
      <div class="modal-card small">
        <h3>需要强制改密</h3>
        <p>服务端要求先修改密码后再登录。</p>
        <label>
          新密码
          <input v-model="forcePasswordForm.newPassword" type="password" />
        </label>
        <label>
          确认新密码
          <input v-model="forcePasswordForm.confirmPassword" type="password" />
        </label>
        <div class="actions">
          <button class="ghost" @click="loginStage.needForcePassword = false">取消</button>
          <button :disabled="busy" @click="runSafe(submitForcePassword)">提交改密</button>
        </div>
      </div>
    </div>

    <Transition name="nav-rise">
      <nav
        v-if="isAuthed"
        ref="navRef"
        class="bottom-nav"
        :class="{ 'nav-pressing': navGlow.pressing }"
        :style="{ '--glow-x': navGlow.x + 'px', '--glow-y': navGlow.y + 'px', transform: navTransform, transformOrigin: navOrigin }"
        @pointerdown.prevent="onNavPointerDown"
      >
        <span class="nav-glass-sheen"></span>
        <span
          class="nav-glow"
          :class="{ active: navGlow.active, pressing: navGlow.pressing }"
        ></span>
        <button
          v-for="item in navItems"
          :key="item.key"
          class="nav-btn"
          :class="{ active: activeTab === item.key }"
          @click="runSafe(() => changeTab(item.key))"
        >
          <img :src="item.icon" :alt="item.label" />
          <span class="nav-label">{{ item.label }}</span>
        </button>
      </nav>
    </Transition>

    <button
      v-if="isAuthed"
      class="theme-fab"
      :aria-label="isDarkMode ? '切换到日间模式' : '切换到暗夜模式'"
      @click="toggleThemeMode"
    >
      {{ isDarkMode ? '☀' : '☾' }}
    </button>

    <input
      ref="avatarFileInput"
      type="file"
      accept="image/*"
      class="hidden-input"
      @change="onAvatarFileChange"
    />

    <div v-if="showAvatarCropModal" class="overlay" @click.self="closeAvatarCrop">
      <div class="modal-card small">
        <h3>上传头像</h3>
        <p class="subtitle">裁剪后会同步到服务器并更新个人头像。</p>

        <div class="avatar-crop-preview">
          <img :src="avatarDraft.sourceUrl" alt="avatar-crop" :style="avatarCropStyle" />
        </div>

        <label>
          缩放
          <input v-model.number="avatarDraft.zoom" type="range" min="1" max="3" step="0.01" />
        </label>
        <label>
          左右移动
          <input v-model.number="avatarDraft.offsetX" type="range" min="-1" max="1" step="0.01" />
        </label>
        <label>
          上下移动
          <input v-model.number="avatarDraft.offsetY" type="range" min="-1" max="1" step="0.01" />
        </label>

        <div class="actions">
          <button class="ghost" @click="closeAvatarCrop">取消</button>
          <button :disabled="busy" @click="runSafe(submitAvatarUpload)">裁剪并同步</button>
        </div>
      </div>
    </div>
  </div>
</template>
