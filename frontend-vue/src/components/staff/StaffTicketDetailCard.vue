<script setup lang="ts">
import StaffChangeRequestList from '@/components/staff/StaffChangeRequestList.vue'
import type { Ticket, TicketChangeRequest } from '@/types/api'
import { statusType } from '@/utils/ticket'

/**
 * 工单详情卡：工单基础信息、催办提示、客户问题、AI 摘要与履约变更申请。
 * 变更申请区域由 StaffChangeRequestList 独立承载。
 */
defineProps<{
  ticket: Ticket
  changeRequests: TicketChangeRequest[]
  loadingChangeRequests: boolean
  decidingChangeRequestNo: string | null
  changeRequestMessages: Record<string, string>
  canOperate: boolean
}>()

const emit = defineEmits<{
  decide: [request: TicketChangeRequest, decision: 'APPROVE' | 'REJECT' | 'NEED_MORE_INFO']
  'update:changeRequestMessage': [payload: { requestNo: string; value: string }]
}>()
</script>

<template>
  <el-card shadow="never">
    <template #header>工单详情</template>
    <el-descriptions :column="2" border>
      <el-descriptions-item label="工单号">{{ ticket.ticketNo }}</el-descriptions-item>
      <el-descriptions-item label="状态">
        <el-tag :type="statusType(ticket.status)">{{ ticket.status }}</el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="优先级">{{ ticket.priority || '-' }}</el-descriptions-item>
      <el-descriptions-item label="处理组">{{ ticket.assignedGroup || '-' }}</el-descriptions-item>
      <el-descriptions-item label="处理人">{{ ticket.handlerId || '-' }}</el-descriptions-item>
      <el-descriptions-item label="派单方式">{{ ticket.assignedBy || '-' }}</el-descriptions-item>
      <el-descriptions-item label="关联订单">{{ ticket.orderNo || '-' }}</el-descriptions-item>
      <el-descriptions-item label="SLA">{{ ticket.slaDeadline || '-' }}</el-descriptions-item>
      <el-descriptions-item label="催办次数">{{ ticket.urgeCount || 0 }}</el-descriptions-item>
      <el-descriptions-item label="最近催办">{{ ticket.lastUrgedAt || '-' }}</el-descriptions-item>
    </el-descriptions>

    <el-alert
      v-if="ticket.lastUrgeReason"
      :title="`客户催办：${ticket.lastUrgeReason}`"
      :closable="false"
      class="section-gap"
      type="warning"
      show-icon
    />

    <h3>客户问题</h3>
    <el-alert :title="ticket.content || ticket.title" :closable="false" type="info" />

    <h3>AI 摘要</h3>
    <p class="plain-text">{{ ticket.aiSummary || '暂无 AI 摘要' }}</p>

    <StaffChangeRequestList
      :requests="changeRequests"
      :loading="loadingChangeRequests"
      :can-operate="canOperate"
      :deciding-request-no="decidingChangeRequestNo"
      :messages="changeRequestMessages"
      @decide="(request, decision) => emit('decide', request, decision)"
      @update:message="(payload) => emit('update:changeRequestMessage', payload)"
    />
  </el-card>
</template>
