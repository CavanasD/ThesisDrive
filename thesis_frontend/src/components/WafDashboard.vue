<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'

const emit = defineEmits(['close'])

// Inline mode (default) renders the panel as a regular block inside its parent
// — no teleport, no backdrop. Modal mode is kept around for callers who still
// want the old overlay behaviour, but App.vue no longer uses it.
const props = defineProps({
  inline: { type: Boolean, default: true },
})

const CARAPACE = import.meta.env.VITE_CARAPACE_URL || 'http://localhost:8080'

// ── Panel animation ───────────────────────────────────────────────────────────
const visible = ref(false)

// ── Data ──────────────────────────────────────────────────────────────────────
const stats  = ref({ total: 0, blocked: 0, connections: 0 })
const rules  = ref([])
const events = ref([])
const MAX_EVENTS = 500

// ── Filters ───────────────────────────────────────────────────────────────────
const filterStatus = ref('all')   // 'all' | 'blocked' | 'passed'
const filterRule   = ref('')      // '' = all rules
const filterTime   = ref('all')   // 'all' | '1h' | '6h' | '24h' | '7d'
const filterSearch = ref('')      // free text: IP / action / reason / id

let sse = null
let statsTimer = null

// ── Computed: filtered & sorted events ───────────────────────────────────────
const filteredEvents = computed(() => {
  const now = Date.now()
  const cutoffMs = { '1h': 3600e3, '6h': 6 * 3600e3, '24h': 86400e3, '7d': 7 * 86400e3 }
  const since = cutoffMs[filterTime.value] ? now - cutoffMs[filterTime.value] : 0
  const q = filterSearch.value.toLowerCase().trim()

  return events.value.filter(ev => {
    if (filterStatus.value === 'blocked' && !ev.blocked) return false
    if (filterStatus.value === 'passed'  &&  ev.blocked) return false
    if (filterRule.value && ev.ruleName !== filterRule.value) return false
    if (since && new Date(ev.timestamp).getTime() < since) return false
    if (q && ![ev.clientIp, ev.action, ev.reason, ev.encryptedId, ev.defenseType]
        .some(f => (f || '').toLowerCase().includes(q))) return false
    return true
  })
})

// ── Pagination ───────────────────────────────────────────────────────────────
const pageSize = ref(15)
const currentPage = ref(1)

const totalPages = computed(() =>
  Math.max(1, Math.ceil(filteredEvents.value.length / pageSize.value))
)

const pagedEvents = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredEvents.value.slice(start, start + pageSize.value)
})

// Reset to first page whenever a filter narrows the result set, so users
// don't end up looking at an empty page after typing in the search box.
watch([filterStatus, filterRule, filterTime, filterSearch, pageSize], () => {
  currentPage.value = 1
})

// Clamp the current page if upstream events stream in and the user is on
// a now-out-of-range page (rare but possible after filter changes).
watch(totalPages, (n) => {
  if (currentPage.value > n) currentPage.value = n
})

const goToPage = (p) => {
  currentPage.value = Math.min(Math.max(1, p), totalPages.value)
}

const ruleNames = computed(() => [...new Set(events.value.map(e => e.ruleName).filter(Boolean))])

const blockRate = () => {
  if (!stats.value.total) return '0.0'
  return ((stats.value.blocked / stats.value.total) * 100).toFixed(1)
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────
onMounted(async () => {
  requestAnimationFrame(() => { visible.value = true })
  await Promise.all([loadStats(), loadRules(), loadEvents()])
  connectSse()
  statsTimer = setInterval(loadStats, 5000)
})

onBeforeUnmount(() => {
  sse?.close()
  clearInterval(statsTimer)
})

// ── Data loading ──────────────────────────────────────────────────────────────
const get = (path) => fetch(`${CARAPACE}/api/waf${path}`).then(r => r.json())

const loadStats  = async () => { try { stats.value = await get('/stats') }        catch {} }
const loadRules  = async () => { try { rules.value = await get('/rules') }        catch {} }
const loadEvents = async () => {
  try {
    events.value = await get('/events?limit=500')
  } catch {}
}

const connectSse = () => {
  sse?.close()
  sse = new EventSource(`${CARAPACE}/api/waf/events/stream`)
  // 后端发的是命名事件 "waf-event"，必须用 addEventListener 不能用 onmessage
  sse.addEventListener('waf-event', (e) => {
    try {
      const ev = JSON.parse(e.data)
      events.value = [ev, ...events.value.slice(0, MAX_EVENTS - 1)]
    } catch {}
  })
  sse.onerror = () => {
    sse?.close()
    // 3秒后自动重连
    setTimeout(connectSse, 3000)
  }
}

// ── Rule toggle ───────────────────────────────────────────────────────────────
const toggleRule = async (rule) => {
  const next = !rule.enabled
  try {
    await fetch(`${CARAPACE}/api/waf/rules/${encodeURIComponent(rule.name)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: next }),
    })
    rule.enabled = next
  } catch {}
}

// ── Export ────────────────────────────────────────────────────────────────────
const exportCsv = () => {
  const a = document.createElement('a')
  a.href = `${CARAPACE}/api/waf/events/export`
  a.download = `waf-${new Date().toISOString().slice(0,10)}.csv`
  a.click()
}

// ── Utils ─────────────────────────────────────────────────────────────────────
const dismiss = () => {
  visible.value = false
  setTimeout(() => emit('close'), 400)
}

const resetFilters = () => {
  filterStatus.value = 'all'
  filterRule.value   = ''
  filterTime.value   = 'all'
  filterSearch.value = ''
}

const fmtTime = (ts) => {
  if (!ts) return '-'
  return new Date(ts).toLocaleString('zh-CN', {
    hour12: false, month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}
</script>

<template>
  <component
    :is="props.inline ? 'div' : 'Teleport'"
    v-bind="props.inline ? {} : { to: 'body' }"
  >
    <div
      class="db-backdrop"
      :class="{ visible: visible || props.inline, 'db-inline-host': props.inline }"
      @click.self="props.inline ? null : dismiss()"
    >
      <div class="db-panel" :class="{ visible: visible || props.inline, 'db-inline': props.inline }">

        <!-- Topbar -->
        <div class="db-topbar">
          <span class="db-logo">⛨</span>
          <div class="db-titles">
            <span class="db-title">WAF 安全日志</span>
            <span class="db-sub">Carapace · 实时防护</span>
          </div>
          <button class="db-btn-ghost" @click="exportCsv">↓ 导出 CSV</button>
          <button v-if="!props.inline" class="db-close" @click="dismiss">✕</button>
        </div>

        <!-- 统计卡片 -->
        <div class="db-stats">
          <div class="stat-card">
            <div class="stat-num">{{ stats.total }}</div>
            <div class="stat-label">总请求</div>
          </div>
          <div class="stat-card danger">
            <div class="stat-num">{{ stats.blocked }}</div>
            <div class="stat-label">已拦截</div>
          </div>
          <div class="stat-card">
            <div class="stat-num">{{ blockRate() }}%</div>
            <div class="stat-label">拦截率</div>
          </div>
          <div class="stat-card success">
            <div class="stat-num">{{ stats.connections }}</div>
            <div class="stat-label">在线连接</div>
          </div>
          <div class="stat-card muted">
            <div class="stat-num">{{ filteredEvents.length }}</div>
            <div class="stat-label">当前筛选</div>
          </div>
        </div>

        <!-- 规则开关 -->
        <div class="db-rules-bar">
          <span class="db-bar-label">防护规则</span>
          <div class="db-rules">
            <button
              v-for="rule in rules"
              :key="rule.name"
              class="rule-chip"
              :class="{ on: rule.enabled }"
              @click="toggleRule(rule)"
              :title="rule.name"
            >
              <span class="rule-dot"></span>
              {{ rule.name.replace(' Detection', '') }}
            </button>
          </div>
        </div>

        <!-- 过滤栏 -->
        <div class="db-filter-bar">
          <select v-model="filterStatus" class="db-select">
            <option value="all">全部状态</option>
            <option value="blocked">仅拦截</option>
            <option value="passed">仅通过</option>
          </select>
          <select v-model="filterRule" class="db-select">
            <option value="">全部规则</option>
            <option v-for="n in ruleNames" :key="n" :value="n">{{ n }}</option>
          </select>
          <select v-model="filterTime" class="db-select">
            <option value="all">全部时间</option>
            <option value="1h">最近 1h</option>
            <option value="6h">最近 6h</option>
            <option value="24h">最近 24h</option>
            <option value="7d">最近 7 天</option>
          </select>
          <input v-model="filterSearch" class="db-search" placeholder="搜索 IP · 操作 · 编号…" />
          <button class="db-btn-ghost" @click="resetFilters">重置</button>
        </div>

        <!-- 事件表格 -->
        <div class="db-table-wrap">
          <table class="db-table">
            <thead>
              <tr>
                <th>编号</th>
                <th>时间</th>
                <th>状态</th>
                <th>防御类型</th>
                <th>IP</th>
                <th>操作</th>
                <th>原因</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="ev in pagedEvents"
                :key="ev.id"
                :class="{ 'row-blocked': ev.blocked }"
              >
                <td class="col-id">{{ ev.encryptedId }}</td>
                <td class="col-time">{{ fmtTime(ev.timestamp) }}</td>
                <td>
                  <span class="status-badge" :class="ev.blocked ? 'badge-block' : 'badge-pass'">
                    {{ ev.blocked ? '拦截' : '通过' }}
                  </span>
                </td>
                <td class="col-type">{{ ev.defenseType || '-' }}</td>
                <td class="col-ip">{{ ev.clientIp }}</td>
                <td class="col-action">{{ ev.action }}</td>
                <td class="col-reason">{{ ev.reason || '-' }}</td>
              </tr>
              <tr v-if="filteredEvents.length === 0">
                <td colspan="7" class="ev-empty">暂无匹配事件</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 分页脚 -->
        <div v-if="filteredEvents.length > 0" class="db-pagination">
          <div class="db-page-info">
            共 {{ filteredEvents.length }} 条 ·
            第 {{ currentPage }} / {{ totalPages }} 页
          </div>
          <div class="db-page-ctl">
            <select v-model.number="pageSize" class="db-select db-select-tight">
              <option :value="10">10 / 页</option>
              <option :value="15">15 / 页</option>
              <option :value="25">25 / 页</option>
              <option :value="50">50 / 页</option>
            </select>
            <button class="db-btn-ghost" :disabled="currentPage <= 1" @click="goToPage(1)">«</button>
            <button class="db-btn-ghost" :disabled="currentPage <= 1" @click="goToPage(currentPage - 1)">‹</button>
            <button class="db-btn-ghost" :disabled="currentPage >= totalPages" @click="goToPage(currentPage + 1)">›</button>
            <button class="db-btn-ghost" :disabled="currentPage >= totalPages" @click="goToPage(totalPages)">»</button>
          </div>
        </div>
      </div>
    </div>
  </component>
</template>

<style scoped>
.db-backdrop {
  position: fixed;
  inset: 0;
  z-index: 8900;
  background: rgba(0,0,0,0);
  pointer-events: none;
  transition: background 0.3s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}
.db-backdrop.visible {
  background: rgba(0,0,0,0.6);
  pointer-events: all;
}

/* Inline mode: render flat inside the parent tab card, no overlay/backdrop. */
.db-backdrop.db-inline-host {
  position: static;
  inset: auto;
  z-index: auto;
  background: transparent;
  pointer-events: all;
  display: block;
  padding: 0;
}

.db-panel {
  width: min(1140px, 96vw);
  height: min(90vh, 880px);
  background: #111;
  border-radius: 16px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 24px 64px rgba(0,0,0,0.7);
  opacity: 0;
  transform: translateY(28px) scale(0.97);
  transition: opacity 0.35s ease, transform 0.35s cubic-bezier(0.32,0.72,0,1);
}
.db-panel.visible { opacity: 1; transform: translateY(0) scale(1); }
.db-panel.db-inline {
  width: 100%;
  height: 100%;
  min-height: 600px;
  /* Inherits the site's --surface / --text / --line / --muted from the
     enclosing .page (or .page.theme-dark), so the panel tracks the global
     light/dark toggle instead of being permanently dark. */
  background: var(--surface);
  color: var(--text);
  border-radius: var(--radius-lg, 16px);
  border: 1px solid var(--line);
  box-shadow: var(--shadow);
  opacity: 1;
  transform: none;
  transition: none;
}
.db-panel.db-inline .db-topbar {
  background: var(--surface-soft);
  border-bottom-color: var(--line);
}

/* Pagination footer */
.db-pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-top: 1px solid var(--line);
  background: var(--surface-soft);
  flex-shrink: 0;
  gap: 12px;
}
.db-page-info {
  color: var(--muted);
  font-size: 12px;
}
.db-page-ctl {
  display: flex;
  align-items: center;
  gap: 6px;
}
.db-page-ctl .db-btn-ghost {
  min-width: 28px;
  padding: 5px 9px;
  font-size: 13px;
}
.db-page-ctl .db-btn-ghost:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.db-select-tight {
  padding: 4px 8px;
  font-size: 12px;
}

/* Topbar */
.db-topbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-soft);
  flex-shrink: 0;
}
/* Brand red is kept in both themes — it's the WAF's identity. */
.db-logo { font-size: 22px; color: #e34141; }
.db-titles { flex: 1; display: flex; flex-direction: column; gap: 1px; }
.db-title { font-size: 14px; font-weight: 700; color: #e34141; }
.db-sub { font-size: 10px; color: var(--muted); letter-spacing: 0.06em; }
.db-btn-ghost {
  background: var(--btn-ghost);
  border: 1px solid var(--line);
  color: var(--text);
  font-size: 12px;
  padding: 5px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.db-btn-ghost:hover { background: var(--btn-ghost-hover); }
.db-close {
  background: none; border: none; color: var(--muted);
  font-size: 18px; cursor: pointer; padding: 4px 8px;
  border-radius: 6px; transition: color 0.15s, background 0.15s;
}
.db-close:hover { color: var(--text); background: var(--btn-ghost); }

/* Stats */
.db-stats {
  display: flex;
  gap: 10px;
  padding: 14px 16px 6px;
  flex-shrink: 0;
}
.stat-card {
  flex: 1;
  background: var(--surface-soft);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm, 10px);
  padding: 12px 10px;
  text-align: center;
}
.stat-card.danger  { border-color: rgba(227, 65, 65, 0.4); }
.stat-card.success { border-color: rgba(46, 168, 110, 0.45); }
.stat-card.muted   { border-color: var(--line); }
.stat-num { font-size: 20px; font-weight: 800; color: var(--text); }
.stat-card.danger  .stat-num { color: #e34141; }
.stat-card.success .stat-num { color: #2ea86e; }
.stat-label { font-size: 11px; color: var(--muted); margin-top: 4px; letter-spacing: 0.04em; }

/* Rules bar */
.db-rules-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  flex-shrink: 0;
}
.db-bar-label { font-size: 11px; color: var(--muted); letter-spacing: 0.07em; min-width: 56px; }
.db-rules { display: flex; flex-wrap: wrap; gap: 6px; }
.rule-chip {
  display: flex; align-items: center; gap: 5px;
  background: var(--btn-ghost); border: 1px solid var(--line);
  color: var(--muted); font-size: 11px; padding: 4px 10px;
  border-radius: 20px; cursor: pointer; transition: all 0.15s;
}
.rule-chip.on {
  border-color: rgba(46, 168, 110, 0.55);
  color: #2ea86e;
  background: rgba(46, 168, 110, 0.08);
}
.rule-dot {
  width: 6px; height: 6px; border-radius: 50%; background: var(--muted);
  opacity: 0.5;
  transition: background 0.15s;
}
.rule-chip.on .rule-dot { background: #2ea86e; opacity: 1; box-shadow: 0 0 6px rgba(46, 168, 110, 0.5); }

/* Filter bar */
.db-filter-bar {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 8px 16px 10px;
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
}
.db-select {
  background: var(--surface-soft); border: 1px solid var(--line);
  color: var(--text); font-size: 12px; padding: 5px 10px;
  border-radius: 6px; outline: none; cursor: pointer;
}
.db-search {
  flex: 1; min-width: 160px;
  background: var(--surface-soft); border: 1px solid var(--line);
  color: var(--text); font-size: 12px; padding: 6px 10px;
  border-radius: 6px; outline: none; transition: border-color 0.2s;
}
.db-search:focus { border-color: var(--brand); }
.db-search::placeholder { color: var(--muted); }

/* Table */
.db-table-wrap { flex: 1; overflow: auto; }
.db-table-wrap::-webkit-scrollbar { width: 6px; height: 6px; }
.db-table-wrap::-webkit-scrollbar-thumb { background: var(--line); border-radius: 3px; }

.db-table {
  width: 100%; border-collapse: collapse;
  font-size: 12px; min-width: 900px;
}
.db-table th {
  position: sticky; top: 0;
  background: var(--surface-soft);
  color: var(--muted); font-weight: 600; font-size: 11px;
  text-align: left; padding: 9px 12px;
  letter-spacing: 0.05em; border-bottom: 1px solid var(--line);
}
.db-table td {
  padding: 8px 12px; color: var(--text);
  border-bottom: 1px solid var(--line);
  white-space: nowrap; vertical-align: middle;
}
.row-blocked td { background: rgba(227, 65, 65, 0.06); }
.db-table tbody tr:hover td { background: var(--btn-ghost); }
.row-blocked:hover td { background: rgba(227, 65, 65, 0.12) !important; }

.col-id    { color: #e34141; font-family: monospace; font-size: 11px; font-weight: 700; }
.col-time  { color: var(--muted); font-family: monospace; font-size: 11px; }
.col-type  { color: var(--brand-dark); font-family: monospace; font-size: 11px; max-width: 220px; overflow: hidden; text-overflow: ellipsis; }
.col-ip    { color: var(--muted); font-family: monospace; }
.col-action{ color: var(--text); }
.col-reason{ color: var(--muted); max-width: 260px; overflow: hidden; text-overflow: ellipsis; font-style: italic; }

.status-badge { border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: 700; }
.badge-block  { background: rgba(227, 65, 65, 0.15); color: #e34141; }
.badge-pass   { background: rgba(46, 168, 110, 0.18); color: #2ea86e; }

.ev-empty { text-align: center; color: var(--muted); padding: 48px; font-size: 13px; }
</style>
