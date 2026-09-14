<script setup>
import { computed } from 'vue'
import { renderSafeMarkdown } from '../utils/markdown'

const props = defineProps({
  source: { type: String, default: '' },
})

const rendered = computed(() => renderSafeMarkdown(props.source))
</script>

<template>
  <div class="markdown-view" v-html="rendered"></div>
</template>

<style scoped>
.markdown-view { color: inherit; line-height: 1.75; overflow-wrap: anywhere; }
.markdown-view :deep(h1), .markdown-view :deep(h2), .markdown-view :deep(h3) { margin: 1.1em 0 .45em; line-height: 1.25; }
.markdown-view :deep(h1) { font-size: 1.45rem; }
.markdown-view :deep(h2) { font-size: 1.2rem; }
.markdown-view :deep(h3) { font-size: 1.05rem; }
.markdown-view :deep(p) { margin: .65em 0; }
.markdown-view :deep(ul), .markdown-view :deep(ol) { margin: .55em 0; padding-left: 1.45rem; }
.markdown-view :deep(code) { padding: .14rem .35rem; border: 1px solid #d7d1c6; border-radius: 4px; background: #f4f0e8; font: .88em/1.5 ui-monospace, SFMono-Regular, Consolas, monospace; }
.markdown-view :deep(pre) { margin: .8rem 0; padding: .9rem 1rem; overflow: auto; border: 1px solid #d7d1c6; border-radius: 8px; background: #1e2529; color: #f5f1e8; }
.markdown-view :deep(pre code) { padding: 0; border: 0; background: transparent; color: inherit; }
.markdown-view :deep(blockquote) { margin: .75rem 0; padding-left: .85rem; border-left: 3px solid #b64934; color: #5b625f; }
.markdown-view :deep(a) { color: #155c55; text-underline-offset: 3px; }
</style>
