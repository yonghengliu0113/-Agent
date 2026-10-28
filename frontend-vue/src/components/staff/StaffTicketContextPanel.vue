<script setup lang="ts">
import { computed } from 'vue'

import StaffAiEvidenceCard from '@/components/staff/StaffAiEvidenceCard.vue'
import StaffChangeRequestList from '@/components/staff/StaffChangeRequestList.vue'
import type { StaffTicketContext, Ticket, TicketChangeRequest } from '@/types/api'

/**
 * 工单上下文面板（右栏）。
 *
 * 只放"判断与处理"需要的信息：工单事实、履约变更审核、AI 判断依据、处理动作。
 * 客户对话在中间主区，避免信息和沟通混在一起。
 */
const props = defineProps<{
  ticket: Ticket | null
  aiContext: StaffTicketContext | null
  loadingAiContext: boolean
  changeRequests: TicketChangeRequest[]
  loadingChangeRequests: boolean
  decidingChangeRequestNo: string | null
  changeRequestMessages: Record<string, string>
  canOperate: boolean
  canClaim: boolean
  acting: boolean
  generatingDraft: boolean
  draftGenerationMode: 'llm' | 'fallback' | null
  draftFallbackReason: string | null
  activeTab: 'detail' | 'evidence'
}>()

const emit = defineEmits<{
  'tab-change': [value: 'detail' | 'evidence']
  'change-request-message': [payload: { requestNo: string; value: string }]
  claim: []
  start: []
  close: []
  'generate-draft': []
  decide: [request: TicketChangeRequest, decision: 'APPROVE' | 'REJECT' | 'NEED_MORE_INFO']
}>()

/** 工单状态到中文标签与色调的映射，避免模板里堆 if。 */
const STATUS_META: Record<string, { label: string; tone: string }> = {
  PENDING_ASSIGN: { label: '待分派', tone: 'warn' },
  ASSIGNED: { label: '已分派', tone: 'warn' },
  PROCESSING: { label: '处理中', tone: 'accent' },
  CLOSED: { label: '已关闭', tone: 'ok' },
  CANCELLED: { label: '已取消', tone: 'default' }
}

const statusMeta = computed(() => {
  const status = String(props.ticket?.status || '')
  return STATUS_META[status] || { label: status || '-', tone: 'default' }
})

/** 优先级只在高优先级时用强调色，避免满屏红黄。 */
const priorityTone = computed(() => {
  const priority = String(props.ticket?.priority || '').toLowerCase()
  if (priority === 'high' || priority === 'urgent') return 'danger'
  if (priority === 'low') return 'default'
  return 'warn'
})

const evidenceCount = computed(() => props.aiContext?.ai_evidence?.length ?? 0)
</script>

<template>
  <aside class="ws-context">
    <div class="ws-context__tabs">
      <button
        :class="['ws-context__tab', activeTab === 'detail' ? 'is-active' : '']"
        @click="emit('tab-change', 'detail')"
      >
        工单详情
      </button>
      <button
        :class="['ws-context__tab', activeTab === 'evidence' ? 'is-active' : '']"
        @click="emit('tab-change', 'evidence')"
      >
        AI 依据
        <span v-if="evidenceCount" class="ws-tag" style="margin-left: 4px">{{ evidenceCount }}</span>
      </button>
    </div>

    <div class="ws-context__scroll">
      <template v-if="!ticket">
        <div class="ws-empty" style="height: auto; padding: 24px 0">
          <p class="ws-empty__title">未选择工单</p>
          <p class="ws-empty__desc">从左侧队列选择一张工单查看详情。</p>
        </div>
      </template>

      <template v-else-if="activeTab === 'evidence'">
        <StaffAiEvidenceCard :context="aiContext" :loading="loadingAiContext" />
      </template>

      <template v-else>
        <!-- 工单事实：只用键值行，不用表格边框 -->
        <div class="ws-field">
          <span class="ws-field__k">工单号</span>
          <span class="ws-field__v">{{ ticket.ticketNo }}</span>
        </div>
        <div class="ws-field">
          <span class="ws-field__k">状态</span>
          <span class="ws-field__v">
            <span :class="['ws-tag', `ws-tag--${statusMeta.tone}`]">{{ statusMeta.label }}</span>
          </span>
        </div>
        <div class="ws-field">
          <span class="ws-field__k">优先级</span>
          <span class="ws-field__v">
            <span :class="['ws-tag', `ws-tag--${priorityTone}`]">{{ ticket.priority || '-' }}</span>
          </span>
        </div>
        <div class="ws-field">
          <span class="ws-field__k">处理组</span>
          <span class="ws-field__v">{{ ticket.assignedGroup || '-' }}</span>
        </div>
        <div class="ws-field">
          <span class="ws-field__k">处理人</span>
          <span class="ws-field__v">{{ ticket.handlerId ?? '待领取' }}</span>
        </div>
        <div class="ws-field">
          <span class="ws-field__k">关联订单</span>
          <span class="ws-field__v">{{ ticket.orderNo || '-' }}</span>
        </div>
        <div class="ws-field">
          <span class="ws-field__k">创建时间</span>
          <span class="ws-field__v">{{ ticket.createdAt || '-' }}</span>
        </div>

        <section class="ws-section">
          <div class="ws-section__head">
            <h3 class="ws-section__title">客户问题</h3>
          </div>
          <div class="ws-note">{{ ticket.content || '客户未填写问题描述。' }}</div>
        </section>

        <section class="ws-section">
          <div class="ws-section__head">
            <h3 class="ws-section__title">处理动作</h3>
          </div>
          <div style="display: flex; flex-wrap: wrap; gap: 8px">
            <button v-if="canClaim" class="ws-btn ws-btn--primary" :disabled="acting" @click="emit('claim')">
              领取工单
            </button>
            <button v-else-if="canOperate" class="ws-btn ws-btn--primary" :disabled="acting" @click="emit('start')">
              开始处理
            </button>
            <button class="ws-btn" :disabled="!canOperate || generatingDraft" @click="emit('generate-draft')">
              {{ generatingDraft ? '生成中…' : '生成回复草稿' }}
            </button>
            <button class="ws-btn" :disabled="!canOperate" @click="emit('close')">关闭工单</button>
          </div>
          <p v-if="draftGenerationMode === 'fallback'" class="ws-composer__tip" style="margin-top: 8px">
            当前为规则模板草稿{{ draftFallbackReason ? `（${draftFallbackReason}）` : '' }}
          </p>
          <p v-else-if="draftGenerationMode === 'llm'" class="ws-composer__tip" style="margin-top: 8px">
            已生成 AI 草稿并填入下方输入框，请确认后发送
          </p>
        </section>

        <section class="ws-section">
          <StaffChangeRequestList
            :requests="changeRequests"
            :loading="loadingChangeRequests"
            :can-operate="canOperate"
            :deciding-request-no="decidingChangeRequestNo"
            :messages="changeRequestMessages"
            @decide="(request, decision) => emit('decide', request, decision)"
            @update:message="(payload) => emit('change-request-message', payload)"
          />
        </section>
      </template>
    </div>
  </aside>
</template>
