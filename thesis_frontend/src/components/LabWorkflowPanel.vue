<script setup>
import { computed, onMounted, reactive, ref } from 'vue'

const props = defineProps({
  client: { type: Object, required: true },
  auth: { type: Object, required: true },
})

const FEATURE_META = {
  sqli: { label: 'SQL 注入', short: '枚举' },
  rce: { label: '命令注入', short: '执行' },
  auth_bypass: { label: '认证绕过', short: '绕过' },
  path_traversal: { label: '路径穿越', short: '穿越' },
  idor: { label: 'IDOR', short: '越权' },
}

const EXERCISE_META = {
  enumerate: { label: '账号枚举', feature: 'sqli' },
  bypass: { label: '认证绕过', feature: 'auth_bypass' },
  idor: { label: '对象越权', feature: 'idor' },
  traverse: { label: '路径穿越', feature: 'path_traversal' },
  execute: { label: '命令执行', feature: 'rce' },
}

const status = ref(null)
const loading = ref(false)
const error = ref('')
const chainForm = reactive({ id: '', title: '', steps: [] })
const lastStep = ref(null)
const chainEvidence = ref({})

const enabledFeatures = computed(() => new Set(status.value?.enabled_features || []))
const chains = computed(() => status.value?.chains || [])
const exercises = computed(() => status.value?.available_exercises || Object.keys(EXERCISE_META))

const request = async (action, data = {}) => {
  const response = await props.client.request(action, data, props.auth)
  if (!response || Number(response.code) >= 400) {
    throw new Error(response?.message || `${action} 失败`)
  }
  return response.data || {}
}

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    status.value = await request('lab_status')
  } catch (cause) {
    status.value = null
    error.value = cause?.message || '无法读取实验室状态'
  } finally {
    loading.value = false
  }
}

const toggleFeature = async (feature) => {
  try {
    await request('lab_set_vulnerability', {
      feature,
      enabled: !enabledFeatures.value.has(feature),
    })
    await load()
  } catch (cause) {
    error.value = cause?.message || '更新漏洞开关失败'
  }
}

const normalizeChainId = () => {
  const raw = chainForm.id.trim().toLowerCase()
  return raw.startsWith('custom-') ? raw : `custom-${raw}`
}

const publishChain = async () => {
  try {
    const id = normalizeChainId()
    if (!/^custom-[a-z][a-z0-9_-]{0,39}$/.test(id)) {
      throw new Error('链路标识应为英文字母开头，仅含小写字母、数字、- 或 _')
    }
    if (!chainForm.title.trim() || !chainForm.steps.length) {
      throw new Error('请填写链路名称并至少选择一个演练步骤')
    }
    await request('lab_configure_chain', {
      chain: id,
      title: chainForm.title.trim(),
      steps: chainForm.steps,
    })
    chainForm.id = ''
    chainForm.title = ''
    chainForm.steps = []
    await load()
  } catch (cause) {
    error.value = cause?.message || '发布教学链失败'
  }
}

const advanceChain = async (chain) => {
  try {
    const progress = Number(status.value?.chain_progress?.[chain.id] || 0)
    const step = chain.steps[progress]
    if (!step) {
      lastStep.value = `${chain.title} 已完成；请先重置实验状态。`
      return
    }
    const data = { chain: chain.id, step }
    if (progress > 0) {
      data.evidence = chainEvidence.value[chain.id]
    }
    const result = await request('lab_chain_step', data)
    if (result.evidence) {
      chainEvidence.value = { ...chainEvidence.value, [chain.id]: result.evidence }
    }
    lastStep.value = `${chain.title} · 第 ${result.step_number} 步：${EXERCISE_META[result.step]?.label || result.step}`
    await load()
  } catch (cause) {
    error.value = cause?.message || '推进教学链失败'
  }
}

onMounted(load)
</script>

<template>
  <div class="lab-root">
    <header class="lab-header">
      <div>
        <h3>教学流程编排</h3>
        <p>Core 实验室 · 运行时启停 · 仅 sysop 可管理</p>
      </div>
      <button class="lab-button secondary" :disabled="loading" @click="load">
        {{ loading ? '刷新中…' : '刷新状态' }}
      </button>
    </header>

    <p v-if="error" class="lab-message error">{{ error }}</p>
    <p v-else-if="!status && !loading" class="lab-message">实验室未启用；请使用含 <code>LAB_MODE=true</code> 的隔离 profile。</p>

    <template v-if="status">
      <section class="lab-section">
        <div class="section-heading">
          <h4>漏洞热插拔</h4>
          <span>{{ enabledFeatures.size }} / {{ Object.keys(FEATURE_META).length }} 已启用</span>
        </div>
        <div class="switch-grid">
          <button
            v-for="(meta, feature) in FEATURE_META"
            :key="feature"
            class="feature-switch"
            :class="{ enabled: enabledFeatures.has(feature) }"
            :aria-pressed="enabledFeatures.has(feature)"
            @click="toggleFeature(feature)"
          >
            <span class="switch-indicator"></span>
            <span><strong>{{ meta.label }}</strong><small>{{ enabledFeatures.has(feature) ? '已接入实验链' : '安全关闭' }}</small></span>
          </button>
        </div>
      </section>

      <section class="lab-section composer">
        <div class="section-heading">
          <h4>自定义教学链</h4>
          <span>只允许安全模拟步骤</span>
        </div>
        <div class="compose-fields">
          <label>链路标识<input v-model="chainForm.id" placeholder="custom-week-1" /></label>
          <label>教学名称<input v-model="chainForm.title" placeholder="第一周攻防演练" /></label>
        </div>
        <div class="exercise-picker">
          <label v-for="exercise in exercises" :key="exercise" class="exercise-choice">
            <input v-model="chainForm.steps" type="checkbox" :value="exercise" />
            <span>{{ EXERCISE_META[exercise]?.label || exercise }}</span>
            <small>{{ FEATURE_META[EXERCISE_META[exercise]?.feature]?.short || '' }}</small>
          </label>
        </div>
        <button class="lab-button" @click="publishChain">发布到本次实验</button>
      </section>

      <section class="lab-section">
        <div class="section-heading">
          <h4>已编排流程</h4>
          <span>{{ chains.length }} 条</span>
        </div>
        <div class="chain-list">
          <article v-for="chain in chains" :key="chain.id" class="chain-card" :class="{ unavailable: !chain.available }">
            <div class="chain-title-row">
              <div><strong>{{ chain.title }}</strong><small>{{ chain.id }}</small></div>
              <span class="chain-status">{{ chain.available ? '可演练' : '缺少漏洞开关' }}</span>
            </div>
            <ol class="step-list">
              <li v-for="step in chain.steps" :key="step">{{ EXERCISE_META[step]?.label || step }}</li>
            </ol>
            <button class="lab-button secondary" :disabled="!chain.available" @click="advanceChain(chain)">
              推进下一步
            </button>
          </article>
        </div>
        <p v-if="lastStep" class="lab-message success">{{ lastStep }}</p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.lab-root { display: grid; gap: 16px; width: 100%; }
.lab-header, .section-heading, .chain-title-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.lab-header h3, .lab-header p, h4, .lab-message { margin: 0; }
.lab-header h3 { font-size: 18px; }
.lab-header p, .section-heading span, .chain-title-row small, .feature-switch small { color: var(--muted); font-size: 12px; }
.lab-section { display: grid; gap: 12px; padding: 16px; border: 1px solid var(--line); border-radius: 16px; background: var(--surface); }
.section-heading h4 { font-size: 14px; }
.switch-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }
.feature-switch { display: flex; align-items: center; gap: 10px; text-align: left; padding: 12px; border: 1px solid var(--line); border-radius: 12px; background: var(--surface-soft); color: var(--text); cursor: pointer; }
.feature-switch.enabled { border-color: rgba(222, 77, 77, .55); background: rgba(222, 77, 77, .08); }
.feature-switch span:last-child { display: grid; gap: 2px; }
.switch-indicator { width: 10px; height: 10px; border-radius: 50%; background: var(--muted); flex: none; }
.feature-switch.enabled .switch-indicator { background: #d94646; box-shadow: 0 0 0 4px rgba(217, 70, 70, .14); }
.compose-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
label { display: grid; gap: 5px; color: var(--muted); font-size: 12px; }
input { min-width: 0; border: 1px solid var(--line); border-radius: 9px; background: var(--surface-soft); color: var(--text); padding: 9px 10px; }
.exercise-picker { display: flex; flex-wrap: wrap; gap: 8px; }
.exercise-choice { display: flex; align-items: center; gap: 6px; padding: 8px 10px; border: 1px solid var(--line); border-radius: 999px; color: var(--text); cursor: pointer; }
.exercise-choice input { accent-color: #d94646; }
.exercise-choice small { color: var(--muted); }
.lab-button { justify-self: start; border: 1px solid #d94646; border-radius: 9px; padding: 8px 12px; background: #d94646; color: white; cursor: pointer; }
.lab-button.secondary { background: var(--btn-ghost); border-color: var(--line); color: var(--text); }
.lab-button:disabled { cursor: not-allowed; opacity: .55; }
.chain-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(235px, 1fr)); gap: 10px; }
.chain-card { display: grid; gap: 10px; padding: 12px; border: 1px solid var(--line); border-radius: 12px; background: var(--surface-soft); }
.chain-card.unavailable { opacity: .68; }
.chain-title-row strong { display: block; }
.chain-title-row small { display: block; margin-top: 2px; font-family: monospace; }
.chain-status { font-size: 11px; color: var(--muted); white-space: nowrap; }
.step-list { display: flex; flex-wrap: wrap; gap: 6px; padding: 0; margin: 0; list-style: none; counter-reset: item; }
.step-list li { counter-increment: item; padding: 4px 7px; border-radius: 999px; background: var(--surface); font-size: 12px; }
.step-list li::before { content: counter(item) '·'; color: var(--muted); margin-right: 3px; }
.lab-message { padding: 10px 12px; border-radius: 10px; background: var(--surface-soft); color: var(--muted); font-size: 13px; }
.lab-message.error { color: #d94646; background: rgba(217, 70, 70, .08); }
.lab-message.success { color: #20885c; background: rgba(32, 136, 92, .08); }
@media (max-width: 640px) { .lab-header, .section-heading { align-items: flex-start; flex-direction: column; } .compose-fields { grid-template-columns: 1fr; } }
</style>
