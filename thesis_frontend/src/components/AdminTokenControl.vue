<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import {
  clearAdminToken,
  getAdminToken,
  setAdminToken,
  subscribeAdminToken,
} from '../services/adminApi'

const props = defineProps({
  status: { type: String, default: 'locked' },
})
const emit = defineEmits(['change'])

const token = ref(getAdminToken())
const reveal = ref(false)
const statusMeta = computed(() => ({
  locked: { label: '未配置', tone: 'muted' },
  connecting: { label: '认证中', tone: 'busy' },
  connected: { label: '已认证', tone: 'ok' },
  unauthorized: { label: '认证失败', tone: 'danger' },
  error: { label: '连接异常', tone: 'danger' },
}[props.status] || { label: props.status, tone: 'muted' }))

const unsubscribe = subscribeAdminToken((next) => { token.value = next })
onBeforeUnmount(unsubscribe)

const save = () => {
  const next = setAdminToken(token.value)
  emit('change', next)
}

const clear = () => {
  token.value = ''
  clearAdminToken()
  emit('change', '')
}
</script>

<template>
  <form class="admin-token" @submit.prevent="save">
    <span class="admin-state" :class="statusMeta.tone" role="status">
      <span class="admin-state-dot" aria-hidden="true"></span>
      {{ statusMeta.label }}
    </span>
    <label class="admin-secret">
      <span class="sr-only">Carapace 管理令牌</span>
      <input
        v-model="token"
        :type="reveal ? 'text' : 'password'"
        autocomplete="current-password"
        spellcheck="false"
        placeholder="管理令牌"
      />
      <button type="button" class="admin-reveal" :aria-label="reveal ? '隐藏令牌' : '显示令牌'" @click="reveal = !reveal">
        {{ reveal ? '隐藏' : '显示' }}
      </button>
    </label>
    <button type="submit" class="admin-apply">连接</button>
    <button v-if="token" type="button" class="admin-clear" aria-label="清除管理令牌" @click="clear">×</button>
  </form>
</template>

<style scoped>
.admin-token {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.admin-state {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--muted);
  font-size: 10px;
  font-weight: 650;
  white-space: nowrap;
}
.admin-state-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 0 3px color-mix(in srgb, currentColor 14%, transparent);
}
.admin-state.ok { color: #2ea86e; }
.admin-state.busy { color: #d89426; }
.admin-state.danger { color: #e34141; }
.admin-secret {
  display: flex;
  align-items: center;
  width: clamp(150px, 18vw, 230px);
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--surface);
  overflow: hidden;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.admin-secret:focus-within {
  border-color: #e34141;
  box-shadow: 0 0 0 3px rgba(227, 65, 65, 0.09);
}
.admin-secret input {
  width: 100%;
  min-width: 0;
  border: 0;
  outline: 0;
  padding: 6px 8px;
  background: transparent;
  color: var(--text);
  font: 11px/1.2 monospace;
}
.admin-reveal,
.admin-apply,
.admin-clear {
  border: 0;
  color: var(--muted);
  background: transparent;
  font-size: 10px;
  cursor: pointer;
  white-space: nowrap;
}
.admin-reveal { padding: 6px 7px; }
.admin-apply {
  padding: 6px 10px;
  border: 1px solid rgba(227, 65, 65, 0.38);
  border-radius: 7px;
  color: #e34141;
  font-weight: 700;
}
.admin-clear { padding: 4px; font-size: 15px; }
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
@media (max-width: 760px) {
  .admin-token { width: 100%; }
  .admin-secret { flex: 1; width: auto; }
}
</style>
