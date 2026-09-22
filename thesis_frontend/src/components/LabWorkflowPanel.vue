<script setup>
import { computed, onMounted, reactive, ref } from 'vue'

const props = defineProps({
  client: { type: Object, required: true },
  auth: { type: Object, required: true },
})

// 与后端 thesis_attack_lab/_extension.py 的 FEATURE_ENV 保持一致。
// 新增漏洞点时，这里与后端必须同步，否则面板会漏显示开关。
const FEATURE_META = {
  sqli: { label: 'SQL 注入', short: '注入' },
  jwt_weak_secret: { label: 'JWT 弱密钥', short: '伪造' },
  listing_sort: { label: '文件列表排序注入', short: '业务面' },
}

// 与后端 EXERCISE_FEATURES 保持一致。feature 字段决定该步是否受某开关控制。
const EXERCISE_META = {
  // 第 1 条 —— 文件列表「按时间排序」注入
  sqli_probe: { label: '① 确认参数可控（合法值）', feature: 'sqli' },
  sqli_inject: { label: '② 确认注入位置（拼接子查询）', feature: 'sqli' },
  sqli_exfil: { label: '③ 报错带外读取版本', feature: 'sqli' },
  // 第 2 条 —— JWT 弱 HMAC 密钥 → 伪造 admin
  jwt_forge: { label: '① 用 secret123 自签 admin 令牌', feature: 'jwt_weak_secret' },
  jwt_admin_login: { label: '② 拿令牌调业务接口验证身份', feature: 'jwt_weak_secret' },
  // 第 3 条 —— 业务面 ORDER BY 注入
  listing_probe: { label: '① 文件列表按时间排序（合法）', feature: 'listing_sort' },
  listing_inject: { label: '② 排序字段拼接子查询', feature: 'listing_sort' },
  listing_exfil: { label: '③ 报错带外读取数据库版本', feature: 'listing_sort' },
}

// 重点链的展示顺序与副标题（与 require.txt 的两条重点链对应）。
const FOCUS_CHAIN_ORDER = ['sqli_chain', 'jwt_admin_chain', 'listing_orderby_chain']
const FOCUS_CHAIN_NOTE = {
  sqli_chain: '业务面 · 文件列表排序直接注入数据库',
  jwt_admin_chain: '重点 · 弱 HMAC 密钥伪造管理员身份',
  listing_orderby_chain: '业务面 · 普通用户点文件列表排序即可触发',
}

// 已下线的链：后端漏洞点已移除，面板以绿色「已修复」置灰呈现。
const FIXED_CHAIN_META = {
  identity_takeover: { title: 'Identity Takeover', reason: '依赖的 lab_* 桩动作已下线' },
  sandbox_breach: { title: 'Sandbox Breach', reason: '依赖的 lab_* 桩动作已下线' },
  hot_plugin_chain: { title: 'Hot Plugin Chain', reason: '依赖的 lab_* 桩动作已下线' },
}

const status = ref(null)
const loading = ref(false)
const error = ref('')
const chainForm = reactive({ id: '', title: '', steps: [] })
const lastStep = ref(null)
const chainEvidence = ref({})

const enabledFeatures = computed(() => new Set(status.value?.enabled_features || []))
// 重点链排在最前，其余保持后端返回顺序，避免学生翻找。
const chains = computed(() => {
  const all = status.value?.chains || []
  const rank = (id) => {
    const i = FOCUS_CHAIN_ORDER.indexOf(id)
    return i === -1 ? FOCUS_CHAIN_ORDER.length : i
  }
  return [...all].sort((a, b) => rank(a.id) - rank(b.id))
})
const focusChains = computed(() => chains.value.filter((c) => FOCUS_CHAIN_ORDER.includes(c.id)))
const otherChains = computed(() => chains.value.filter((c) => !FOCUS_CHAIN_ORDER.includes(c.id)))
const focusEnabledCount = computed(
  () => focusChains.value.filter((c) => c.available).length,
)
const exercises = computed(() => status.value?.available_exercises || Object.keys(EXERCISE_META))

const isFocusChain = (id) => FOCUS_CHAIN_ORDER.includes(id)
const focusNote = (id) => FOCUS_CHAIN_NOTE[id] || ''
// 已下线链（后端漏洞点已移除），面板置灰 + 绿色「已修复」标记。
const isFixedChain = (chain) => chain?.status === 'fixed' || !!FIXED_CHAIN_META[chain?.id]
// 列出该链当前缺失的开关，便于蓝方一键定位要打开哪个漏洞点。
const missingFeatures = (chain) => {
  const needed = new Set(
    (chain.steps || []).map((step) => EXERCISE_META[step]?.feature).filter(Boolean),
  )
  return [...needed].filter((feature) => !enabledFeatures.value.has(feature))
}

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
          <span>{{ chains.length }} 条 · 重点链 {{ focusEnabledCount }}/{{ focusChains.length }} 就绪</span>
        </div>
        <div class="chain-list">
          <article
            v-for="chain in chains"
            :key="chain.id"
            class="chain-card"
            :class="{
              unavailable: !chain.available,
              focus: isFocusChain(chain.id),
              fixed: isFixedChain(chain),
            }"
          >
            <div class="chain-title-row">
              <div><strong>{{ chain.title }}</strong><small>{{ chain.id }}</small></div>
              <span class="chain-status" :class="{ fixed: isFixedChain(chain) }">
                {{ isFixedChain(chain) ? '已修复' : (chain.available ? '可推进' : '缺少漏洞开关') }}
              </span>
            </div>
            <p v-if="focusNote(chain.id)" class="chain-note">{{ focusNote(chain.id) }}</p>
            <p v-if="isFixedChain(chain)" class="chain-note fixed-note">
              {{ chain.fixed_reason || FIXED_CHAIN_META[chain.id]?.reason }}
            </p>
            <ol v-if="chain.steps.length" class="step-list">
              <li v-for="step in chain.steps" :key="step">{{ EXERCISE_META[step]?.label || step }}</li>
            </ol>
            <p v-else class="chain-note">该教学链的步骤已随漏洞点一并下线。</p>
            <p v-if="!chain.available && !isFixedChain(chain)" class="chain-hint">
              需开启：
              <code v-for="f in missingFeatures(chain)" :key="f">{{ FEATURE_META[f]?.label || f }}</code>
            </p>
            <button
              class="lab-button secondary"
              :disabled="!chain.available || isFixedChain(chain)"
              @click="advanceChain(chain)"
            >
              {{ isFixedChain(chain) ? '已修复 · 不可推进' : '推进下一步' }}
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
.chain-card.focus { border-color: rgba(217, 70, 70, .45); background: rgba(217, 70, 70, .05); }
.chain-card.fixed { border-color: rgba(32, 136, 92, .45); background: rgba(32, 136, 92, .06); opacity: .85; }
.chain-status.fixed { color: #20885c; font-weight: 700; }
.fixed-note { color: #20885c; }
.chain-note { margin: 0; color: var(--muted); font-size: 12px; }
.chain-hint { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 0; color: #d94646; font-size: 12px; }
.chain-hint code { padding: 2px 6px; border-radius: 6px; background: rgba(217, 70, 70, .12); font-size: 11px; }
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
