<script setup lang="ts">
import { computed } from 'vue'

import type { ChatSession } from '@/types/api'

/**
 * 历史咨询抽屉：展示客户全部会话及人工状态，点击后由父页面关闭抽屉并切换会话。
 */
const props = defineProps<{
  modelValue: boolean
  sessions: ChatSession[]
  selectedSessionId: string | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  select: [session: ChatSession]
}>()

/** 把抽屉开关桥接为受控 v-model，避免子组件直接修改 props。 */
const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value)
})

/** 人工接管状态的中文展示。 */
function handoffStatusLabel(status?: string | null) {
  if (status === 'PENDING') return '人工排队中'
  if (status === 'ACTIVE') return '人工已接入'
  if (status === 'CLOSED') return '人工已结束'
  return '智能对话'
}

/** 会话创建时间格式化为月-日 时:分；无时区信息按 UTC 处理。 */
function formatHistoryTime(value?: string | null) {
  if (!value) return ''
  const date = new Date(value.includes('T') && !/[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? `${value}Z` : value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date)
}
</script>

<template>
  <el-drawer v-model="visible" title="历史咨询" size="380px">
    <el-empty v-if="!sessions.length" description="暂无历史咨询" />
    <div v-else class="history-session-list">
      <button
        v-for="session in sessions"
        :key="session.session_id"
        :class="['history-session-item', { active: session.session_id === selectedSessionId }]"
        type="button"
        @click="emit('select', session)"
      >
        <div class="history-session-item__head">
          <strong>{{ session.title || session.session_id }}</strong>
          <em>{{ handoffStatusLabel(session.handoff_status) }}</em>
        </div>
        <span>{{ formatHistoryTime(session.created_at) }}</span>
      </button>
    </div>
  </el-drawer>
</template>
