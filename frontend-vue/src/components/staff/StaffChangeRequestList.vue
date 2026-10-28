<script setup lang="ts">
import type { TicketChangeRequest } from '@/types/api'
import { changeRequestStatusLabel } from '@/utils/ticket'

/**
 * 坐席履约变更申请列表。
 * 只展示已关联原工单的改约请求，并把审核动作与客户可见说明交给父页面。
 */
defineProps<{
  requests: TicketChangeRequest[]
  loading: boolean
  canOperate: boolean
  decidingRequestNo: string | null
  messages: Record<string, string>
}>()

const emit = defineEmits<{
  decide: [request: TicketChangeRequest, decision: 'APPROVE' | 'REJECT' | 'NEED_MORE_INFO']
  'update:message': [payload: { requestNo: string; value: string }]
}>()
</script>

<template>
  <section v-loading="loading" class="staff-change-requests">
    <div class="staff-change-requests__title">
      <h3>履约变更申请</h3>
      <span>仅审核已关联原工单的改约请求</span>
    </div>
    <el-empty v-if="canOperate && !requests.length && !loading" :image-size="44" description="暂无待审核的履约变更申请" />
    <article v-for="request in requests" :key="request.requestNo" class="staff-change-request">
      <header>
        <div><b>{{ request.requestNo }}</b><span>{{ request.changeType === 'RETURN_METHOD_CHANGE' ? '退回方式调整' : '取件时间调整' }}</span></div>
        <el-tag size="small" :type="request.status === 'APPROVED' ? 'success' : request.status === 'REJECTED' ? 'danger' : 'warning'">{{ changeRequestStatusLabel(request.status) }}</el-tag>
      </header>
      <p>原偏好：{{ request.previousReturnMethod || '未登记' }}{{ request.previousPickupTimeWindow ? ` / ${request.previousPickupTimeWindow}` : '' }}</p>
      <p>申请调整为：{{ request.requestedReturnMethod || request.previousReturnMethod || '未变更' }}{{ request.requestedPickupTimeWindow ? ` / ${request.requestedPickupTimeWindow}` : '' }}</p>
      <p v-if="request.customerMessage" class="staff-change-request__message">客户可见说明：{{ request.customerMessage }}</p>
      <template v-if="request.status === 'PENDING_REVIEW'">
        <el-input
          :model-value="messages[request.requestNo]"
          :disabled="!canOperate"
          :rows="2"
          maxlength="500"
          placeholder="填写客户可见说明（可选，不要包含内部信息）"
          type="textarea"
          @update:model-value="emit('update:message', { requestNo: request.requestNo, value: String($event) })"
        />
        <div class="action-row staff-change-request__actions">
          <el-button :disabled="!canOperate" :loading="decidingRequestNo === request.requestNo" type="success" @click="emit('decide', request, 'APPROVE')">同意调整</el-button>
          <el-button :disabled="!canOperate" :loading="decidingRequestNo === request.requestNo" @click="emit('decide', request, 'NEED_MORE_INFO')">请客户补充</el-button>
          <el-button :disabled="!canOperate" :loading="decidingRequestNo === request.requestNo" type="danger" plain @click="emit('decide', request, 'REJECT')">暂不支持</el-button>
        </div>
      </template>
    </article>
  </section>
</template>
