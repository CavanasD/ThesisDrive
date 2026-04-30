<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  data: Object,
})
const emit = defineEmits(['close'])

const visible = ref(false)
const countdown = ref(15)
let timer = null

onMounted(() => {
  requestAnimationFrame(() => { visible.value = true })
  timer = setInterval(() => {
    countdown.value--
    if (countdown.value <= 0) dismiss()
  }, 1000)
})

onBeforeUnmount(() => clearInterval(timer))

const dismiss = () => {
  visible.value = false
  setTimeout(() => emit('close'), 500)
}
</script>

<template>
  <Teleport to="body">
    <div class="waf-backdrop" :class="{ visible }" @click.self="dismiss">
      <div class="waf-panel" :class="{ visible }">
        <div class="waf-stripe"></div>

        <div class="waf-header">
          <span class="waf-shield">⛨</span>
          <div class="waf-titles">
            <div class="waf-main-title">安全拦截</div>
            <div class="waf-sub-title">WAF · Carapace</div>
          </div>
          <button class="waf-dismiss" @click="dismiss">✕</button>
        </div>

        <div class="waf-body">
          <div class="waf-row">
            <span class="waf-label">日志编号</span>
            <span class="waf-value enc-id">{{ data?.encryptedId || '-' }}</span>
          </div>
          <div class="waf-row">
            <span class="waf-label">防御类型</span>
            <span class="waf-value defense-type">{{ data?.defenseType || '-' }}</span>
          </div>
          <div class="waf-row">
            <span class="waf-label">拦截规则</span>
            <span class="waf-value rule">{{ data?.rule || '未知规则' }}</span>
          </div>
          <div class="waf-row">
            <span class="waf-label">请求操作</span>
            <span class="waf-value">{{ data?.action || '-' }}</span>
          </div>
          <div class="waf-row">
            <span class="waf-label">拦截原因</span>
            <span class="waf-value reason">{{ data?.reason || '请求违反安全策略' }}</span>
          </div>
        </div>

        <div class="waf-footer">
          <span class="waf-hint">{{ countdown }}s 后自动关闭</span>
          <button class="waf-close-btn" @click="dismiss">我知道了</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.waf-backdrop {
  position: fixed;
  inset: 0;
  z-index: 9000;
  background: rgba(0, 0, 0, 0);
  pointer-events: none;
  transition: background 0.4s ease;
}
.waf-backdrop.visible {
  background: rgba(0, 0, 0, 0.45);
  pointer-events: all;
}

.waf-panel {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  max-width: 560px;
  margin: 0 auto;
  background: #1a1a1a;
  border-top-left-radius: 20px;
  border-top-right-radius: 20px;
  overflow: hidden;
  box-shadow: 0 -8px 40px rgba(0, 0, 0, 0.6);
  transform: translateY(100%);
  transition: transform 0.5s cubic-bezier(0.32, 0.72, 0, 1);
}
.waf-panel.visible {
  transform: translateY(0);
}

.waf-stripe {
  height: 4px;
  background: linear-gradient(90deg, #d32f2f, #ff5252, #ff1744, #d32f2f);
  background-size: 200% 100%;
  animation: stripe-move 2s linear infinite;
}
@keyframes stripe-move {
  to { background-position: -200% 0; }
}

.waf-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px 24px 12px;
}
.waf-shield {
  font-size: 32px;
  color: #ff5252;
  filter: drop-shadow(0 0 8px #ff525280);
  animation: shield-pulse 1.5s ease-in-out infinite;
}
@keyframes shield-pulse {
  0%, 100% { filter: drop-shadow(0 0 8px #ff525280); }
  50% { filter: drop-shadow(0 0 16px #ff5252cc); }
}
.waf-titles { flex: 1 }
.waf-main-title {
  font-size: 18px;
  font-weight: 700;
  color: #ff5252;
  letter-spacing: 0.04em;
}
.waf-sub-title {
  font-size: 11px;
  color: #666;
  margin-top: 2px;
  letter-spacing: 0.08em;
}
.waf-dismiss {
  background: none;
  border: none;
  color: #555;
  font-size: 18px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
  transition: color 0.2s, background 0.2s;
}
.waf-dismiss:hover { color: #ccc; background: #2a2a2a; }

.waf-body {
  padding: 0 24px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.waf-row {
  display: flex;
  gap: 12px;
  align-items: baseline;
}
.waf-label {
  font-size: 11px;
  color: #666;
  min-width: 64px;
  letter-spacing: 0.05em;
}
.waf-value {
  font-size: 13px;
  color: #ccc;
  flex: 1;
  word-break: break-all;
}
.waf-value.enc-id {
  color: #ff8a80;
  font-family: monospace;
  font-weight: 700;
  letter-spacing: 0.08em;
}
.waf-value.defense-type {
  color: #7c9fdb;
  font-family: monospace;
  font-size: 12px;
}
.waf-value.rule {
  color: #ffb74d;
  font-weight: 600;
}
.waf-value.reason {
  color: #aaa;
  font-style: italic;
  font-size: 12px;
}

.waf-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px 28px;
  border-top: 1px solid #2a2a2a;
}
.waf-hint {
  font-size: 11px;
  color: #444;
}
.waf-close-btn {
  background: #d32f2f;
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 8px 20px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
}
.waf-close-btn:hover { background: #b71c1c; }
</style>
