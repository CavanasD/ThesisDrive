<script setup>
import { ref, onMounted } from 'vue'
import AdminTokenControl from './AdminTokenControl.vue'
import {
  AdminApiError,
  adminFetch,
  carapaceBaseUrl,
  getAdminToken,
  requireAdminResponse,
} from '../services/adminApi'

const CARAPACE = carapaceBaseUrl()

// Static metadata for each vulnerability switch. Names must match
// VulnSwitchRegistry constants on the backend (ssrf / jwt-alg-none / cors / log4shell).
const VULN_META = {
  'ssrf':         { label: 'SSRF',          desc: '/api/preview 接受任意 URL（含内网），允许打到 CFMS:5104' },
  'jwt-alg-none': { label: 'JWT alg:none',  desc: '/api/admin/config 接受 alg=none token，可伪造 admin' },
  'cors':         { label: 'CORS 错配',     desc: '反射 Origin 头并允许 credentials，CSRF 防御失效' },
  'log4shell':    { label: 'Log4Shell',     desc: '/api/log4shell 用 log4j-core 2.14.1 解析 ${jndi:...}' },
}

const switches = ref([])  // [{ name, enabled, label, desc }]
const loading = ref(false)
const errorMsg = ref('')
const adminStatus = ref(getAdminToken() ? 'connecting' : 'locked')

const handleAdminError = (error, prefix = '请求失败') => {
  adminStatus.value = error instanceof AdminApiError && [401, 403].includes(error.status)
    ? 'unauthorized'
    : 'error'
  errorMsg.value = `${prefix}: ${error.message}`
}

const load = async () => {
  if (!getAdminToken()) {
    adminStatus.value = 'locked'
    switches.value = []
    errorMsg.value = ''
    return
  }
  loading.value = true
  adminStatus.value = 'connecting'
  errorMsg.value = ''
  try {
    const res = await adminFetch(`${CARAPACE}/api/admin/vuln`)
    await requireAdminResponse(res)
    const data = await res.json()
    switches.value = Object.entries(data).map(([name, enabled]) => ({
      name,
      enabled,
      label: VULN_META[name]?.label ?? name,
      desc:  VULN_META[name]?.desc  ?? '',
    }))
    adminStatus.value = 'connected'
  } catch (e) {
    handleAdminError(e, '加载失败')
  } finally {
    loading.value = false
  }
}

const toggle = async (sw) => {
  const next = !sw.enabled
  try {
    const res = await adminFetch(`${CARAPACE}/api/admin/vuln/${encodeURIComponent(sw.name)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: next }),
    })
    await requireAdminResponse(res)
    sw.enabled = next
    adminStatus.value = 'connected'
  } catch (e) {
    handleAdminError(e, `切换 ${sw.name} 失败`)
  }
}

const allOn  = () => Promise.all(switches.value.filter(s => !s.enabled).map(toggle))
const allOff = () => Promise.all(switches.value.filter(s =>  s.enabled).map(toggle))

const onAdminTokenChange = (token) => {
  if (!token) {
    adminStatus.value = 'locked'
    switches.value = []
    errorMsg.value = ''
    return
  }
  load()
}

onMounted(load)
</script>

<template>
  <div class="vp-root">
    <div class="vp-header">
      <div class="vp-titles">
        <span class="vp-title">漏洞开关</span>
        <span class="vp-sub">Carapace · 教学攻防靶场（运行时热切换）</span>
      </div>
      <AdminTokenControl :status="adminStatus" @change="onAdminTokenChange" />
      <div class="vp-actions">
        <button class="vp-btn" @click="load" :disabled="loading">{{ loading ? '加载中…' : '刷新' }}</button>
        <button class="vp-btn vp-btn-on" :disabled="adminStatus !== 'connected'" @click="allOn">全部开启</button>
        <button class="vp-btn vp-btn-off" :disabled="adminStatus !== 'connected'" @click="allOff">全部关闭（加固模式）</button>
      </div>
    </div>

    <p v-if="errorMsg" class="vp-error">{{ errorMsg }}</p>

    <ul class="vp-list">
      <li v-for="sw in switches" :key="sw.name" class="vp-item" :class="{ on: sw.enabled }">
        <div class="vp-item-text">
          <div class="vp-item-name">
            <span class="vp-item-label">{{ sw.label }}</span>
            <code class="vp-item-key">{{ sw.name }}</code>
          </div>
          <div class="vp-item-desc">{{ sw.desc }}</div>
        </div>
        <button
          class="vp-toggle"
          :class="{ on: sw.enabled }"
          @click="toggle(sw)"
          :aria-pressed="sw.enabled"
        >
          <span class="vp-toggle-knob"></span>
          <span class="vp-toggle-label">{{ sw.enabled ? 'ON' : 'OFF' }}</span>
        </button>
      </li>
      <li v-if="!loading && !switches.length" class="vp-empty">没有可显示的漏洞开关</li>
    </ul>
  </div>
</template>

<style scoped>
.vp-root {
  width: 100%;
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg, 16px);
  box-shadow: var(--shadow);
  padding: 18px 20px 22px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.vp-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--line);
}
.vp-titles { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.vp-title { font-size: 15px; font-weight: 700; color: #e34141; }
.vp-sub   { font-size: 11px; color: var(--muted); letter-spacing: 0.05em; }
.vp-actions { display: flex; gap: 6px; }
.vp-btn {
  background: var(--btn-ghost);
  border: 1px solid var(--line);
  color: var(--text);
  font-size: 12px;
  padding: 6px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.vp-btn:hover:not(:disabled) { background: var(--btn-ghost-hover); }
.vp-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.vp-btn-on  { color: #2ea86e; border-color: rgba(46, 168, 110, 0.45); }
.vp-btn-off { color: #e34141; border-color: rgba(227, 65, 65, 0.45); }

.vp-error {
  background: rgba(227, 65, 65, 0.08);
  border: 1px solid rgba(227, 65, 65, 0.4);
  color: #e34141;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
  margin: 0;
}

.vp-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
.vp-item {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 16px;
  background: var(--surface-soft);
  border: 1px solid var(--line);
  border-radius: 10px;
  transition: border-color 0.15s, background 0.15s;
}
.vp-item.on {
  border-color: rgba(227, 65, 65, 0.45);
  background: rgba(227, 65, 65, 0.05);
}
.vp-item-text { flex: 1; min-width: 0; }
.vp-item-name { display: flex; align-items: baseline; gap: 10px; }
.vp-item-label { font-size: 14px; font-weight: 700; color: var(--text); }
.vp-item-key {
  font-family: monospace;
  font-size: 11px;
  color: var(--muted);
  background: var(--btn-ghost);
  padding: 1px 6px;
  border-radius: 4px;
}
.vp-item-desc { font-size: 12px; color: var(--muted); margin-top: 4px; }

.vp-toggle {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--btn-ghost);
  border: 1px solid var(--line);
  color: var(--muted);
  font-family: monospace;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  padding: 6px 12px 6px 8px;
  border-radius: 999px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
  flex-shrink: 0;
}
.vp-toggle.on {
  background: rgba(227, 65, 65, 0.12);
  color: #e34141;
  border-color: rgba(227, 65, 65, 0.55);
}
.vp-toggle-knob {
  width: 12px; height: 12px; border-radius: 50%;
  background: var(--muted);
  opacity: 0.6;
  box-shadow: 0 0 0 2px var(--surface);
  transition: background 0.15s, box-shadow 0.15s, opacity 0.15s;
}
.vp-toggle.on .vp-toggle-knob {
  background: #e34141;
  opacity: 1;
  box-shadow: 0 0 6px rgba(227, 65, 65, 0.6);
}

.vp-empty {
  padding: 32px;
  text-align: center;
  color: var(--muted);
  font-size: 13px;
}

@media (max-width: 940px) {
  .vp-header { flex-wrap: wrap; }
  .vp-titles { min-width: 220px; }
  .vp-actions { width: 100%; justify-content: flex-end; }
}
</style>
