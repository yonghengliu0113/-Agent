<script setup lang="ts">
defineOptions({ name: 'CustomerHome' })

import { ElMessage } from 'element-plus'
import { storeToRefs } from 'pinia'
import { onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import ChatAssistantPanel from '@/components/customer/ChatAssistantPanel.vue'
import CustomerHistoryDrawer from '@/components/customer/CustomerHistoryDrawer.vue'
import CustomerServiceHeader from '@/components/customer/CustomerServiceHeader.vue'
import CustomerSidebar from '@/components/customer/CustomerSidebar.vue'
import { useCustomerChat } from '@/composables/useCustomerChat'
import { useCustomerConversation } from '@/composables/useCustomerConversation'
import { useCustomerRouteContext } from '@/composables/useCustomerRouteContext'
import { useCustomerWorkspace } from '@/composables/useCustomerWorkspace'
import { useAuthStore } from '@/stores/auth'
import { useCustomerSessionStore } from '@/stores/customerSessions'
import type { ChatSession } from '@/types/api'

/**
 * 客户智能客服页容器。
 * 负责组合侧栏、页头、聊天面板与历史抽屉，并串联工作区数据、会话数据、
 * 聊天交互和外部路由上下文；具体展示与请求逻辑分别下沉到子组件和 composable。
 */
const auth = useAuthStore()
const route = useRoute()
const sessionStore = useCustomerSessionStore()
const { sessions } = storeToRefs(sessionStore)
const selectedSessionId = ref<string | null>(null)

const workspace = useCustomerWorkspace({ sessions, selectedSessionId })
const conversation = useCustomerConversation({
  sessions,
  selectedSessionId,
  onSessionsRefreshed: workspace.cacheCustomerWorkspace
})
const chat = useCustomerChat({ conversation, workspace })
const routeContext = useCustomerRouteContext({
  sessions,
  orders: workspace.orders,
  tickets: workspace.tickets,
  selectedSessionId,
  selectedOrderNo: workspace.selectedOrderNo,
  selectedTicketNo: workspace.selectedTicketNo,
  messageText: chat.messageText,
  selectSession: conversation.selectSession,
  createNewSession
})

const {
  agentStatus,
  selectedOrder,
  selectedTicket,
  selectedOrderNo,
  selectedTicketNo
} = workspace
const {
  selectedSession,
  messages,
  lastReply,
  loadingMessages,
  creatingSession,
  selectSession,
  handleSessionsChanged
} = conversation
const {
  messageText,
  composerMode,
  submitting,
  composerHint,
  submitQuestion,
  cancelCurrentGeneration,
  fillAndMaybeSend,
  regenerateAnswer,
  handleUploadAttachment,
  handleDownloadAttachment,
  cancelHandoff,
  stopMessagePolling,
  scheduleMessagePolling,
  handleVisibilityChange
} = chat
const { applyRouteContext, resetHandledContext } = routeContext

const historyVisible = ref(false)
const loadingWorkspace = ref(false)
const activatedOnce = ref(false)

/** 新建会话后清空输入框，避免上一轮草稿带入新会话。 */
async function createNewSession() {
  const created = await conversation.createNewSession()
  if (created) chat.resetInput()
  return created
}

/** 历史抽屉选择会话：先关闭抽屉，再切换到目标会话。 */
async function selectHistorySession(session: ChatSession) {
  historyVisible.value = false
  await selectSession(session.session_id)
}

/** 选中/取消选中订单；切换上下文时同步清理售后草稿语境。 */
function selectOrder(orderNo: string) {
  if (selectedOrderNo.value === orderNo) {
    selectedOrderNo.value = null
    selectedTicketNo.value = null
    composerMode.value = 'default'
    ElMessage.info('已取消当前咨询订单')
    return
  }
  selectedOrderNo.value = orderNo
  selectedTicketNo.value = null
  composerMode.value = 'default'
  ElMessage.success(`已选择订单 ${orderNo}`)
}

function selectTicket(ticketNo: string) {
  selectedTicketNo.value = ticketNo
}

/** 手动刷新工作区：四个数据源并行刷新，失败提示由各加载函数内部处理。 */
async function refreshWorkspace() {
  if (loadingWorkspace.value) return
  loadingWorkspace.value = true
  try {
    await Promise.all([
      workspace.loadAgentStatus(),
      workspace.loadOrders(false),
      workspace.loadTickets(false),
      conversation.loadSessions(true)
    ])
    ElMessage.success('已刷新')
  } catch {
    // 各加载函数内部已统一处理错误提示。
  } finally {
    loadingWorkspace.value = false
  }
}

onMounted(async () => {
  const restored = workspace.restoreCustomerWorkspace()
  // 已缓存数据先渲染，接口在后台刷新；首次进入仍按原逻辑等待完整的初始数据。
  const initialRefresh = Promise.all([
    workspace.loadAgentStatus(),
    workspace.loadOrders(),
    workspace.loadTickets(),
    conversation.loadSessions(!restored)
  ])
  if (restored) {
    void initialRefresh.catch(() => undefined)
  } else {
    await initialRefresh
  }
  await applyRouteContext()
  document.addEventListener('visibilitychange', handleVisibilityChange)
  scheduleMessagePolling()
})

onActivated(() => {
  scheduleMessagePolling(0)
  if (!activatedOnce.value) {
    activatedOnce.value = true
    return
  }
  if (!workspace.orders.value.length && !workspace.tickets.value.length && !sessions.value.length) return
  // KeepAlive 恢复页面后静默校准最新业务数据，避免缓存内容出现骨架屏闪烁。
  void Promise.all([
    workspace.loadAgentStatus(),
    workspace.loadOrders(false),
    workspace.loadTickets(false),
    conversation.loadSessions(true)
  ]).catch(() => undefined)
  void applyRouteContext()
})

onDeactivated(stopMessagePolling)
onBeforeUnmount(() => {
  stopMessagePolling()
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})

watch(() => route.fullPath, () => {
  // 离开智能客服后清理本次入口标记，用户再次从同一按钮进入时仍会新建正确上下文。
  if (route.path !== '/customer/service') {
    resetHandledContext()
    return
  }
  void applyRouteContext()
})
</script>

<template>
  <div class="customer-service-page">
    <CustomerSidebar
      :selected-session-id="selectedSessionId"
      :sessions="sessions"
      :user="auth.user"
      @contact-service="createNewSession"
      @unavailable="() => ElMessage.info('该功能页面暂未开放')"
      @select-session="selectSession"
      @sessions-changed="handleSessionsChanged"
    />

    <main class="customer-main">
      <CustomerServiceHeader
        :agent-status="agentStatus"
        :loading-workspace="loadingWorkspace"
        :creating-session="creatingSession"
        @refresh="refreshWorkspace"
        @create="createNewSession"
        @open-history="historyVisible = true"
      />

      <div class="customer-content-grid chat-only-grid">
        <section class="center-workspace chat-only-workspace">
          <ChatAssistantPanel
            v-model="messageText"
            :last-reply="lastReply"
            :messages="messages"
            :session="selectedSession"
            :selected-order="selectedOrder"
            :selected-ticket="selectedTicket"
            :composer-hint="composerHint"
            :submitting="submitting || loadingMessages"
            @cancel-handoff="cancelHandoff"
            @quick="fillAndMaybeSend"
            @regenerate="regenerateAnswer"
            @submit="submitQuestion"
            @cancel="cancelCurrentGeneration"
            @upload="handleUploadAttachment"
            @download-attachment="handleDownloadAttachment"
          />
        </section>
      </div>
    </main>

    <CustomerHistoryDrawer
      v-model="historyVisible"
      :sessions="sessions"
      :selected-session-id="selectedSessionId"
      @select="selectHistorySession"
    />
  </div>
</template>
