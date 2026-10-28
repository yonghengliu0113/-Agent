<script setup lang="ts">
import { CopyDocument, Document, Refresh } from '@element-plus/icons-vue'

/** AI 回复底部操作区：复制 / 刷新 / 参考文献，参考文献无数据时隐藏。 */
const props = defineProps<{
  referencesCount: number
  referencesExpanded: boolean
  submitting?: boolean
  disabled?: boolean
}>()

const emit = defineEmits<{
  copy: []
  regenerate: []
  'toggle-references': []
}>()

defineOptions({ name: 'MessageActions' })
</script>

<template>
  <div class="message-actions" role="group" aria-label="AI 回复操作">
    <el-tooltip content="复制正文" placement="top">
      <el-button class="message-actions__button" text size="small" :icon="CopyDocument" :disabled="props.disabled" @click="emit('copy')">复制</el-button>
    </el-tooltip>
    <el-tooltip content="重新生成回复" placement="top">
      <el-button class="message-actions__button" text size="small" :icon="Refresh" :disabled="props.disabled || props.submitting" @click="emit('regenerate')">刷新</el-button>
    </el-tooltip>
    <el-tooltip v-if="props.referencesCount > 0" :content="props.referencesExpanded ? '收起参考文献' : '展开参考文献'" placement="top">
      <el-button
        class="message-actions__button"
        text
        size="small"
        :icon="Document"
        :aria-expanded="String(props.referencesExpanded)"
        :aria-pressed="String(props.referencesExpanded)"
        @click="emit('toggle-references')"
      >参考文献 ({{ props.referencesCount }})</el-button>
    </el-tooltip>
  </div>
</template>
