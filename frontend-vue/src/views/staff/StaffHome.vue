<script setup lang="ts">
import { ArrowLeft, ArrowRight, ChatLineRound, Histogram, Setting, SwitchButton } from '@element-plus/icons-vue'

import StaffConversationPane from '@/components/staff/StaffConversationPane.vue'
import StaffHandoffContextPanel from '@/components/staff/StaffHandoffContextPanel.vue'
import StaffQueueAside from '@/components/staff/StaffQueueAside.vue'
import StaffTicketContextPanel from '@/components/staff/StaffTicketContextPanel.vue'
import { useStaffWorkspace } from '@/composables/useStaffWorkspace'

/**
 * 坐席工作台外壳。
 *
 * 布局：顶栏 + 左侧队列 + 中间对话 + 右侧上下文。
 * 页面级状态与数据编排见 useStaffWorkspace，本文件只负责模板与事件绑定。
 */
const {
  auth,
  router,
  workMode,
  acting,
  sending,
  queueCollapsed,
  contextCollapsed,
  contextTab,
  isTicketMode,
  switchMode,
  queue,
  selectTicket,
  refreshQueue,
  conversationMessages,
  conversationTitle,
  conversationSubtitle,
  conversationTags,
  canReply,
  replyHint,
  composerDraft,
  ticketMessages,
  handoff,
  sendMessage,
  ticketActions,
  changeRequests,
  handleChangeRequestMessage,
  logout
} = useStaffWorkspace()

// 模板直接使用的字段解构出来，保持模板可读性（均为 composable 暴露的 ref）
const { visibleTickets, selectedTicketNo, queueScope, selectedStatuses, statusOptions, loading, selectedTicket, canClaim, canOperate } = queue
const {
  handoffSessions,
  handoffLoading,
  visibleHandoffs,
  selectedHandoffSessionId,
  seenHandoffMessageIds,
  selectedHandoff,
  handoffSummary,
  canOperateHandoff,
  handoffCloseMessage,
  handoffHistoryAvailable,
  handoffHistoryAccessAllowed,
  handoffHistoryLoading,
  selectHandoff,
  acceptHandoff,
  createHandoffTicket,
  closeHandoff,
  loadEarlierHandoffHistory
} = handoff
const { generatingDraft, draftGenerationMode, draftFallbackReason, claimTicket, startTicket, closeTicket, generateDraft, ticketAiContext, loadingTicketAiContext } = ticketActions
const { ticketChangeRequests, loadingChangeRequests, decidingChangeRequestNo, changeRequestMessages, decideChangeRequest } = changeRequests
</script>


<template>
  <div class="ws-app">
    <header class="ws-topbar">
      <div class="ws-topbar__brand">
        <span class="ws-topbar__mark">
          <el-icon><ChatLineRound /></el-icon>
        </span>
        客服工作台
      </div>

      <div class="ws-segment">
        <button
          :class="['ws-segment__btn', workMode === 'tickets' ? 'is-active' : '']"
          @click="switchMode('tickets')"
        >
          工单
          <span class="ws-segment__count">{{ visibleTickets.length }}</span>
        </button>
        <button
          :class="['ws-segment__btn', workMode === 'handoff' ? 'is-active' : '']"
          @click="switchMode('handoff')"
        >
          人工会话
          <span class="ws-segment__count">{{ handoffSessions.length }}</span>
        </button>
      </div>

      <button
        class="ws-iconbtn"
        :class="queueCollapsed ? '' : 'is-active'"
        title="展开或收起队列"
        aria-label="展开或收起队列"
        @click="queueCollapsed = !queueCollapsed"
      >
        <el-icon><ArrowLeft /></el-icon>
      </button>
      <button
        class="ws-iconbtn"
        :class="contextCollapsed ? '' : 'is-active'"
        title="展开或收起详情栏"
        aria-label="展开或收起详情栏"
        @click="contextCollapsed = !contextCollapsed"
      >
        <el-icon><ArrowRight /></el-icon>
      </button>

      <span class="ws-topbar__spacer" />

      <span class="ws-presence">
        <span class="ws-presence__dot" />
        在线
      </span>

      <button class="ws-iconbtn" title="RAG 评测" aria-label="RAG 评测" @click="router.push('/staff/rag-evaluation')">
        <el-icon><Histogram /></el-icon>
      </button>
      <button class="ws-iconbtn" title="系统监控" aria-label="系统监控" @click="router.push('/staff/system-monitor')">
        <el-icon><Setting /></el-icon>
      </button>

      <el-dropdown trigger="click">
        <button class="ws-btn ws-btn--ghost ws-btn--sm">
          {{ auth.user?.display_name || '坐席' }}
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item disabled>{{ auth.user?.display_name }} · 客服坐席</el-dropdown-item>
            <el-dropdown-item divided @click="logout">
              <el-icon><SwitchButton /></el-icon>
              退出登录
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </header>

    <div class="ws-body">
      <StaffQueueAside
        v-show="!queueCollapsed"
        :mode="workMode"
        :queue-scope="queueScope"
        :selected-statuses="selectedStatuses"
        :status-options="statusOptions"
        :loading="loading"
        :visible-tickets="visibleTickets"
        :selected-ticket-no="selectedTicketNo"
        :handoff-loading="handoffLoading"
        :visible-handoffs="visibleHandoffs"
        :selected-handoff-session-id="selectedHandoffSessionId"
        :seen-handoff-message-ids="seenHandoffMessageIds"
        @update:queue-scope="queueScope = $event"
        @update:selected-statuses="selectedStatuses = $event"
        @select-ticket="selectTicket"
        @select-handoff="selectHandoff"
        @refresh="refreshQueue"
      />

      <StaffConversationPane
        :title="conversationTitle"
        :subtitle="conversationSubtitle"
        :tags="conversationTags"
        :messages="conversationMessages"
        :loading="isTicketMode ? ticketMessages.loading.value : handoffLoading"
        :sending="sending"
        :can-reply="canReply"
        :reply-hint="replyHint"
        :draft="composerDraft"
        :empty-title="isTicketMode ? '该工单暂无客户对话' : '暂无对话内容'"
        :empty-desc="
          isTicketMode
            ? '客户在本次会话中的消息会显示在这里，可直接在下方回复。'
            : '接入会话后即可看到客户消息并回复。'
        "
        @update:draft="composerDraft = $event"
        @send="sendMessage"
      >
        <template #actions>
          <button
            v-if="!isTicketMode && selectedHandoff?.handoff_status === 'PENDING'"
            class="ws-btn ws-btn--primary"
            :disabled="acting"
            @click="acceptHandoff"
          >
            接入会话
          </button>
          <button v-if="isTicketMode && canClaim" class="ws-btn ws-btn--primary" :disabled="acting" @click="claimTicket">
            领取工单
          </button>
        </template>
      </StaffConversationPane>

      <StaffTicketContextPanel
        v-if="isTicketMode && !contextCollapsed"
        :active-tab="contextTab"
        :ticket="selectedTicket"
        :ai-context="ticketAiContext"
        :loading-ai-context="loadingTicketAiContext"
        :change-requests="ticketChangeRequests"
        :loading-change-requests="loadingChangeRequests"
        :deciding-change-request-no="decidingChangeRequestNo"
        :change-request-messages="changeRequestMessages"
        :can-operate="canOperate"
        :can-claim="canClaim"
        :acting="acting"
        :generating-draft="generatingDraft"
        :draft-generation-mode="draftGenerationMode"
        :draft-fallback-reason="draftFallbackReason"
        @tab-change="contextTab = $event"
        @change-request-message="handleChangeRequestMessage"
        @claim="claimTicket"
        @start="startTicket"
        @close="closeTicket"
        @generate-draft="generateDraft"
        @decide="decideChangeRequest"
      />

      <StaffHandoffContextPanel
        v-else-if="!isTicketMode && !contextCollapsed"
        :session="selectedHandoff"
        :summary="handoffSummary"
        :can-operate-handoff="canOperateHandoff"
        :acting="acting"
        :close-message="handoffCloseMessage"
        :history-available="handoffHistoryAvailable"
        :history-access-allowed="handoffHistoryAccessAllowed"
        :history-loading="handoffHistoryLoading"
        @close-message-change="handoffCloseMessage = $event"
        @accept="acceptHandoff"
        @create-ticket="createHandoffTicket"
        @close="closeHandoff"
        @load-history="loadEarlierHandoffHistory"
      />
    </div>
  </div>
</template>
