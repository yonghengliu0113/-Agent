<script setup lang="ts">
import { Refresh, Search } from '@element-plus/icons-vue'
import { computed, ref } from 'vue'

import type { StaffHandoffSession, Ticket } from '@/types/api'

/**
 * 左侧队列：工单与人工会话统一在一列展示，用于快速定位要处理的会话。
 *
 * 设计要点：
 * - 只承载"选谁"这一件事，状态筛选与关键字搜索放在顶部一行；
 * - 条目用标题 + 摘要 + 时间三行信息，避免卡片套卡片；
 * - 收起时整体让位给对话主区，坐席可在窄屏下专心沟通。
 */
const props = defineProps<{
  mode: 'tickets' | 'handoff'
  queueScope: 'mine' | 'claimable'
  selectedStatuses: string[]
  statusOptions: string[]
  loading: boolean
  visibleTickets: Ticket[]
  selectedTicketNo: string | null
  handoffLoading: boolean
  visibleHandoffs: StaffHandoffSession[]
  selectedHandoffSessionId: string | null
  seenHandoffMessageIds: Record<string, number>
}>()

const emit = defineEmits<{
  'update:queueScope': [value: 'mine' | 'claimable']
  'update:selectedStatuses': [value: string[]]
  'select-ticket': [ticket: Ticket]
  'select-handoff': [session: StaffHandoffSession]
  refresh: []
}>()

/** 关键字过滤：工单按工单号/标题/订单号/问题描述，人工会话按会话号/标题/摘要。 */
const keyword = ref('')

const filteredTickets = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return props.visibleTickets
  return props.visibleTickets.filter((ticket) =>
    [ticket.ticketNo, ticket.title, ticket.orderNo, ticket.content]
      .filter(Boolean)
      .some((field) => String(field).toLowerCase().includes(q))
  )
})

const filteredHandoffs = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return props.visibleHandoffs
  return props.visibleHandoffs.filter((session) =>
    [session.session_id, session.title, session.ai_summary, session.handoff_reason]
      .filter(Boolean)
      .some((field) => String(field).toLowerCase().includes(q))
  )
})

/** 未读判断：会话最新消息 id 大于本地已读游标即视为有新消息。 */
function unreadOf(session: StaffHandoffSession): boolean {
  const seen = props.seenHandoffMessageIds[session.session_id] || 0
  const latest = session.latest_message_id || 0
  return latest > seen
}

const TICKET_STATUS: Record<string, { label: string; tone: string }> = {
  PENDING_ASSIGN: { label: '待分派', tone: 'warn' },
  ASSIGNED: { label: '已分派', tone: 'warn' },
  PROCESSING: { label: '处理中', tone: 'accent' },
  CLOSED: { label: '已关闭', tone: 'ok' },
  CANCELLED: { label: '已取消', tone: 'default' }
}

function ticketStatus(status?: string | null) {
  const key = String(status || '')
  return TICKET_STATUS[key] || { label: key || '-', tone: 'default' }
}

/** 队列条目只需要月-日 时:分，不展示秒级精度。 */
function shortTime(value?: string | null): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value).slice(5, 16)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function toggleStatus(value: string) {
  const next = props.selectedStatuses.includes(value)
    ? props.selectedStatuses.filter((item) => item !== value)
    : [...props.selectedStatuses, value]
  // 至少保留一个状态，避免空筛选导致队列永远为空
  emit('update:selectedStatuses', next.length ? next : [value])
}
</script>

<template>
  <aside class="ws-queue">
    <div class="ws-queue__head">
      <h2 class="ws-queue__title">
        {{ mode === 'tickets' ? '工单队列' : '人工会话' }}
      </h2>
      <button class="ws-iconbtn" title="刷新" aria-label="刷新队列" @click="emit('refresh')">
        <el-icon><Refresh /></el-icon>
      </button>
    </div>

    <div class="ws-queue__filters">
      <template v-if="mode === 'tickets'">
        <button
          :class="['ws-chip', queueScope === 'mine' ? 'is-active' : '']"
          @click="emit('update:queueScope', 'mine')"
        >
          我的
        </button>
        <button
          :class="['ws-chip', queueScope === 'claimable' ? 'is-active' : '']"
          @click="emit('update:queueScope', 'claimable')"
        >
          可领取
        </button>
        <el-popover placement="bottom-start" :width="200" trigger="click">
          <template #reference>
            <button class="ws-chip">状态</button>
          </template>
          <div style="display: flex; flex-direction: column; gap: 6px">
            <label
              v-for="option in statusOptions"
              :key="option"
              style="display: flex; align-items: center; gap: 8px; font-size: 12px"
            >
              <el-checkbox
                :model-value="selectedStatuses.includes(option)"
                @update:model-value="toggleStatus(option)"
              />
              {{ ticketStatus(option).label }}
            </label>
          </div>
        </el-popover>
      </template>
    </div>

    <div style="padding: 0 12px 10px">
      <el-input v-model="keyword" :prefix-icon="Search" clearable placeholder="搜索" size="small" />
    </div>

    <ul v-if="mode === 'tickets'" class="ws-queue__list">
      <li v-if="loading && !filteredTickets.length" class="ws-skel">
        <div class="ws-skel__row" />
        <div class="ws-skel__row" />
      </li>
      <li v-else-if="!filteredTickets.length" class="ws-empty" style="height: auto; padding: 28px 12px">
        <p class="ws-empty__title">暂无工单</p>
        <p class="ws-empty__desc">切换范围或状态筛选查看其它工单。</p>
      </li>
      <li v-for="ticket in filteredTickets" :key="ticket.ticketNo">
        <button
          :class="['ws-queue-item', ticket.ticketNo === selectedTicketNo ? 'is-active' : '']"
          @click="emit('select-ticket', ticket)"
        >
          <div class="ws-queue-item__top">
            <span class="ws-queue-item__who">{{ ticket.ticketNo }}</span>
            <span class="ws-queue-item__time">{{ shortTime(ticket.createdAt) }}</span>
          </div>
          <p class="ws-queue-item__preview">{{ ticket.title || ticket.content || '无标题' }}</p>
          <div class="ws-queue-item__meta">
            <span :class="['ws-tag', `ws-tag--${ticketStatus(ticket.status).tone}`]">
              {{ ticketStatus(ticket.status).label }}
            </span>
            <span v-if="ticket.priority" class="ws-tag">优先级 {{ ticket.priority }}</span>
            <span v-if="ticket.handlerId" class="ws-tag">处理人 {{ ticket.handlerId }}</span>
          </div>
        </button>
      </li>
    </ul>

    <ul v-else class="ws-queue__list">
      <li v-if="handoffLoading && !filteredHandoffs.length" class="ws-skel">
        <div class="ws-skel__row" />
        <div class="ws-skel__row" />
      </li>
      <li v-else-if="!filteredHandoffs.length" class="ws-empty" style="height: auto; padding: 28px 12px">
        <p class="ws-empty__title">暂无待接入会话</p>
        <p class="ws-empty__desc">客户点击转人工后会出现在这里。</p>
      </li>
      <li v-for="session in filteredHandoffs" :key="session.session_id">
        <button
          :class="['ws-queue-item', session.session_id === selectedHandoffSessionId ? 'is-active' : '']"
          @click="emit('select-handoff', session)"
        >
          <div class="ws-queue-item__top">
            <span class="ws-queue-item__who">
              会话 {{ session.session_id.slice(-6) }}
              <span v-if="unreadOf(session)" class="ws-queue-item__unread">1</span>
            </span>
            <span class="ws-queue-item__time">
              {{ shortTime(session.latest_message_at || session.human_requested_at) }}
            </span>
          </div>
          <p class="ws-queue-item__preview">
            {{ session.ai_summary || session.title || session.handoff_reason || '客户请求人工协助' }}
          </p>
          <div class="ws-queue-item__meta">
            <span :class="['ws-tag', session.handoff_status === 'ACTIVE' ? 'ws-tag--ok' : 'ws-tag--warn']">
              {{ session.handoff_status === 'ACTIVE' ? '接管中' : '等待接入' }}
            </span>
            <span v-if="session.linked_ticket_no" class="ws-tag">{{ session.linked_ticket_no }}</span>
          </div>
        </button>
      </li>
    </ul>
  </aside>
</template>
