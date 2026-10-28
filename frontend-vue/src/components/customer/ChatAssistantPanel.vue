<script setup lang="ts">
import { Connection, Headset, Message, Refresh, Service, Tickets } from '@element-plus/icons-vue'
import { computed } from 'vue'

import ChatComposer from '@/components/customer/chat/ChatComposer.vue'
import ChatHandoffStatusCard from '@/components/customer/chat/ChatHandoffStatusCard.vue'
import ChatMessageList from '@/components/customer/chat/ChatMessageList.vue'
import type { AgentReply, ChatMessage, ChatSession, CustomerOrder, Ticket } from '@/types/api'

/**
 * 智能客服聊天面板容器。
 * 负责组合头部、上下文条、人工状态卡、消息列表、快捷操作与输入区，
 * 并把子组件事件原样上抛给父页面；不直接发起网络请求。
 * 对外 props / emits 与拆分前完全一致。
 */
const props = defineProps<{
  messages: ChatMessage[]
  lastReply: AgentReply | null
  modelValue: string
  session: ChatSession | null
  submitting?: boolean
  selectedOrder: CustomerOrder | null
  selectedTicket: Ticket | null
  /** 当前输入框的受控业务语境，仅用于引导客户补充信息。 */
  composerHint?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'cancel-handoff': []
  // 单一对话流：提交时由父组件根据人工接管状态决定投递通道。
  submit: []
  cancel: []
  quick: [action: string]
  regenerate: [message: string]
  upload: [file: File]
  'download-attachment': [message: ChatMessage]
}>()

const handoffStatusText = computed(() => ({ PENDING: '待接入', ACTIVE: '已接入', CLOSED: '已结束' }[String(props.session?.handoff_status)] || ''))
const handoffStatusType = computed<'success' | 'info' | 'warning'>(() =>
  props.session?.handoff_status === 'ACTIVE' ? 'success' : props.session?.handoff_status === 'CLOSED' ? 'info' : 'warning'
)

/** 客户可见的会话工单号：优先取会话预建工单，其次取前端选中的工单。 */
const sessionTicketNo = computed(() => props.session?.ticket_no || props.selectedTicket?.ticketNo || '')

function handleUpdateModelValue(value: string) {
  emit('update:modelValue', value)
}

function handleUpload(file: File) {
  emit('upload', file)
}

function handleRegenerate(message: string) {
  emit('regenerate', message)
}

function handleDownloadAttachment(message: ChatMessage) {
  emit('download-attachment', message)
}
</script>

<template>
  <section class="chat-panel dashboard-card">
    <div class="chat-header">
      <div>
        <h2>在线客服</h2>
        <p><span class="online-dot"></span>智能助手 · 7x24小时为您服务</p>
      </div>
      <div class="chat-header-actions">
        <el-button :icon="Headset" plain @click="emit('quick', '转人工客服')">转人工客服</el-button>
      </div>
    </div>

    <div class="chat-context-strip">
      <span v-if="selectedOrder">
        <el-icon><Message /></el-icon>
        当前订单：{{ selectedOrder.orderNo }}
      </span>
      <span v-if="sessionTicketNo">
        <el-icon><Tickets /></el-icon>
        当前工单：{{ sessionTicketNo }}
      </span>
      <span v-if="!selectedOrder && !sessionTicketNo">当前为无订单咨询，可直接提问规则、发票、会员或人工服务问题</span>
    </div>

    <ChatHandoffStatusCard
      :session="session"
      :status-text="handoffStatusText"
      :status-type="handoffStatusType"
      :session-ticket-no="sessionTicketNo"
      :selected-order="selectedOrder"
      @cancel-handoff="emit('cancel-handoff')"
    />

    <ChatMessageList
      :messages="messages"
      :last-reply="lastReply"
      :submitting="submitting"
      @regenerate="handleRegenerate"
      @download-attachment="handleDownloadAttachment"
    />

    <div class="quick-actions">
      <el-button :disabled="!selectedOrder" :icon="Connection" @click="emit('quick', '查询物流')">查看物流</el-button>
      <el-button :disabled="!selectedOrder" :icon="Refresh" @click="emit('quick', '申请退货')">申请退货退款</el-button>
      <el-button :icon="Tickets" @click="emit('quick', '催办工单')">催办工单</el-button>
      <el-button :icon="Service" @click="emit('quick', '转人工客服')">转人工客服</el-button>
    </div>

    <ChatComposer
      :model-value="modelValue"
      :session="session"
      :submitting="submitting"
      :composer-hint="composerHint"
      @update:model-value="handleUpdateModelValue"
      @submit="emit('submit')"
      @cancel="emit('cancel')"
      @upload="handleUpload"
    />
  </section>
</template>
