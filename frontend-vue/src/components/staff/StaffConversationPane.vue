<script setup lang="ts">
import { ChatDotRound, InfoFilled, Loading, Paperclip } from '@element-plus/icons-vue'
import { computed, nextTick, ref, watch } from 'vue'

import type { ChatMessage } from '@/types/api'

/**
 * 会话主区：消息时间线 + 输入框。
 *
 * 这是坐席与客户沟通的唯一入口，工单模式与人工接管模式共用同一套交互，
 * 避免"工单页只能看不能回"的割裂体验。数据由父组件注入，组件只负责展示与上抛事件。
 */
const props = defineProps<{
  /** 标题：人工模式为客户标识，工单模式为工单号 */
  title: string
  /** 副标题：会话编号、请求时间等一行摘要 */
  subtitle?: string
  /** 标题右侧状态标签 */
  tags?: { text: string; tone?: 'accent' | 'ok' | 'warn' | 'danger' | 'default' }[]
  messages: ChatMessage[]
  loading?: boolean
  sending?: boolean
  /** 是否允许发送；false 时输入框禁用并展示原因 */
  canReply: boolean
  /** 不能发送时的原因说明 */
  replyHint?: string
  emptyTitle?: string
  emptyDesc?: string
  draft: string
}>()

const emit = defineEmits<{
  'update:draft': [value: string]
  send: []
  'load-history': []
}>()

const streamRef = ref<HTMLElement | null>(null)
const showJump = ref(false)

/** 发送者类型归一化：未知类型按系统提示处理，避免被当成客户发言。 */
function senderKind(message: ChatMessage): 'customer' | 'ai' | 'staff' | 'system' {
  const type = String(message.sender_type || '').toLowerCase()
  if (type === 'customer' || type === 'ai' || type === 'staff') return type
  return 'system'
}

const SENDER_LABEL: Record<string, string> = {
  customer: '客户',
  ai: 'AI 助手',
  staff: '坐席'
}

/** 提取附件元数据，用于气泡内的下载入口。 */
function attachmentOf(message: ChatMessage) {
  const attach = message.extra_data?.attachment
  return attach?.stored_name ? attach : null
}

/** 时间格式：只保留时分，日期由上方分隔条承担，减少气泡噪音。 */
function timeOf(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

/** 日期分隔文案：今天/昨天/月-日，避免每行都重复日期。 */
function dayKey(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`
}

function dayLabel(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const today = new Date()
  const sameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
  if (sameDay(date, today)) return '今天'
  const yesterday = new Date(today.getTime() - 86400000)
  if (sameDay(date, yesterday)) return '昨天'
  return `${date.getMonth() + 1} 月 ${date.getDate()} 日`
}

/** 把消息按天分组，用于插入日期分隔条。 */
const grouped = computed(() => {
  const rows: { key: string; label: string; messages: ChatMessage[] }[] = []
  for (const message of props.messages) {
    const key = dayKey(message.created_at)
    const last = rows[rows.length - 1]
    if (last && last.key === key) {
      last.messages.push(message)
    } else {
      rows.push({ key, label: dayLabel(message.created_at), messages: [message] })
    }
  }
  return rows
})

/** 滚动到底部；仅在用户已接近底部时自动跟随，避免打断向上翻历史。 */
async function scrollToBottom(force = false) {
  await nextTick()
  const el = streamRef.value
  if (!el) return
  if (force || el.scrollHeight - el.scrollTop - el.clientHeight < 260) {
    el.scrollTop = el.scrollHeight
    showJump.value = false
  } else {
    showJump.value = true
  }
}

watch(
  () => props.messages.length,
  () => {
    // 坐席自己发出的消息必须可见，历史轮询新增消息则只在接近底部时跟随
    const last = props.messages[props.messages.length - 1]
    void scrollToBottom(last?.sender_type === 'staff')
  }
)
watch(() => props.title, () => void scrollToBottom(true))

function onStreamScroll() {
  const el = streamRef.value
  if (!el) return
  showJump.value = el.scrollHeight - el.scrollTop - el.clientHeight > 260
}

/** Enter 发送，Shift+Enter 换行；输入法组合期间不触发，避免中文候选被误发送。 */
function onKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey) return
  if (event.isComposing) return
  event.preventDefault()
  submit()
}

function submit() {
  const text = props.draft.trim()
  if (!text || !props.canReply || props.sending) return
  emit('send')
}
</script>

<template>
  <section class="ws-main">
    <header class="ws-conv__head">
      <div class="ws-conv__who">
        <h2 class="ws-conv__name">
          {{ title }}
          <span v-for="tag in tags || []" :key="tag.text" :class="['ws-tag', tag.tone ? `ws-tag--${tag.tone}` : '']">
            {{ tag.text }}
          </span>
        </h2>
        <p v-if="subtitle" class="ws-conv__sub">{{ subtitle }}</p>
      </div>
      <div class="ws-conv__actions">
        <slot name="actions" />
      </div>
    </header>

    <div ref="streamRef" class="ws-conv__stream" @scroll.passive="onStreamScroll">
      <div v-if="loading" class="ws-skel">
        <div class="ws-skel__row" />
        <div class="ws-skel__row" />
        <div class="ws-skel__row" />
      </div>

      <div v-else-if="!messages.length" class="ws-empty">
        <div class="ws-empty__icon">
          <el-icon><ChatDotRound /></el-icon>
        </div>
        <p class="ws-empty__title">{{ emptyTitle || '暂无对话' }}</p>
        <p class="ws-empty__desc">{{ emptyDesc || '客户在本会话中的消息会显示在这里。' }}</p>
      </div>

      <template v-else>
        <div v-for="group in grouped" :key="group.key">
          <div class="ws-day">{{ group.label }}</div>
          <div
            v-for="message in group.messages"
            :key="message.id"
            :class="['ws-msg', `ws-msg--${senderKind(message)}`]"
          >
            <div class="ws-msg__avatar">
              {{ senderKind(message) === 'customer' ? '客' : senderKind(message) === 'staff' ? '席' : 'AI' }}
            </div>
            <div class="ws-msg__body">
              <div class="ws-msg__meta">
                <span class="ws-msg__author">{{ SENDER_LABEL[senderKind(message)] || '系统' }}</span>
                <span>{{ timeOf(message.created_at) }}</span>
              </div>
              <div class="ws-msg__bubble">
                {{ message.content }}
                <a
                  v-if="attachmentOf(message)"
                  class="ws-msg__attach"
                  :href="`/api/staff/handoff/sessions/${message.session_id}/attachment/${message.id}`"
                  target="_blank"
                  rel="noopener"
                >
                  <el-icon><Paperclip /></el-icon>
                  {{ attachmentOf(message)?.name || '附件' }}
                </a>
              </div>
            </div>
          </div>
        </div>
      </template>

      <button v-if="showJump" class="ws-jump" @click="scrollToBottom(true)">
        回到最新
      </button>
    </div>

    <footer class="ws-composer">
      <div v-if="!canReply && replyHint" class="ws-composer__hint">
        <el-icon><InfoFilled /></el-icon>
        <span>{{ replyHint }}</span>
      </div>
      <div class="ws-composer__box">
        <textarea
          :value="draft"
          :disabled="!canReply"
          :placeholder="canReply ? '输入回复，Enter 发送，Shift + Enter 换行' : '当前不可发送'"
          @input="emit('update:draft', ($event.target as HTMLTextAreaElement).value)"
          @keydown="onKeydown"
        />
        <div class="ws-composer__bar">
          <slot name="composer-extra" />
          <span class="ws-composer__bar-spacer" />
          <span v-if="canReply" class="ws-composer__tip">Enter 发送</span>
          <button class="ws-btn ws-btn--primary" :disabled="!canReply || !draft.trim() || sending" @click="submit">
            <el-icon v-if="sending" class="is-loading"><Loading /></el-icon>
            {{ sending ? '发送中' : '发送' }}
          </button>
        </div>
      </div>
    </footer>
  </section>
</template>
