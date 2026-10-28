<script setup lang="ts">
import { Refresh, SwitchButton } from '@element-plus/icons-vue'

import type { StaffHandoffSession, Ticket } from '@/types/api'
import { statusType } from '@/utils/ticket'

/**
 * 坐席左侧工作队列。
 * 承载工单/人工会话切换、队列范围、状态筛选与列表选择，
 * 只通过事件把刷新、选中、退出和页面跳转交给父页面处理。
 */
defineProps<{
  workMode: 'tickets' | 'handoff'
  handoffCount: number
  displayName?: string
  queueScope: 'mine' | 'claimable'
  selectedStatuses: string[]
  statusOptions: string[]
  loading: boolean
  visibleTickets: Ticket[]
  selectedTicketNo: string | null
  handoffScope: 'pending' | 'mine'
  handoffLoading: boolean
  visibleHandoffs: StaffHandoffSession[]
  selectedHandoffSessionId: string | null
  seenHandoffMessageIds: Record<string, number>
}>()

const emit = defineEmits<{
  'update:workMode': [value: 'tickets' | 'handoff']
  'update:queueScope': [value: 'mine' | 'claimable']
  'update:selectedStatuses': [value: string[]]
  'update:handoffScope': [value: 'pending' | 'mine']
  'select-ticket': [ticket: Ticket]
  'select-handoff': [session: StaffHandoffSession]
  'refresh-tickets': []
  'refresh-handoffs': []
  logout: []
  'open-rag': []
  'open-monitor': []
}>()

function handleWorkModeChange(value: string | number | boolean) {
  if (value === 'tickets' || value === 'handoff') emit('update:workMode', value)
}

function handleQueueScopeChange(value: string | number | boolean) {
  if (value === 'mine' || value === 'claimable') emit('update:queueScope', value)
}

function handleStatusesChange(value: string[]) {
  emit('update:selectedStatuses', value)
}

function handleHandoffScopeChange(value: string | number | boolean) {
  if (value === 'pending' || value === 'mine') emit('update:handoffScope', value)
}
</script>

<template>
  <el-aside class="sidebar" width="360px">
    <div class="sidebar-header">
      <h2>我的工单</h2>
      <div class="header-actions">
        <el-button plain @click="emit('open-rag')">RAG 评测</el-button>
        <el-button plain @click="emit('open-monitor')">系统监控</el-button>
        <el-button :icon="SwitchButton" plain @click="emit('logout')">退出</el-button>
      </div>
    </div>
    <p class="muted">当前坐席：{{ displayName }}</p>

    <el-segmented
      :model-value="workMode"
      :options="[
        { label: '工单', value: 'tickets' },
        { label: `人工会话 ${handoffCount}`, value: 'handoff' }
      ]"
      class="full-button"
      @update:model-value="handleWorkModeChange"
    />

    <template v-if="workMode === 'tickets'">
      <el-segmented
        :model-value="queueScope"
        :options="[
          { label: '我的', value: 'mine' },
          { label: '可领取', value: 'claimable' }
        ]"
        class="full-button"
        @update:model-value="handleQueueScopeChange"
      />
      <el-select
        :model-value="selectedStatuses"
        class="full-button"
        multiple
        collapse-tags
        collapse-tags-tooltip
        @update:model-value="handleStatusesChange"
      >
        <el-option v-for="status in statusOptions" :key="status" :label="status" :value="status" />
      </el-select>
      <el-button :icon="Refresh" :loading="loading" class="full-button" @click="emit('refresh-tickets')">刷新工单</el-button>
    </template>
    <template v-else>
      <el-segmented
        :model-value="handoffScope"
        :options="[{ label: '待接入', value: 'pending' }, { label: '我的会话', value: 'mine' }]"
        class="full-button"
        @update:model-value="handleHandoffScopeChange"
      />
      <el-button :icon="Refresh" :loading="handoffLoading" class="full-button" @click="emit('refresh-handoffs')">
        刷新人工会话
      </el-button>
    </template>

    <div v-if="workMode === 'tickets'" class="ticket-list">
      <button
        v-for="ticket in visibleTickets"
        :key="ticket.ticketNo"
        :class="['ticket-item', { active: ticket.ticketNo === selectedTicketNo }]"
        @click="emit('select-ticket', ticket)"
      >
        <strong>{{ ticket.ticketNo }}</strong>
        <span>{{ ticket.title }}</span>
        <div>
          <el-tag :type="statusType(ticket.status)" size="small">{{ ticket.status }}</el-tag>
          <el-tag size="small" type="warning">{{ ticket.priority || 'medium' }}</el-tag>
        </div>
        <small>处理人：{{ ticket.handlerId || '未分配' }}</small>
        <small v-if="ticket.urgeCount">催办：{{ ticket.urgeCount }} 次</small>
      </button>
      <el-empty v-if="!visibleTickets.length && !loading" description="当前队列没有工单" />
    </div>
    <div v-else class="ticket-list">
      <button
        v-for="session in visibleHandoffs"
        :key="session.session_id"
        :class="['ticket-item', { active: session.session_id === selectedHandoffSessionId }]"
        @click="emit('select-handoff', session)"
      >
        <strong>{{ session.title || session.session_id }}</strong>
        <span>客户：{{ session.customer_id }}</span>
        <div>
          <el-tag :type="session.handoff_status === 'ACTIVE' ? 'success' : 'warning'" size="small">
            {{ session.handoff_status === 'ACTIVE' ? '已接入' : '待接入' }}
          </el-tag>
          <el-tag v-if="session.handoff_reason" size="small" type="info">{{ session.handoff_reason }}</el-tag>
          <el-tag
            v-if="session.last_sender_type === 'customer' && (session.latest_message_id || 0) > (seenHandoffMessageIds[session.session_id] || 0)"
            size="small"
            type="danger"
          >新消息</el-tag>
        </div>
        <small>接入人：{{ session.human_assigned_staff_name || '未接入' }}</small>
        <small v-if="session.linked_ticket_no">跟进工单：{{ session.linked_ticket_no }}</small>
        <small>更新时间：{{ session.updated_at || '-' }}</small>
      </button>
      <el-empty v-if="!visibleHandoffs.length && !handoffLoading" description="当前没有待接入人工会话" />
    </div>
  </el-aside>
</template>
