<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { staffHandoffApi } from '@/api/staff'
import StaffHandoffWorkspace from '@/components/staff/StaffHandoffWorkspace.vue'
import StaffQueueAside from '@/components/staff/StaffQueueAside.vue'
import StaffTicketWorkspace from '@/components/staff/StaffTicketWorkspace.vue'
import { useStaffChangeRequests } from '@/composables/useStaffChangeRequests'
import { useStaffHandoff } from '@/composables/useStaffHandoff'
import { useStaffPolling } from '@/composables/useStaffPolling'
import { useStaffTicketActions } from '@/composables/useStaffTicketActions'
import { useStaffTicketQueue } from '@/composables/useStaffTicketQueue'
import { useAuthStore } from '@/stores/auth'
import type { Ticket } from '@/types/api'

/**
 * 坐席工作台容器。
 * 负责组合左侧队列、工单工作区与人工接管工作区，并串联队列/工单/会话三类数据源。
 * 列表、写操作、轮询与本地已读游标分别下沉到 composable，展示区块下沉到
 * src/components/staff，本文件只保留页面级状态与生命周期。
 */
const router = useRouter()
const auth = useAuthStore()
const workMode = ref<'tickets' | 'handoff'>('tickets')
const acting = ref(false)

const queue = useStaffTicketQueue()
const changeRequests = useStaffChangeRequests({
  selectedTicketNo: queue.selectedTicketNo,
  selectedTicket: queue.selectedTicket,
  canOperate: queue.canOperate,
  loadTickets: queue.loadTickets
})
const ticketActions = useStaffTicketActions({
  selectedTicket: queue.selectedTicket,
  selectedTicketNo: queue.selectedTicketNo,
  queueScope: queue.queueScope,
  acting,
  loadTickets: queue.loadTickets,
  loadChangeRequests: changeRequests.loadChangeRequests
})
const handoff = useStaffHandoff({ acting })
const polling = useStaffPolling({
  loadHandoffSessions: handoff.loadHandoffSessions,
  pollHandoffDetail: handoff.pollHandoffDetail
})

const { selectedTicketNo, queueScope, selectedStatuses, statusOptions, loading, selectedTicket, visibleTickets, canClaim, canOperate, loadTickets } = queue
const {
  ticketChangeRequests,
  loadingChangeRequests,
  decidingChangeRequestNo,
  changeRequestMessages,
  loadChangeRequests,
  decideChangeRequest
} = changeRequests
const {
  closeReason,
  draftMessage,
  draftGenerationMode,
  draftFallbackReason,
  generatingDraft,
  ticketAiContext,
  loadingTicketAiContext,
  resetDraft,
  loadTicketAiContext,
  claimTicket,
  startTicket,
  closeTicket,
  generateDraft,
  sendReply
} = ticketActions
const {
  handoffSessions,
  handoffMessages,
  handoffSummary,
  handoffHistoryAvailable,
  handoffHistoryAccessAllowed,
  handoffHistoryLoading,
  selectedHandoffSessionId,
  handoffLoading,
  handoffReply,
  handoffCloseMessage,
  handoffScope,
  seenHandoffMessageIds,
  selectedHandoff,
  visibleHandoffs,
  canOperateHandoff,
  loadHandoffSessions,
  loadEarlierHandoffHistory,
  selectHandoff,
  acceptHandoff,
  sendHandoffReply,
  closeHandoff,
  createHandoffTicket
} = handoff
const { startStaffPolling, stopStaffPolling, handleStaffVisibility } = polling

/** 选择工单：清空上一张工单草稿，并并行加载改约申请与 AI 决策依据。 */
function selectTicket(ticket: Ticket) {
  selectedTicketNo.value = ticket.ticketNo
  resetDraft()
  void loadChangeRequests(ticket.ticketNo)
  void loadTicketAiContext(ticket.ticketNo)
}

/** 改约申请的客户可见说明按申请号保存，提交时随审核动作一起发送。 */
function handleChangeRequestMessage(payload: { requestNo: string; value: string }) {
  changeRequestMessages.value = { ...changeRequestMessages.value, [payload.requestNo]: payload.value }
}

/** 退出登录：先停止轮询并通知在线状态下线，再清理本地登录态。 */
async function logout() {
  stopStaffPolling()
  await staffHandoffApi.leave().catch(() => undefined)
  auth.logout()
  await router.push('/staff/login')
}

onMounted(async () => {
  await staffHandoffApi.heartbeat().catch(() => undefined)
  await Promise.all([loadTickets(), loadHandoffSessions()])
  document.addEventListener('visibilitychange', handleStaffVisibility)
  startStaffPolling()
})

onBeforeUnmount(() => {
  stopStaffPolling()
  document.removeEventListener('visibilitychange', handleStaffVisibility)
  void staffHandoffApi.leave().catch(() => undefined)
})
</script>

<template>
  <el-container class="app-shell">
    <StaffQueueAside
      v-model:work-mode="workMode"
      v-model:queue-scope="queueScope"
      v-model:selected-statuses="selectedStatuses"
      v-model:handoff-scope="handoffScope"
      :handoff-count="handoffSessions.length"
      :display-name="auth.user?.display_name"
      :status-options="statusOptions"
      :loading="loading"
      :visible-tickets="visibleTickets"
      :selected-ticket-no="selectedTicketNo"
      :handoff-loading="handoffLoading"
      :visible-handoffs="visibleHandoffs"
      :selected-handoff-session-id="selectedHandoffSessionId"
      :seen-handoff-message-ids="seenHandoffMessageIds"
      @select-ticket="selectTicket"
      @select-handoff="selectHandoff"
      @refresh-tickets="loadTickets"
      @refresh-handoffs="loadHandoffSessions(false)"
      @logout="logout"
      @open-rag="router.push('/staff/rag-evaluation')"
      @open-monitor="router.push('/staff/system-monitor')"
    />

    <el-main class="main-panel">
      <header class="page-header">
        <div>
          <h1>客服坐席工作台</h1>
          <p>处理自己名下工单，填写处理结果，并确认客户可见回复</p>
        </div>
      </header>

      <StaffHandoffWorkspace
        v-if="workMode === 'handoff'"
        v-model:reply="handoffReply"
        v-model:close-message="handoffCloseMessage"
        :session="selectedHandoff"
        :summary="handoffSummary"
        :messages="handoffMessages"
        :can-operate-handoff="canOperateHandoff"
        :history-available="handoffHistoryAvailable"
        :history-access-allowed="handoffHistoryAccessAllowed"
        :history-loading="handoffHistoryLoading"
        :acting="acting"
        @accept="acceptHandoff"
        @send-reply="sendHandoffReply"
        @create-ticket="createHandoffTicket"
        @close="closeHandoff"
        @load-history="loadEarlierHandoffHistory"
      />

      <StaffTicketWorkspace
        v-else
        v-model:close-reason="closeReason"
        v-model:draft-message="draftMessage"
        :selected-ticket="selectedTicket"
        :ticket-change-requests="ticketChangeRequests"
        :loading-change-requests="loadingChangeRequests"
        :deciding-change-request-no="decidingChangeRequestNo"
        :change-request-messages="changeRequestMessages"
        :can-operate="canOperate"
        :can-claim="canClaim"
        :acting="acting"
        :draft-generation-mode="draftGenerationMode"
        :draft-fallback-reason="draftFallbackReason"
        :generating-draft="generatingDraft"
        :ticket-ai-context="ticketAiContext"
        :loading-ticket-ai-context="loadingTicketAiContext"
        @update:change-request-message="handleChangeRequestMessage"
        @claim="claimTicket"
        @start="startTicket"
        @close="closeTicket"
        @generate-draft="generateDraft"
        @send-reply="sendReply"
        @decide-change-request="decideChangeRequest"
      />
    </el-main>
  </el-container>
</template>
