<script setup lang="ts">
import StaffAiEvidenceCard from '@/components/staff/StaffAiEvidenceCard.vue'
import StaffTicketActionCard from '@/components/staff/StaffTicketActionCard.vue'
import StaffTicketDetailCard from '@/components/staff/StaffTicketDetailCard.vue'
import type { StaffTicketContext, Ticket, TicketChangeRequest } from '@/types/api'

/**
 * 工单模式工作区。
 * 组合工单详情、AI 决策依据与处理操作三张卡片，
 * 并把子卡片的动作统一上抛给 StaffHome 容器。
 */
defineProps<{
  selectedTicket: Ticket | null
  ticketChangeRequests: TicketChangeRequest[]
  loadingChangeRequests: boolean
  decidingChangeRequestNo: string | null
  changeRequestMessages: Record<string, string>
  canOperate: boolean
  canClaim: boolean
  acting: boolean
  closeReason: string
  draftMessage: string
  draftGenerationMode: 'llm' | 'fallback' | null
  draftFallbackReason: string | null
  generatingDraft: boolean
  ticketAiContext: StaffTicketContext | null
  loadingTicketAiContext: boolean
}>()

const emit = defineEmits<{
  'update:closeReason': [value: string]
  'update:draftMessage': [value: string]
  'update:changeRequestMessage': [payload: { requestNo: string; value: string }]
  claim: []
  start: []
  close: []
  'generate-draft': []
  'send-reply': []
  'decide-change-request': [request: TicketChangeRequest, decision: 'APPROVE' | 'REJECT' | 'NEED_MORE_INFO']
}>()

function handleDecide(request: TicketChangeRequest, decision: 'APPROVE' | 'REJECT' | 'NEED_MORE_INFO') {
  emit('decide-change-request', request, decision)
}

function handleChangeRequestMessage(payload: { requestNo: string; value: string }) {
  emit('update:changeRequestMessage', payload)
}
</script>

<template>
  <el-empty v-if="!selectedTicket" description="请选择工单" />
  <section v-else class="staff-grid">
    <StaffTicketDetailCard
      v-if="selectedTicket"
      :ticket="selectedTicket"
      :change-requests="ticketChangeRequests"
      :loading-change-requests="loadingChangeRequests"
      :deciding-change-request-no="decidingChangeRequestNo"
      :change-request-messages="changeRequestMessages"
      :can-operate="canOperate"
      @decide="handleDecide"
      @update:change-request-message="handleChangeRequestMessage"
    />

    <StaffAiEvidenceCard :context="ticketAiContext" :loading="loadingTicketAiContext" />

    <StaffTicketActionCard
      :can-operate="canOperate"
      :can-claim="canClaim"
      :acting="acting"
      :close-reason="closeReason"
      :draft-message="draftMessage"
      :draft-generation-mode="draftGenerationMode"
      :draft-fallback-reason="draftFallbackReason"
      :generating-draft="generatingDraft"
      @update:close-reason="(value) => emit('update:closeReason', value)"
      @update:draft-message="(value) => emit('update:draftMessage', value)"
      @claim="emit('claim')"
      @start="emit('start')"
      @close="emit('close')"
      @generate-draft="emit('generate-draft')"
      @send-reply="emit('send-reply')"
    />
  </section>
</template>
