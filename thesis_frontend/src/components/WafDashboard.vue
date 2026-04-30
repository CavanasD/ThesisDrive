<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'

const emit = defineEmits(['close'])

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
  <Teleport to="body">
    <div class="db-backdrop" :class="{ visible }" @click.self="dismiss">
      <div class="db-panel" :class="{ visible }">

        <!-- Topbar -->
        <div class="db-topbar">
          <span class="db-logo">⛨</span>
          <div class="db-titles">
            <span class="db-title">WAF 安全日志</span>
            <span class="db-sub">Carapace · 实时防护</span>
          </div>
          <button class="db-btn-ghost" @click="exportCsv">↓ 导出 CSV</button>
          <button class="db-close" @click="dismiss">✕</button>
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
                v-for="ev in filteredEvents"
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
      </div>
    </div>
  </Teleport>
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

/* Topbar */
.db-topbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 20px;
  border-bottom: 1px solid #1e1e1e;
  background: #141414;
  flex-shrink: 0;
}
.db-logo { font-size: 22px; color: #ff5252; }
.db-titles { flex: 1; display: flex; flex-direction: column; gap: 1px; }
.db-title { font-size: 14px; font-weight: 700; color: #ff5252; }
.db-sub { font-size: 10px; color: #3a3a3a; letter-spacing: 0.06em; }
.db-btn-ghost {
  background: #1e1e1e;
  border: 1px solid #2a2a2a;
  color: #777;
  font-size: 12px;
  padding: 5px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.db-btn-ghost:hover { background: #262626; color: #ccc; }
.db-close {
  background: none; border: none; color: #444;
  font-size: 18px; cursor: pointer; padding: 4px 8px;
  border-radius: 6px; transition: color 0.15s, background 0.15s;
}
.db-close:hover { color: #ccc; background: #222; }

/* Stats */
.db-stats {
  display: flex;
  gap: 8px;
  padding: 12px 16px 8px;
  flex-shrink: 0;
}
.stat-card {
  flex: 1;
  background: #191919;
  border: 1px solid #222;
  border-radius: 10px;
  padding: 10px 8px;
  text-align: center;
}
.stat-card.danger  { border-color: #3a1414; }
.stat-card.success { border-color: #143a14; }
.stat-card.muted   { border-color: #1e1e1e; }
.stat-num { font-size: 20px; font-weight: 800; color: #ddd; }
.stat-card.danger  .stat-num { color: #ff5252; }
.stat-card.success .stat-num { color: #69f0ae; }
.stat-label { font-size: 10px; color: #3a3a3a; margin-top: 3px; letter-spacing: 0.04em; }

/* Rules bar */
.db-rules-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  flex-shrink: 0;
}
.db-bar-label { font-size: 10px; color: #3a3a3a; letter-spacing: 0.07em; min-width: 52px; }
.db-rules { display: flex; flex-wrap: wrap; gap: 6px; }
.rule-chip {
  display: flex; align-items: center; gap: 5px;
  background: #1a1a1a; border: 1px solid #252525;
  color: #4a4a4a; font-size: 11px; padding: 4px 10px;
  border-radius: 20px; cursor: pointer; transition: all 0.15s;
}
.rule-chip.on { border-color: #1b4a1b; color: #69f0ae; }
.rule-dot {
  width: 6px; height: 6px; border-radius: 50%; background: #2a2a2a;
  transition: background 0.15s;
}
.rule-chip.on .rule-dot { background: #69f0ae; box-shadow: 0 0 4px #69f0ae80; }

/* Filter bar */
.db-filter-bar {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 6px 16px 10px;
  border-bottom: 1px solid #191919;
  flex-shrink: 0;
}
.db-select {
  background: #191919; border: 1px solid #252525;
  color: #777; font-size: 12px; padding: 5px 10px;
  border-radius: 6px; outline: none; cursor: pointer;
}
.db-search {
  flex: 1; min-width: 160px;
  background: #191919; border: 1px solid #252525;
  color: #ccc; font-size: 12px; padding: 5px 10px;
  border-radius: 6px; outline: none; transition: border-color 0.2s;
}
.db-search:focus { border-color: #ff525430; }
.db-search::placeholder { color: #2e2e2e; }

/* Table */
.db-table-wrap { flex: 1; overflow: auto; }
.db-table-wrap::-webkit-scrollbar { width: 4px; height: 4px; }
.db-table-wrap::-webkit-scrollbar-thumb { background: #252525; border-radius: 2px; }

.db-table {
  width: 100%; border-collapse: collapse;
  font-size: 12px; min-width: 900px;
}
.db-table th {
  position: sticky; top: 0; background: #141414;
  color: #3a3a3a; font-weight: 600; font-size: 10px;
  text-align: left; padding: 8px 12px;
  letter-spacing: 0.05em; border-bottom: 1px solid #1e1e1e;
}
.db-table td {
  padding: 7px 12px; color: #777;
  border-bottom: 1px solid #181818;
  white-space: nowrap; vertical-align: middle;
}
.row-blocked td { background: #140e0e; }
.db-table tbody tr:hover td { background: #1a1a1a; }
.row-blocked:hover td { background: #1e1010 !important; }

.col-id    { color: #ff8a80; font-family: monospace; font-size: 11px; font-weight: 700; }
.col-time  { color: #444; font-family: monospace; font-size: 11px; }
.col-type  { color: #6a8fc4; font-family: monospace; font-size: 11px; max-width: 220px; overflow: hidden; text-overflow: ellipsis; }
.col-ip    { color: #555; font-family: monospace; }
.col-action{ color: #888; }
.col-reason{ color: #555; max-width: 260px; overflow: hidden; text-overflow: ellipsis; font-style: italic; }

.status-badge { border-radius: 4px; padding: 2px 6px; font-size: 10px; font-weight: 700; }
.badge-block  { background: #350d0d; color: #ff5252; }
.badge-pass   { background: #0d280d; color: #69f0ae; }

.ev-empty { text-align: center; color: #252525; padding: 48px; font-size: 13px; }
</style>
