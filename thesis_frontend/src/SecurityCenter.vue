<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import MarkdownView from './components/MarkdownView.vue'
import { CfmsClient } from './services/cfmsClient'
import { TransferClient } from './services/transferClient'

const SESSION_STORAGE_KEY = 'thesis-session'
const STATUS_ORDER = ['pending', 'rejected', 'duplicate', 'fixing', 'passed']
const STATUS_LABELS = {
  pending: '审核中',
  rejected: '已拒绝',
  duplicate: '重复',
  fixing: '修复中',
  passed: '已通过',
}
const SEVERITY_LABELS = {
  low: '低危',
  medium: '中危',
  high: '高危',
  critical: '严重',
}

function resolveWsUrl() {
  const configured = String(import.meta.env.VITE_WS_URL || '').trim()
  if (configured && configured.toLowerCase() !== 'auto') return configured
  if (typeof window === 'undefined') return 'wss://127.0.0.1/ws'
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws`
}

const adminPath = typeof window !== 'undefined'
  && (window.location.pathname.replace(/\/+$/, '') || '/') === '/admin/src'
const busy = ref(false)
const loading = ref(true)
const redirecting = ref(false)
const isDarkMode = ref(false)
const pageError = ref('')
const toast = reactive({ show: false, text: '', tone: 'info' })
let toastTimer = null

const session = reactive({
  username: '',
  token: '',
  nickname: '',
  exp: 0,
  groups: [],
  permissions: [],
  homeDirectoryId: null,
  diskQuota: 0,
  diskUsed: 0,
})

const personalTab = ref('submit')
const myReports = ref([])
const leaderboard = ref([])
const myRanking = ref({ rank: null, score: 0, accepted_count: 0, report_count: 0 })
const scoreRules = reactive({ low: 10, medium: 30, high: 60, critical: 100 })
const selectedReport = ref(null)
const reportModalOpen = ref(false)
const selectedFiles = ref([])
const uploadProgress = ref('')
const reportForm = reactive({
  title: '',
  category: '访问控制',
  severity: 'medium',
  affectedUrl: 'https://thesis.n1n3bird.top/',
  descriptionMd: '## 漏洞描述\n\n请说明问题是什么，以及可能造成的影响。\n\n## 复现步骤\n\n1. \n2. \n3. \n\n## 修复建议\n\n',
})

const adminTab = ref('review')
const adminReports = ref([])
const adminCounts = reactive(Object.fromEntries(STATUS_ORDER.map((status) => [status, 0])))
const adminFilter = ref('')
const selectedAdminReport = ref(null)
const reviewForm = reactive({ status: 'pending', noteMd: '' })

const isAuthed = computed(() => Boolean(session.username && session.token))
const isSysop = computed(() => session.groups.includes('sysop'))
const remainingQuota = computed(() => Math.max(0, Number(session.diskQuota || 0) - Number(session.diskUsed || 0)))
const selectedFileBytes = computed(() => selectedFiles.value.reduce((total, file) => total + file.size, 0))
const visibleAdminReports = computed(() => adminFilter.value
  ? adminReports.value.filter((report) => report.status_code === adminFilter.value)
  : adminReports.value)

const notify = (text, tone = 'info') => {
  toast.text = text
  toast.tone = tone
  toast.show = true
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.show = false }, 3200)
}

const client = new CfmsClient({
  url: resolveWsUrl(),
})
const transferClient = new TransferClient({ controlClient: client })
const authHeader = () => ({ username: session.username, token: session.token })

const callAction = async (action, data = {}, useAuth = true) => {
  const response = await client.request(action, data, useAuth ? authHeader() : null)
  if (Number(response?.code) >= 400 && Number(response?.code) !== 202) {
    const error = new Error(response?.message || `${action} 请求失败`)
    error.code = Number(response.code)
    throw error
  }
  return response
}

const loadCapabilities = async () => {
  const response = await callAction('server_info', {}, false)
  const serverInfo = client.applyServerInfo(response)
  transferClient.setCapabilities(serverInfo.capabilities)
}

const restoreSession = () => {
  try {
    const saved = JSON.parse(sessionStorage.getItem(SESSION_STORAGE_KEY) || 'null')
    if (!saved?.token || !saved?.username || Number(saved.exp || 0) <= Date.now() / 1000) {
      sessionStorage.removeItem(SESSION_STORAGE_KEY)
      return
    }
    Object.assign(session, saved)
  } catch {
    sessionStorage.removeItem(SESSION_STORAGE_KEY)
  }
}

const redirectToDriveLogin = () => {
  redirecting.value = true
  const nextPath = adminPath ? '/admin/src' : '/security'
  window.location.replace(`/?next=${encodeURIComponent(nextPath)}`)
}

const reloadPage = () => window.location.reload()

const loadMyReports = async () => {
  const response = await callAction('src_list_my_reports')
  myReports.value = response.data?.reports || []
}

const loadLeaderboard = async () => {
  const response = await callAction('src_get_leaderboard')
  leaderboard.value = response.data?.leaderboard || []
  myRanking.value = response.data?.me || { rank: null, score: 0, accepted_count: 0, report_count: 0 }
  Object.assign(scoreRules, response.data?.score_rules || {})
}

const loadAdminReports = async () => {
  const response = await callAction('src_list_reports', {})
  adminReports.value = response.data?.reports || []
  Object.assign(adminCounts, response.data?.counts || {})
}

const loadAuthenticatedView = async () => {
  if (adminPath) {
    if (isSysop.value) await loadAdminReports()
    return
  }
  await Promise.all([loadMyReports(), loadLeaderboard()])
}

const logout = async () => {
  try {
    if (isAuthed.value) await callAction('logout')
  } catch {
    // The browser session is still cleared if the server is temporarily unavailable.
  }
  sessionStorage.removeItem(SESSION_STORAGE_KEY)
  Object.assign(session, {
    username: '', token: '', nickname: '', exp: 0, groups: [], permissions: [],
    homeDirectoryId: null, diskQuota: 0, diskUsed: 0,
  })
  myReports.value = []
  leaderboard.value = []
  myRanking.value = { rank: null, score: 0, accepted_count: 0, report_count: 0 }
  adminReports.value = []
  selectedReport.value = null
  selectedAdminReport.value = null
  redirectToDriveLogin()
}

const onFilesSelected = (event) => {
  selectedFiles.value = Array.from(event.target.files || [])
  event.target.value = ''
}

const removeSelectedFile = (index) => {
  selectedFiles.value = selectedFiles.value.filter((_file, fileIndex) => fileIndex !== index)
}

const uploadAttachment = async (file, index, total) => {
  uploadProgress.value = `正在上传附件 ${index + 1}/${total}：${file.name}`
  const marker = typeof crypto?.randomUUID === 'function'
    ? crypto.randomUUID().slice(0, 8)
    : Math.random().toString(16).slice(2, 10)
  const storedTitle = `SRC-${marker}-${file.name}`.slice(0, 255)
  const created = await callAction('create_document', {
    folder_id: session.homeDirectoryId,
    title: storedTitle,
    inherit_parent: true,
  })
  const taskId = created.data?.task_data?.task_id
  if (!taskId || !created.data?.document_id) throw new Error('附件上传任务创建失败')
  const result = transferClient.supportsHttpTransfer()
    ? await transferClient.uploadFile(taskId, file, { auth: authHeader() })
    : await client.uploadFileByTask(taskId, file, authHeader())
  if (result?.code >= 400) throw new Error(result.message || '附件上传失败')
  return { document_id: created.data.document_id, filename: file.name.slice(0, 255) }
}

const submitReport = async () => {
  if (!reportForm.title.trim() || !reportForm.descriptionMd.trim()) {
    notify('标题和报告正文不能为空', 'danger')
    return
  }
  if (session.diskQuota && selectedFileBytes.value > remainingQuota.value) {
    notify('附件会超过当前 200 MiB 账号空间', 'danger')
    return
  }
  busy.value = true
  try {
    const attachments = []
    for (let index = 0; index < selectedFiles.value.length; index += 1) {
      attachments.push(await uploadAttachment(selectedFiles.value[index], index, selectedFiles.value.length))
    }
    uploadProgress.value = '正在登记漏洞报告…'
    const response = await callAction('src_create_report', {
      title: reportForm.title.trim(),
      category: reportForm.category,
      severity: reportForm.severity,
      affected_url: reportForm.affectedUrl.trim() || null,
      description_md: reportForm.descriptionMd,
      attachments,
    })
    selectedFiles.value = []
    reportForm.title = ''
    reportForm.severity = 'medium'
    reportForm.descriptionMd = '## 漏洞描述\n\n\n## 复现步骤\n\n1. \n2. \n3. \n\n## 修复建议\n\n'
    await Promise.all([loadMyReports(), loadLeaderboard()])
    selectedReport.value = response.data?.report || null
    reportModalOpen.value = Boolean(selectedReport.value)
    personalTab.value = 'mine'
    notify('报告已进入审核队列', 'success')
  } catch (error) {
    notify(error.message || '提交失败', 'danger')
  } finally {
    uploadProgress.value = ''
    busy.value = false
  }
}

const openReport = async (report, forAdmin = false) => {
  busy.value = true
  try {
    const response = await callAction('src_get_report', { report_id: report.id })
    if (forAdmin) {
      selectedAdminReport.value = response.data.report
      reviewForm.status = response.data.report.status_code
      reviewForm.noteMd = ''
    } else {
      selectedReport.value = response.data.report
      reportModalOpen.value = true
    }
  } catch (error) {
    notify(error.message || '报告读取失败', 'danger')
  } finally {
    busy.value = false
  }
}

const downloadAttachment = async (attachment) => {
  busy.value = true
  try {
    const response = await callAction('src_prepare_attachment_download', { attachment_id: attachment.id })
    const taskId = response.data?.task_data?.task_id
    if (!taskId) throw new Error('附件下载任务创建失败')
    if (transferClient.supportsHttpTransfer()) {
      await transferClient.nativeDownload(taskId, response.data.filename, { auth: authHeader() })
    } else {
      const result = await client.downloadFileByTask(taskId, { strictIntegrity: true }, authHeader())
      const blob = new Blob([result.fileBytes])
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = response.data.filename
      anchor.click()
      URL.revokeObjectURL(url)
    }
    notify('附件下载已开始', 'success')
  } catch (error) {
    notify(error.message || '附件下载失败', 'danger')
  } finally {
    busy.value = false
  }
}

const setAdminFilter = (status) => {
  adminFilter.value = adminFilter.value === status ? '' : status
}

const updateReportStatus = async () => {
  if (!selectedAdminReport.value) return
  busy.value = true
  try {
    const response = await callAction('src_update_report_status', {
      report_id: selectedAdminReport.value.id,
      status: reviewForm.status,
      note_md: reviewForm.noteMd.trim() || null,
    })
    selectedAdminReport.value = response.data.report
    reviewForm.noteMd = ''
    await loadAdminReports()
    notify('审核结论已记录', 'success')
  } catch (error) {
    notify(error.message || '状态更新失败', 'danger')
  } finally {
    busy.value = false
  }
}

const statusClass = (status) => `status-${STATUS_ORDER.includes(status) ? status : 'pending'}`
const formatDate = (timestamp) => timestamp
  ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(timestamp * 1000)
  : '—'
const formatBytes = (bytes) => {
  const value = Number(bytes || 0)
  if (value < 1024) return `${value} B`
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / 1024 ** 2).toFixed(1)} MiB`
}

onMounted(async () => {
  isDarkMode.value = localStorage.getItem('thesis-theme-mode') === 'dark'
  if (typeof document !== 'undefined') {
    document.title = adminPath ? 'SRC 管理 · Thesis' : 'SRC · Thesis'
  }
  restoreSession()
  if (!isAuthed.value) {
    redirectToDriveLogin()
    return
  }
  try {
    await client.connect()
    await loadCapabilities()
    await loadAuthenticatedView()
  } catch (error) {
    if (Number(error?.code) === 401 || String(error?.message || '').startsWith('401')) {
      sessionStorage.removeItem(SESSION_STORAGE_KEY)
      redirectToDriveLogin()
      return
    }
    pageError.value = error.message || 'SRC 暂时无法连接'
  } finally {
    if (!redirecting.value) loading.value = false
  }
})

onBeforeUnmount(() => {
  clearTimeout(toastTimer)
  client.disconnect()
})
</script>

<template>
  <div class="security-shell page" :class="{ 'theme-dark': isDarkMode }">
    <div class="bg-glow" aria-hidden="true"></div>
    <header class="topbar">
      <a class="wordmark" href="/security" aria-label="Thesis Security">
        <strong>Thesis Drive</strong>
        <span>Security</span>
      </a>
      <div class="topbar-right">
        <a v-if="isSysop && !adminPath" class="quiet-button" href="/admin/src">管理</a>
        <a v-if="adminPath" class="quiet-button" href="/security">报告台</a>
        <a class="quiet-button" href="/">网盘</a>
        <button class="quiet-button" type="button" @click="logout">退出</button>
      </div>
    </header>
    <div class="scroll-blur-mask" aria-hidden="true"></div>
    <div class="topbar-spacer" aria-hidden="true"></div>

    <main v-if="loading || redirecting" class="state-page">
      <span class="loader-mark"></span>
    </main>

    <main v-else-if="pageError" class="state-page error-page">
      <h1>加载失败</h1>
      <button class="primary-button" @click="reloadPage">重试</button>
    </main>

    <main v-else-if="adminPath && !isSysop" class="state-page denied-page">
      <span class="stamp">403</span>
      <h1>需要管理员权限</h1>
      <a class="primary-button" href="/security">返回报告台</a>
    </main>

    <main v-else-if="adminPath" class="admin-main">
      <div class="page-heading admin-heading">
        <h1>报告审查</h1>
        <div class="heading-stat">
          <strong>{{ adminReports.length }}</strong>
          <span>份报告</span>
        </div>
      </div>

      <nav class="section-tabs" aria-label="SRC 管理设置">
        <button :class="{ active: adminTab === 'review' }" @click="adminTab = 'review'">报告审查</button>
        <button :class="{ active: adminTab === 'workflow' }" @click="adminTab = 'workflow'">流程编排</button>
      </nav>

      <section v-if="adminTab === 'review'" class="pipeline" aria-label="报告状态筛选">
        <button
          v-for="status in STATUS_ORDER"
          :key="status"
          class="pipeline-step"
          :class="[{ selected: adminFilter === status }, statusClass(status)]"
          @click="setAdminFilter(status)"
        >
          <strong>{{ STATUS_LABELS[status] }}</strong>
          <b>{{ adminCounts[status] || 0 }}</b>
        </button>
      </section>

      <section v-if="adminTab === 'workflow'" class="workflow-notes" aria-label="报告状态编排">
        <div v-for="(status, index) in STATUS_ORDER" :key="status" class="workflow-step">
          <strong>{{ STATUS_LABELS[status] }}</strong>
          <span>{{ adminCounts[status] || 0 }}</span>
          <b v-if="index < STATUS_ORDER.length - 1">→</b>
        </div>
      </section>

      <section v-else class="review-workspace">
        <aside class="report-queue">
          <div class="queue-head">
            <h2>{{ adminFilter ? STATUS_LABELS[adminFilter] : '全部报告' }}</h2>
            <button v-if="adminFilter" class="quiet-button" @click="adminFilter = ''">清除筛选</button>
          </div>
          <button
            v-for="report in visibleAdminReports"
            :key="report.id"
            class="queue-item"
            :class="{ active: selectedAdminReport?.id === report.id }"
            @click="openReport(report, true)"
          >
            <span class="severity-flag" :class="`severity-${report.severity}`">{{ SEVERITY_LABELS[report.severity] }}</span>
            <strong>{{ report.title }}</strong>
            <small>{{ report.reporter_username }} · {{ formatDate(report.updated_at) }}</small>
            <span class="status-chip" :class="statusClass(report.status_code)">{{ report.status }}</span>
          </button>
          <p v-if="!visibleAdminReports.length" class="empty-copy">这个队列目前是空的。</p>
        </aside>

        <article v-if="selectedAdminReport" class="review-sheet">
          <div class="sheet-meta">
            <span>#{{ selectedAdminReport.id.slice(0, 8) }}</span>
            <span>{{ selectedAdminReport.reporter_username }}</span>
            <span>{{ formatDate(selectedAdminReport.created_at) }}</span>
          </div>
          <h2>{{ selectedAdminReport.title }}</h2>
          <div class="report-badges">
            <span>{{ selectedAdminReport.category }}</span>
            <span>{{ SEVERITY_LABELS[selectedAdminReport.severity] }}</span>
            <span :class="statusClass(selectedAdminReport.status_code)">{{ selectedAdminReport.status }}</span>
          </div>
          <a v-if="selectedAdminReport.affected_url" class="affected-link" :href="selectedAdminReport.affected_url" target="_blank" rel="noreferrer noopener">{{ selectedAdminReport.affected_url }}</a>
          <MarkdownView class="report-markdown" :source="selectedAdminReport.description_md" />

          <div v-if="selectedAdminReport.attachments?.length" class="attachment-block">
            <h3>报告附件</h3>
            <button v-for="attachment in selectedAdminReport.attachments" :key="attachment.id" :disabled="busy || !attachment.available" @click="downloadAttachment(attachment)">
              <span>↧</span><b>{{ attachment.filename }}</b><small>{{ formatBytes(attachment.size) }}</small>
            </button>
          </div>

          <div class="review-decision">
            <h3>审核处理</h3>
            <label>
              <span>下一状态</span>
              <select v-model="reviewForm.status">
                <option v-for="status in STATUS_ORDER" :key="status" :value="status">{{ STATUS_LABELS[status] }}</option>
              </select>
            </label>
            <label>
              <span>审计备注（Markdown）</span>
              <textarea v-model="reviewForm.noteMd" rows="5" placeholder="说明判断依据、修复分派或回归结果…"></textarea>
            </label>
            <button class="primary-button" :disabled="busy" @click="updateReportStatus">{{ busy ? '正在保存…' : '保存审核记录' }}</button>
          </div>

          <div class="timeline">
            <h3>处理时间线</h3>
            <div v-for="event in [...(selectedAdminReport.events || [])].reverse()" :key="event.id" class="timeline-item">
              <span class="timeline-dot"></span>
              <div>
                <b>{{ event.to_status }}</b>
                <small>{{ event.actor_username || '已注销账号' }} · {{ formatDate(event.created_at) }}</small>
                <MarkdownView v-if="event.note_md" :source="event.note_md" />
              </div>
            </div>
          </div>
        </article>
        <article v-else class="review-placeholder">
          <h2>选择报告</h2>
        </article>
      </section>
    </main>

    <main v-else class="reporter-main">
      <section class="reporter-hero">
        <h1>漏洞报告</h1>
        <div class="hero-stats">
          <div class="rank-note">
            <span>排名</span>
            <strong>{{ myRanking.rank ? `#${myRanking.rank}` : '—' }}</strong>
          </div>
          <div class="rank-note">
            <span>积分</span>
            <strong>{{ myRanking.score }}</strong>
          </div>
          <div class="quota-note">
            <span>剩余空间</span>
            <strong>{{ formatBytes(remainingQuota) }}</strong>
          </div>
        </div>
      </section>

      <nav class="section-tabs reporter-tabs">
        <button :class="{ active: personalTab === 'submit' }" @click="personalTab = 'submit'">提交报告</button>
        <button :class="{ active: personalTab === 'mine' }" @click="personalTab = 'mine'">我的报告 <b>{{ myReports.length }}</b></button>
        <button :class="{ active: personalTab === 'ranking' }" @click="personalTab = 'ranking'">积分榜</button>
      </nav>

      <section v-if="personalTab === 'submit'" class="submit-grid">
        <form class="report-form" @submit.prevent="submitReport">
          <div class="form-heading">
            <h2>新建报告</h2>
          </div>
          <label class="wide-field">
            <span>报告标题</span>
            <input v-model="reportForm.title" maxlength="160" placeholder="一句话说明问题和影响" />
          </label>
          <div class="field-row">
            <label>
              <span>漏洞类型</span>
              <select v-model="reportForm.category">
                <option>访问控制</option><option>身份认证</option><option>文件上传</option>
                <option>信息泄露</option><option>业务逻辑</option><option>其他</option>
              </select>
            </label>
            <label>
              <span>风险等级</span>
              <select v-model="reportForm.severity">
                <option value="low">低危</option><option value="medium">中危</option>
                <option value="high">高危</option><option value="critical">严重</option>
              </select>
            </label>
          </div>
          <label class="wide-field">
            <span>受影响地址</span>
            <input v-model="reportForm.affectedUrl" maxlength="2048" placeholder="https://thesis.n1n3bird.top/..." />
          </label>
          <label class="wide-field markdown-field">
            <span>报告正文 <em>Markdown</em></span>
            <textarea v-model="reportForm.descriptionMd" rows="16" maxlength="50000"></textarea>
          </label>
          <div class="file-field">
            <span>证据附件</span>
            <label class="file-picker">
              <input type="file" multiple @change="onFilesSelected" />
              <span>＋ 选择附件</span>
            </label>
          </div>
          <ul v-if="selectedFiles.length" class="selected-files">
            <li v-for="(file, index) in selectedFiles" :key="`${file.name}-${file.lastModified}`">
              <span>{{ file.name }}</span><small>{{ formatBytes(file.size) }}</small>
              <button type="button" aria-label="移除附件" @click="removeSelectedFile(index)">×</button>
            </li>
          </ul>
          <div class="submit-row">
            <p>{{ uploadProgress || `已选附件 ${formatBytes(selectedFileBytes)}` }}</p>
            <button class="primary-button" type="submit" :disabled="busy">{{ busy ? '正在提交…' : '提交审核' }}</button>
          </div>
        </form>

        <aside class="markdown-preview">
          <h2>{{ reportForm.title || '报告预览' }}</h2>
          <div class="report-badges">
            <span>{{ reportForm.category }}</span>
            <span>{{ SEVERITY_LABELS[reportForm.severity] }}</span>
          </div>
          <MarkdownView :source="reportForm.descriptionMd" />
        </aside>
      </section>

      <section v-else-if="personalTab === 'mine'" class="my-reports">
        <div class="list-heading">
          <h2>我的报告</h2>
          <button class="quiet-button" :disabled="busy" @click="loadMyReports">刷新</button>
        </div>
        <button v-for="report in myReports" :key="report.id" class="my-report-row" @click="openReport(report)">
          <span class="severity-flag" :class="`severity-${report.severity}`">{{ SEVERITY_LABELS[report.severity] }}</span>
          <span class="report-main"><strong>{{ report.title }}</strong><small>#{{ report.id.slice(0, 8) }} · {{ report.category }} · {{ formatDate(report.updated_at) }}</small></span>
          <span v-if="report.attachment_count" class="attachment-count">⌕ {{ report.attachment_count }}</span>
          <span class="status-chip" :class="statusClass(report.status_code)">{{ report.status }}</span>
          <span class="row-arrow">→</span>
        </button>
        <div v-if="!myReports.length" class="empty-state">
          <h3>暂无报告</h3>
          <button class="quiet-button" @click="personalTab = 'submit'">新建报告</button>
        </div>
      </section>

      <section v-else class="leaderboard-panel">
        <div class="leaderboard-intro">
          <h2>积分榜</h2>
          <button class="quiet-button" :disabled="busy" @click="loadLeaderboard">刷新</button>
        </div>
        <div class="score-rules" aria-label="SRC 积分规则">
          <div v-for="severity in ['low', 'medium', 'high', 'critical']" :key="severity">
            <span class="severity-flag" :class="`severity-${severity}`">{{ SEVERITY_LABELS[severity] }}</span>
            <strong>+{{ scoreRules[severity] }}</strong>
          </div>
        </div>
        <div class="ranking-head"><span>排名</span><span>研究员</span><span>通过 / 提交</span><span>积分</span></div>
        <div
          v-for="entry in leaderboard"
          :key="entry.username"
          class="ranking-row"
          :class="{ current: entry.username === session.username }"
        >
          <strong class="ranking-number">{{ entry.rank }}</strong>
          <span class="ranking-person"><b>{{ entry.nickname }}</b><small>@{{ entry.username }}</small></span>
          <span>{{ entry.accepted_count }} / {{ entry.report_count }}</span>
          <strong>{{ entry.score }}</strong>
        </div>
        <div v-if="!leaderboard.length" class="empty-state">
          <h3>暂无排名</h3>
        </div>
      </section>
    </main>

    <div v-if="reportModalOpen && selectedReport" class="modal-backdrop" @click.self="reportModalOpen = false">
      <article class="report-modal">
        <button class="modal-close" aria-label="关闭" @click="reportModalOpen = false">×</button>
        <div class="sheet-meta"><span>#{{ selectedReport.id.slice(0, 8) }}</span><span>{{ formatDate(selectedReport.created_at) }}</span></div>
        <h2>{{ selectedReport.title }}</h2>
        <div class="report-badges"><span>{{ selectedReport.category }}</span><span>{{ SEVERITY_LABELS[selectedReport.severity] }}</span><span :class="statusClass(selectedReport.status_code)">{{ selectedReport.status }}</span></div>
        <a v-if="selectedReport.affected_url" class="affected-link" :href="selectedReport.affected_url" target="_blank" rel="noreferrer noopener">{{ selectedReport.affected_url }}</a>
        <MarkdownView class="report-markdown" :source="selectedReport.description_md" />
        <div v-if="selectedReport.attachments?.length" class="attachment-block">
          <h3>附件</h3>
          <button v-for="attachment in selectedReport.attachments" :key="attachment.id" :disabled="busy || !attachment.available" @click="downloadAttachment(attachment)"><span>↧</span><b>{{ attachment.filename }}</b><small>{{ formatBytes(attachment.size) }}</small></button>
        </div>
        <div class="timeline compact-timeline">
          <h3>处理进度</h3>
          <div v-for="event in [...(selectedReport.events || [])].reverse()" :key="event.id" class="timeline-item">
            <span class="timeline-dot"></span><div><b>{{ event.to_status }}</b><small>{{ formatDate(event.created_at) }}</small><MarkdownView v-if="event.note_md" :source="event.note_md" /></div>
          </div>
        </div>
      </article>
    </div>

    <transition name="toast">
      <div v-if="toast.show" class="toast-message" :class="`tone-${toast.tone}`">{{ toast.text }}</div>
    </transition>
  </div>
</template>

<style scoped>
:global(body) { margin: 0; background: #f3f0e9; color: #1f2927; }
:global(*) { box-sizing: border-box; }
:global(button), :global(input), :global(select), :global(textarea) { font: inherit; }
.security-shell { min-height: 100vh; background: #f3f0e9; color: #202a28; font-family: "Microsoft YaHei", "PingFang SC", sans-serif; }
.topbar { position: sticky; z-index: 20; top: 0; display: flex; align-items: center; justify-content: space-between; min-height: 74px; padding: 0 4.5vw; border-bottom: 1px solid #cbc6bb; background: rgba(243, 240, 233, .96); backdrop-filter: blur(10px); }
.wordmark { display: flex; align-items: center; gap: 13px; color: inherit; text-decoration: none; }
.wordmark-thesis { font: italic 700 1.5rem/1 Georgia, serif; letter-spacing: -.04em; }
.wordmark-rule { width: 1px; height: 25px; background: #9d988d; }
.wordmark-center { font-size: .82rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.topbar-right { display: flex; align-items: center; gap: 10px; }
.connection-dot { width: 7px; height: 7px; border-radius: 50%; background: #a65c48; box-shadow: 0 0 0 4px rgba(166, 92, 72, .12); }
.connection-dot.online { background: #2d7468; box-shadow: 0 0 0 4px rgba(45, 116, 104, .12); }
.connection-label { color: #69716e; font-size: .74rem; }
.text-link, .back-link { color: #215f57; font-size: .82rem; text-underline-offset: 3px; }
.account-button { display: grid; padding: 7px 10px 7px 14px; border: 0; border-left: 1px solid #cbc6bb; background: transparent; color: inherit; text-align: left; cursor: pointer; }
.account-button span { font-weight: 700; }
.account-button small { color: #777d79; font-size: .68rem; }
.state-page { display: grid; min-height: calc(100vh - 75px); place-content: center; justify-items: center; padding: 40px; text-align: center; }
.loader-mark { display: grid; width: 48px; height: 48px; place-content: center; border: 1px solid #202a28; font: italic 700 1.5rem Georgia, serif; animation: turn 1.8s steps(4) infinite; }
@keyframes turn { to { transform: rotate(360deg); } }
.login-layout { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(360px, .75fr); min-height: calc(100vh - 75px); }
.login-intro { display: flex; flex-direction: column; justify-content: center; padding: 8vw; border-right: 1px solid #cbc6bb; background: #233532; color: #f7f3e9; }
.eyebrow, .card-kicker { margin: 0 0 14px; color: #a85f4a; font: 700 .7rem/1.3 ui-monospace, Consolas, monospace; letter-spacing: .17em; }
.login-intro .eyebrow { color: #d6aa75; }
.login-intro h1, .reporter-hero h1, .page-heading h1 { margin: 0; font: 500 clamp(2.6rem, 5.5vw, 5.8rem)/.98 Georgia, "Noto Serif SC", serif; letter-spacing: -.055em; }
.intro-copy { max-width: 620px; margin: 30px 0 46px; color: #cad2cf; font-size: 1rem; line-height: 1.9; }
.promise-list { display: grid; max-width: 620px; margin: 0; border-top: 1px solid rgba(255, 255, 255, .22); }
.promise-list div { display: grid; grid-template-columns: 55px 1fr; padding: 14px 0; border-bottom: 1px solid rgba(255, 255, 255, .14); }
.promise-list dt { color: #d6aa75; font: .75rem ui-monospace, Consolas, monospace; }
.promise-list dd { margin: 0; }
.login-card { align-self: center; width: min(420px, calc(100% - 50px)); margin: 60px auto; padding: 38px; border: 1px solid #bdb7ac; background: #fbf9f4; box-shadow: 10px 12px 0 #ded9ce; }
.login-card h2 { margin: 0; font: 600 2rem Georgia, "Noto Serif SC", serif; }
.login-card > p:not(.card-kicker, .inline-error) { margin: 12px 0 30px; color: #6c726f; font-size: .9rem; }
.login-card form { display: grid; gap: 19px; }
label { display: grid; gap: 8px; color: #3b4542; font-size: .8rem; font-weight: 700; }
input, select, textarea { width: 100%; border: 1px solid #bdb7ac; border-radius: 3px; outline: none; background: #fffefb; color: #202a28; transition: border-color .16s, box-shadow .16s; }
input, select { min-height: 44px; padding: 0 12px; }
textarea { resize: vertical; padding: 12px; line-height: 1.7; }
input:focus, select:focus, textarea:focus { border-color: #27685f; box-shadow: 0 0 0 3px rgba(39, 104, 95, .1); }
.primary-button { display: inline-flex; align-items: center; justify-content: center; min-height: 44px; padding: 0 22px; border: 1px solid #1d4f49; border-radius: 3px; background: #215f57; color: #fff; font-weight: 700; text-decoration: none; cursor: pointer; }
.primary-button:hover { background: #174a43; }
.primary-button:disabled, button:disabled { cursor: not-allowed; opacity: .55; }
.primary-button.full { width: 100%; margin-top: 5px; }
.back-link { display: inline-block; margin-top: 24px; }
.inline-error { color: #9d3e32; font-size: .8rem; }
.denied-page .stamp { padding: 8px 13px; border: 2px solid #a94b3b; color: #a94b3b; font: 800 1.35rem ui-monospace, Consolas, monospace; transform: rotate(-3deg); }
.denied-page h1 { margin: 25px 0 8px; font: 600 2.3rem Georgia, serif; }
.denied-page p { max-width: 560px; color: #68706d; line-height: 1.8; }
.admin-main, .reporter-main { width: min(1500px, 92vw); margin: 0 auto; padding: 55px 0 80px; }
.page-heading { display: flex; align-items: end; justify-content: space-between; gap: 30px; padding-bottom: 38px; border-bottom: 1px solid #bdb7ac; }
.page-heading h1 { font-size: clamp(2.6rem, 5vw, 5rem); }
.page-heading p:last-child { max-width: 760px; margin: 18px 0 0; color: #66706c; line-height: 1.8; }
.heading-stat { display: grid; min-width: 150px; padding: 15px 18px; border-left: 4px solid #b55340; background: #e8e2d7; }
.heading-stat strong { font: 600 2.2rem Georgia, serif; }
.heading-stat span { color: #707672; font-size: .78rem; }
.section-tabs { display: flex; gap: 28px; margin: 26px 0 22px; border-bottom: 1px solid #c8c2b7; }
.section-tabs button { position: relative; padding: 10px 2px 13px; border: 0; background: transparent; color: #686f6c; cursor: pointer; }
.section-tabs button.active { color: #1f2927; font-weight: 800; }
.section-tabs button.active::after { position: absolute; right: 0; bottom: -1px; left: 0; height: 3px; background: #b55340; content: ''; }
.section-tabs b { display: inline-grid; min-width: 20px; height: 20px; place-items: center; margin-left: 5px; border-radius: 50%; background: #ddd7cc; font-size: .7rem; }
.pipeline { display: grid; grid-template-columns: repeat(5, 1fr); border: 1px solid #bdb7ac; background: #f9f7f1; }
.pipeline-step { display: grid; grid-template-columns: auto 1fr auto; gap: 6px 10px; min-height: 124px; padding: 17px; border: 0; border-right: 1px solid #d0cabf; background: transparent; color: inherit; text-align: left; cursor: pointer; }
.pipeline-step:last-child { border-right: 0; }
.pipeline-step:hover, .pipeline-step.selected { background: #ebe6dc; }
.pipeline-step.selected { box-shadow: inset 0 -4px #b55340; }
.step-index { color: #9a9d98; font: .66rem ui-monospace, Consolas, monospace; }
.pipeline-step strong { font-size: .95rem; }
.pipeline-step b { font: 600 1.55rem Georgia, serif; }
.pipeline-step small { grid-column: 1 / -1; color: #767c78; font-size: .72rem; line-height: 1.5; }
.workflow-notes { display: grid; grid-template-columns: .8fr 1.2fr; gap: 60px; margin-top: 28px; padding: 42px; border: 1px solid #bdb7ac; background: #233532; color: #f5f1e8; }
.workflow-notes h2 { max-width: 380px; margin: 0; font: 500 2.3rem/1.15 Georgia, serif; }
.workflow-notes ol { margin: 0; padding: 0; list-style: none; counter-reset: steps; }
.workflow-notes li { display: grid; grid-template-columns: 105px 1fr; gap: 20px; padding: 15px 0; border-bottom: 1px solid rgba(255,255,255,.15); }
.workflow-notes li b { color: #e0b37d; }
.workflow-notes li span { color: #ccd3d0; line-height: 1.6; }
.review-workspace { display: grid; grid-template-columns: minmax(300px, .72fr) minmax(0, 1.45fr); min-height: 640px; margin-top: 28px; border: 1px solid #bdb7ac; background: #fbf9f4; }
.report-queue { border-right: 1px solid #c9c3b8; }
.queue-head, .list-heading { display: flex; align-items: center; justify-content: space-between; padding: 24px; border-bottom: 1px solid #d5cfc4; }
.queue-head h2, .list-heading h2 { margin: 0; font: 600 1.55rem Georgia, serif; }
.quiet-button { padding: 7px 10px; border: 1px solid #aca69b; border-radius: 3px; background: transparent; color: #40504c; cursor: pointer; }
.queue-item { position: relative; display: grid; width: 100%; grid-template-columns: auto 1fr auto; gap: 7px 10px; padding: 17px 19px; border: 0; border-bottom: 1px solid #ddd7cc; background: transparent; color: inherit; text-align: left; cursor: pointer; }
.queue-item:hover, .queue-item.active { background: #eee9df; }
.queue-item.active::before { position: absolute; top: 0; bottom: 0; left: 0; width: 4px; background: #28695f; content: ''; }
.queue-item strong { align-self: center; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.queue-item small { grid-column: 2 / -1; color: #858984; font-size: .68rem; }
.severity-flag { align-self: start; padding: 3px 5px; border: 1px solid currentColor; font-size: .63rem; font-weight: 800; }
.severity-low { color: #48706a; }.severity-medium { color: #9b6a22; }.severity-high { color: #a34e37; }.severity-critical { color: #8d2930; background: #f4dcda; }
.status-chip, .report-badges span { display: inline-flex; align-items: center; justify-content: center; padding: 4px 7px; border: 1px solid #c5bfb4; border-radius: 2px; background: #f7f3ec; color: #525b58; font-size: .68rem; font-weight: 800; white-space: nowrap; }
.status-pending { color: #8b6122 !important; }.status-rejected { color: #8f4036 !important; }.status-duplicate { color: #6c6574 !important; }.status-fixing { color: #28695f !important; }.status-passed { color: #245d3e !important; }
.review-sheet, .report-modal { position: relative; padding: clamp(28px, 4vw, 58px); overflow: hidden; }
.sheet-meta { display: flex; flex-wrap: wrap; gap: 10px 22px; color: #777d79; font: .7rem ui-monospace, Consolas, monospace; text-transform: uppercase; }
.review-sheet > h2, .report-modal > h2 { max-width: 850px; margin: 18px 0 12px; font: 600 clamp(1.9rem, 3vw, 3rem)/1.15 Georgia, "Noto Serif SC", serif; }
.report-badges { display: flex; flex-wrap: wrap; gap: 7px; margin: 12px 0 18px; }
.affected-link { display: block; max-width: 100%; overflow: hidden; color: #216158; font: .75rem ui-monospace, Consolas, monospace; text-overflow: ellipsis; white-space: nowrap; }
.report-markdown { margin-top: 30px; padding-top: 22px; border-top: 1px solid #d1cbc0; }
.attachment-block { margin-top: 30px; padding-top: 20px; border-top: 1px solid #d1cbc0; }
.attachment-block h3, .timeline h3, .review-decision h3 { margin: 0 0 12px; font: 600 1.15rem Georgia, serif; }
.attachment-block button { display: grid; width: 100%; grid-template-columns: 24px 1fr auto; gap: 8px; align-items: center; padding: 10px 0; border: 0; border-bottom: 1px dashed #cdc7bb; background: transparent; color: #245d56; text-align: left; cursor: pointer; }
.attachment-block small { color: #7b807d; }
.review-decision { display: grid; gap: 15px; margin-top: 38px; padding: 24px; border-left: 4px solid #b55340; background: #e9e4da; }
.review-decision .primary-button { justify-self: start; }
.timeline { margin-top: 36px; }
.timeline-item { position: relative; display: grid; grid-template-columns: 18px 1fr; gap: 8px; padding: 0 0 24px; }
.timeline-item::before { position: absolute; top: 9px; bottom: -2px; left: 4px; width: 1px; background: #c5bfb4; content: ''; }
.timeline-item:last-child::before { display: none; }
.timeline-dot { position: relative; z-index: 1; width: 9px; height: 9px; margin-top: 5px; border: 2px solid #f9f7f1; border-radius: 50%; background: #b55340; box-shadow: 0 0 0 1px #b55340; }
.timeline-item div { display: grid; gap: 4px; }
.timeline-item small { color: #858984; font-size: .7rem; }
.review-placeholder { display: grid; place-content: center; justify-items: center; padding: 50px; color: #747b77; text-align: center; }
.review-placeholder > span { font: 3rem Georgia, serif; transform: rotate(-8deg); }
.review-placeholder h2 { margin: 12px 0 6px; color: #35413e; font: 600 1.7rem Georgia, serif; }
.empty-copy { padding: 30px; color: #858984; text-align: center; }
.reporter-hero { display: grid; grid-template-columns: 1fr auto; gap: 60px; align-items: end; padding: 30px 0 44px; border-bottom: 1px solid #bdb7ac; }
.reporter-hero h1 { max-width: 900px; font-size: clamp(2.7rem, 5.6vw, 5.8rem); }
.reporter-hero > div > p:last-child { max-width: 760px; margin: 22px 0 0; color: #65706c; line-height: 1.8; }
.hero-stats { display: grid; min-width: 230px; }
.quota-note, .rank-note { display: grid; padding: 16px 22px; color: #f3efe6; }
.quota-note { border-top: 1px solid #52635f; background: #233532; }
.rank-note { border-top: 3px solid #b55340; background: #2d403c; }
.quota-note span, .rank-note span { color: #d5aa76; font: .65rem ui-monospace, Consolas, monospace; letter-spacing: .15em; }
.quota-note strong, .rank-note strong { margin: 7px 0 2px; font: 500 1.75rem Georgia, serif; }
.quota-note small, .rank-note small { color: #bfc8c4; }
.submit-grid { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(330px, .75fr); gap: 25px; align-items: start; }
.report-form, .markdown-preview, .my-reports, .leaderboard-panel { border: 1px solid #bdb7ac; background: #fbf9f4; }
.report-form { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; padding: clamp(25px, 3vw, 42px); }
.form-heading { display: flex; grid-column: 1 / -1; align-items: center; justify-content: space-between; padding-bottom: 19px; border-bottom: 1px solid #d0cabf; }
.form-heading h2, .markdown-preview h2 { margin: 0; font: 600 1.8rem Georgia, serif; }
.form-heading > span { color: #898c87; font-size: .72rem; }
.wide-field, .file-field, .selected-files, .submit-row { grid-column: 1 / -1; }
.field-row { display: contents; }
.markdown-field em { margin-left: 6px; color: #9a674a; font: normal .65rem ui-monospace, Consolas, monospace; }
.markdown-field textarea { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .82rem; }
.file-field { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 14px 0; border-top: 1px dashed #c3bdb2; border-bottom: 1px dashed #c3bdb2; }
.file-field > div { display: grid; gap: 3px; }
.file-field > div > span { font-size: .8rem; font-weight: 800; }
.file-field small { color: #7a807c; font-size: .7rem; }
.file-picker input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.file-picker span { display: inline-flex; padding: 8px 11px; border: 1px solid #9f9a90; border-radius: 3px; cursor: pointer; }
.selected-files { display: grid; gap: 4px; margin: 0; padding: 0; list-style: none; }
.selected-files li { display: grid; grid-template-columns: 1fr auto auto; gap: 12px; align-items: center; padding: 8px 10px; background: #eee9df; font-size: .76rem; }
.selected-files small { color: #737975; }
.selected-files button { border: 0; background: transparent; color: #984638; font-size: 1rem; cursor: pointer; }
.submit-row { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding-top: 3px; }
.submit-row p { margin: 0; color: #757b77; font-size: .73rem; }
.markdown-preview { position: sticky; top: 98px; max-height: calc(100vh - 120px); padding: 28px; overflow: auto; }
.preview-head { display: flex; align-items: center; gap: 12px; margin-bottom: 22px; color: #9a674a; font: .65rem ui-monospace, Consolas, monospace; letter-spacing: .15em; }
.preview-head i { flex: 1; height: 1px; background: #cfc9be; }
.my-reports { min-height: 480px; }
.my-report-row { display: grid; width: 100%; grid-template-columns: auto 1fr auto auto 25px; gap: 16px; align-items: center; padding: 18px 24px; border: 0; border-bottom: 1px solid #d8d2c7; background: transparent; color: inherit; text-align: left; cursor: pointer; }
.my-report-row:hover { background: #eee9df; }
.report-main { display: grid; gap: 5px; min-width: 0; }
.report-main strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.report-main small, .attachment-count { color: #7f847f; font-size: .7rem; }
.row-arrow { font: 1.3rem Georgia, serif; }
.empty-state { display: grid; place-content: center; justify-items: center; min-height: 340px; color: #727a76; text-align: center; }
.empty-state > span { display: grid; width: 44px; height: 44px; place-content: center; border: 1px solid #2c6d62; border-radius: 50%; color: #2c6d62; }
.empty-state h3 { margin: 15px 0 2px; color: #34413d; font: 600 1.4rem Georgia, serif; }
.leaderboard-panel { min-height: 480px; padding: clamp(24px, 3vw, 40px); }
.leaderboard-intro { display: flex; align-items: start; justify-content: space-between; gap: 24px; padding-bottom: 24px; border-bottom: 1px solid #d0cabf; }
.leaderboard-intro h2 { margin: 0; font: 600 2rem Georgia, "Noto Serif SC", serif; }
.leaderboard-intro p:not(.card-kicker) { max-width: 660px; margin: 10px 0 0; color: #6e7672; line-height: 1.7; }
.score-rules { display: grid; grid-template-columns: repeat(4, 1fr); margin: 24px 0; border: 1px solid #d0cabf; }
.score-rules div { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px; border-right: 1px solid #d0cabf; }
.score-rules div:last-child { border-right: 0; }
.ranking-head, .ranking-row { display: grid; grid-template-columns: 70px minmax(180px, 1fr) 140px 80px; gap: 16px; align-items: center; }
.ranking-head { padding: 10px 16px; border-bottom: 1px solid #aaa499; color: #7b817d; font: .66rem ui-monospace, Consolas, monospace; letter-spacing: .08em; }
.ranking-row { min-height: 70px; padding: 12px 16px; border-bottom: 1px solid #ddd7cc; }
.ranking-row.current { border-left: 4px solid #b55340; background: #eee9df; }
.ranking-row > span:nth-child(3), .ranking-row > strong:last-child { text-align: right; }
.ranking-number { color: #9a674a; font: 500 1.6rem Georgia, serif; }
.ranking-person { display: grid; gap: 3px; }
.ranking-person small { color: #858a86; font-size: .68rem; }
.modal-backdrop { position: fixed; z-index: 50; inset: 0; display: grid; place-items: center; padding: 30px; background: rgba(25, 34, 32, .68); }
.report-modal { width: min(900px, 100%); max-height: 90vh; overflow: auto; border: 1px solid #aaa499; background: #fbf9f4; box-shadow: 14px 16px 0 rgba(20, 28, 26, .3); }
.modal-close { position: absolute; top: 14px; right: 16px; width: 36px; height: 36px; border: 0; background: transparent; color: #394440; font-size: 1.6rem; cursor: pointer; }
.compact-timeline { padding-top: 20px; border-top: 1px solid #d1cbc0; }
.toast-message { position: fixed; z-index: 80; right: 24px; bottom: 24px; max-width: min(420px, calc(100vw - 48px)); padding: 13px 17px; border: 1px solid #27332f; background: #27332f; color: #fff; box-shadow: 6px 7px 0 rgba(25,33,31,.18); font-size: .82rem; }
.tone-success { border-color: #28695f; background: #28695f; }.tone-danger { border-color: #963f34; background: #963f34; }.tone-warning { border-color: #956626; background: #956626; }
.toast-enter-active, .toast-leave-active { transition: opacity .18s, transform .18s; }.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateY(8px); }
@media (max-width: 980px) {
  .login-layout, .submit-grid, .review-workspace, .workflow-notes { grid-template-columns: 1fr; }
  .login-intro { min-height: 520px; border-right: 0; }
  .pipeline { grid-template-columns: 1fr 1fr; }
  .pipeline-step { border-bottom: 1px solid #d0cabf; }
  .report-queue { max-height: 480px; overflow: auto; border-right: 0; border-bottom: 1px solid #c9c3b8; }
  .markdown-preview { position: static; max-height: none; }
}
@media (max-width: 680px) {
  .topbar { min-height: 64px; padding: 0 16px; }
  .wordmark-center, .connection-label, .text-link { display: none; }
  .admin-main, .reporter-main { width: min(100% - 28px, 1500px); padding-top: 30px; }
  .reporter-hero, .page-heading { grid-template-columns: 1fr; align-items: start; }
  .reporter-hero { display: grid; gap: 28px; }
  .hero-stats { width: 100%; }
  .pipeline { grid-template-columns: 1fr; }
  .pipeline-step { min-height: 90px; border-right: 0; }
  .report-form { grid-template-columns: 1fr; padding: 22px 17px; }
  .field-row { display: grid; grid-column: 1 / -1; gap: 20px; }
  .form-heading, .file-field, .submit-row { align-items: flex-start; flex-direction: column; }
  .my-report-row { grid-template-columns: auto 1fr auto; padding: 15px; }
  .my-report-row .status-chip { grid-column: 2; justify-self: start; }
  .attachment-count { display: none; }
  .row-arrow { grid-row: 1 / 3; grid-column: 3; }
  .score-rules { grid-template-columns: 1fr 1fr; }
  .score-rules div:nth-child(2) { border-right: 0; }
  .score-rules div:nth-child(-n + 2) { border-bottom: 1px solid #d0cabf; }
  .ranking-head, .ranking-row { grid-template-columns: 42px 1fr 58px; gap: 10px; }
  .ranking-head span:nth-child(3), .ranking-row > span:nth-child(3) { display: none; }
  .login-card { padding: 28px 22px; box-shadow: 7px 8px 0 #ded9ce; }
  .login-intro { padding: 70px 28px; }
  .modal-backdrop { padding: 12px; }
  .report-modal { max-height: 94vh; padding: 35px 22px; }
}
@media (prefers-reduced-motion: reduce) { .loader-mark { animation: none; } * { scroll-behavior: auto !important; } }

/* Match the Thesis Drive visual system. */
:global(body) { background: var(--page-bg-base); color: var(--text); }
.security-shell {
  min-height: 100vh;
  padding-bottom: 80px;
  color: var(--text);
  background: var(--page-bg-base);
  background-image: var(--page-bg-gradient);
  font-family: 'GoogleSans', 'HarmonyOS_Sans_SC', 'Segoe UI', sans-serif;
}
.topbar {
  position: fixed;
  z-index: 42;
  top: 24px;
  left: 50%;
  display: flex;
  width: min(1120px, calc(100vw - 40px));
  min-height: 54px;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 14px;
  border: 0;
  background: transparent;
  transform: translateX(-50%);
  backdrop-filter: none;
}
.wordmark { display: grid; gap: 1px; color: var(--text); text-decoration: none; }
.wordmark strong { font-size: 24px; line-height: 1.05; letter-spacing: -.03em; }
.wordmark span { color: var(--muted); font-size: 13px; line-height: 1.1; }
.topbar-right { display: flex; align-items: center; gap: 8px; }
.topbar .quiet-button {
  display: inline-flex;
  min-height: 38px;
  align-items: center;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text);
  box-shadow: 0 8px 20px rgba(92, 112, 151, .1);
  font-weight: 500;
  text-decoration: none;
}
.topbar .quiet-button:hover { border-color: var(--accent-soft-border); background: var(--btn-ghost-hover); }
.topbar-spacer { height: 134px; }
.state-page { min-height: calc(100vh - 134px); color: var(--muted); }
.loader-mark {
  width: 38px;
  height: 38px;
  border: 4px solid var(--progress-track);
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: turn .8s linear infinite;
}
.state-page h1 { margin: 0 0 20px; color: var(--text); font-size: 28px; font-weight: 700; line-height: 1.2; }
.admin-main, .reporter-main { position: relative; z-index: 1; width: min(1120px, calc(100vw - 40px)); margin: 0 auto; padding: 0 0 40px; }
.page-heading, .reporter-hero {
  display: flex;
  min-height: 112px;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 18px 0 24px;
  border: 0;
}
.page-heading h1, .reporter-hero h1 { margin: 0; font-size: clamp(28px, 4vw, 38px); font-weight: 700; line-height: 1.1; letter-spacing: -.03em; }
.heading-stat, .rank-note, .quota-note {
  display: grid;
  min-width: 112px;
  gap: 4px;
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: var(--surface);
  color: var(--text);
  box-shadow: var(--shadow);
}
.heading-stat { border-left: 1px solid var(--line); }
.heading-stat strong, .rank-note strong, .quota-note strong { margin: 0; font-size: 24px; font-weight: 700; line-height: 1.1; }
.heading-stat span, .rank-note span, .quota-note span { color: var(--muted); font-size: 12px; font-weight: 500; line-height: 1.2; letter-spacing: 0; }
.hero-stats { display: grid; min-width: 360px; grid-template-columns: repeat(3, minmax(105px, 1fr)); gap: 10px; }
.section-tabs { display: flex; gap: 8px; margin: 0 0 14px; padding: 6px; border: 1px solid var(--line); border-radius: 14px; background: var(--surface); box-shadow: var(--shadow); }
.section-tabs button { flex: 1; padding: 9px 14px; border: 0; border-radius: 10px; background: transparent; color: var(--muted); }
.section-tabs button.active { background: var(--btn-primary); color: var(--btn-primary-text); font-weight: 700; }
.section-tabs button.active::after { display: none; }
.section-tabs b { background: var(--surface-soft); }
.report-form, .markdown-preview, .my-reports, .leaderboard-panel, .review-workspace, .pipeline, .workflow-notes {
  border: 1px solid var(--line);
  border-radius: var(--radius-xl);
  background: var(--surface);
  box-shadow: var(--shadow);
}
.submit-grid { gap: 14px; }
.report-form { gap: 16px; padding: 24px; }
.form-heading, .queue-head, .list-heading, .leaderboard-intro { border-color: var(--line); }
.form-heading h2, .markdown-preview h2, .queue-head h2, .list-heading h2, .leaderboard-intro h2 { margin: 0; font-size: 22px; font-weight: 700; line-height: 1.2; }
label { color: var(--muted); font-weight: 600; }
input, select, textarea {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--surface-soft);
  color: var(--text);
}
input:focus, select:focus, textarea:focus { border-color: var(--brand); box-shadow: 0 0 0 3px var(--hover-glow); }
.primary-button, .file-picker span {
  border: 1px solid var(--accent-soft-border);
  border-radius: var(--radius-sm);
  background: var(--btn-primary);
  color: var(--btn-primary-text);
}
.primary-button:hover { background: var(--btn-primary-hover); }
.quiet-button { border-color: var(--line); border-radius: var(--radius-sm); background: var(--btn-ghost); color: var(--text); text-decoration: none; }
.file-field { border-color: var(--line); }
.selected-files li { border-radius: var(--radius-sm); background: var(--surface-soft); }
.markdown-preview { top: 112px; border-radius: var(--radius-xl); }
.report-form { border-radius: var(--radius-xl); }
.my-reports, .leaderboard-panel { overflow: hidden; }
.my-report-row, .ranking-row, .ranking-head { border-color: var(--line); }
.my-report-row:hover, .ranking-row.current { background: var(--surface-soft); }
.empty-state { color: var(--muted); }
.empty-state h3 { margin: 0 0 18px; color: var(--text); font-size: 20px; font-weight: 700; line-height: 1.2; }
.score-rules { border-color: var(--line); border-radius: var(--radius-lg); overflow: hidden; }
.score-rules div { border-color: var(--line); }
.pipeline { grid-template-columns: repeat(5, 1fr); overflow: hidden; }
.pipeline-step { min-height: 82px; grid-template-columns: 1fr auto; align-items: center; border-color: var(--line); color: var(--text); }
.pipeline-step:hover, .pipeline-step.selected { background: var(--surface-soft); }
.pipeline-step.selected { box-shadow: inset 0 -4px var(--brand); }
.pipeline-step b { font-size: 22px; font-weight: 700; line-height: 1; }
.workflow-notes { display: grid; grid-template-columns: repeat(5, 1fr); gap: 0; margin-top: 0; padding: 0; overflow: hidden; color: var(--text); }
.workflow-step { position: relative; display: grid; min-height: 120px; place-content: center; justify-items: center; gap: 8px; border-right: 1px solid var(--line); }
.workflow-step:last-child { border-right: 0; }
.workflow-step span { color: var(--brand-dark); font-size: 24px; font-weight: 700; }
.workflow-step b { position: absolute; top: 50%; right: -9px; z-index: 1; color: var(--brand); transform: translateY(-50%); }
.review-workspace { min-height: 600px; margin-top: 14px; overflow: hidden; }
.report-queue { border-color: var(--line); }
.queue-item { border-color: var(--line); }
.queue-item:hover, .queue-item.active { background: var(--surface-soft); }
.queue-item.active::before { background: var(--brand); }
.review-sheet > h2, .report-modal > h2 { font-size: clamp(24px, 3vw, 34px); font-weight: 700; line-height: 1.15; }
.review-decision { border-left-color: var(--brand); border-radius: var(--radius-lg); background: var(--surface-soft); }
.review-placeholder { color: var(--muted); }
.review-placeholder h2 { margin: 0; color: var(--text); font-size: 22px; font-weight: 700; line-height: 1.2; }
.report-badges span, .status-chip { border-color: var(--line); border-radius: 999px; background: var(--surface-soft); }
.modal-backdrop { background: rgba(20, 27, 38, .62); }
.report-modal { border-color: var(--line); border-radius: var(--radius-xl); background: var(--surface); box-shadow: var(--shadow); }
.sheet-meta, .queue-item small, .timeline-item small, .report-main small, .attachment-count, .ranking-person small { color: var(--muted); }
.report-markdown, .attachment-block, .compact-timeline { border-color: var(--line); }
.timeline-dot { background: var(--brand); box-shadow: 0 0 0 1px var(--brand); }
.affected-link, .attachment-block button { color: var(--brand-dark); }
.security-shell.theme-dark .severity-critical { background: rgba(141, 41, 48, .2); }

@media (max-width: 980px) {
  .submit-grid, .review-workspace { grid-template-columns: 1fr; }
  .workflow-notes { grid-template-columns: 1fr; }
  .workflow-step { min-height: 76px; border-right: 0; border-bottom: 1px solid var(--line); }
  .workflow-step b { top: auto; right: 50%; bottom: -13px; transform: translateX(50%) rotate(90deg); }
}
@media (max-width: 680px) {
  .topbar { top: 14px; width: calc(100vw - 24px); min-height: 58px; padding: 0; }
  .wordmark strong { font-size: 20px; }
  .wordmark span { font-size: 12px; }
  .topbar .quiet-button { min-height: 34px; padding: 0 9px; font-size: 12px; }
  .topbar-spacer { height: 104px; }
  .admin-main, .reporter-main { width: calc(100vw - 24px); padding-top: 0; }
  .page-heading, .reporter-hero { display: grid; min-height: 0; padding: 12px 0 18px; }
  .hero-stats { width: 100%; min-width: 0; }
  .pipeline { grid-template-columns: 1fr; }
  .pipeline-step { min-height: 64px; border-right: 0; border-bottom: 1px solid var(--line); }
  .report-form { padding: 20px 16px; }
  .section-tabs { overflow-x: auto; }
}
</style>
