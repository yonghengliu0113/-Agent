<script setup lang="ts">
import { ArrowDown, ArrowUp } from '@element-plus/icons-vue'
import { ref, watch } from 'vue'

import type { ChatSession, CustomerOrder } from '@/types/api'

/**
 * 人工接管状态卡：展示当前是否排队/已接入，并提供取消排队与详情展开/收起。
 * 客户可收起大面积上下文，避免遮挡会话内容。
 */
const props = defineProps<{
  session: ChatSession | null
  statusText: string
  statusType: 'success' | 'info' | 'warning'
  sessionTicketNo: string
  selectedOrder: CustomerOrder | null
}>()

const emit = defineEmits<{
  'cancel-handoff': []
}>()

// 人工接入信息默认展开；切换会话后恢复展开，避免把上一会话的偏好带入当前记录。
const handoffDetailsCollapsed = ref(false)

watch(
  () => props.session?.session_id || '',
  (current, previous) => {
    if (!previous || current !== previous) {
      handoffDetailsCollapsed.value = false
    }
  },
  { immediate: true }
)
</script>

<template>
  <!-- 组件常驻以保留展开/收起偏好，仅在没有人工状态时隐藏卡片本体。 -->
  <div v-if="statusText" :class="['human-status-card', { 'is-collapsed': handoffDetailsCollapsed }]">
    <div class="human-status-main">
      <div class="human-status-title">
        <span>当前状态</span>
        <strong>{{ statusText }}</strong>
      </div>
      <div class="human-status-actions">
        <el-button v-if="session?.handoff_status === 'PENDING'" size="small" @click="emit('cancel-handoff')">取消排队</el-button>
        <el-tag :type="statusType">{{ session?.handoff_status }}</el-tag>
        <el-button
          class="handoff-collapse-button"
          text
          size="small"
          :icon="handoffDetailsCollapsed ? ArrowDown : ArrowUp"
          :aria-expanded="String(!handoffDetailsCollapsed)"
          @click="handoffDetailsCollapsed = !handoffDetailsCollapsed"
        >
          {{ handoffDetailsCollapsed ? '展开详情' : '收起详情' }}
        </el-button>
      </div>
    </div>
    <p v-if="handoffDetailsCollapsed" class="handoff-collapsed-summary">
      {{ sessionTicketNo ? `已关联工单 ${sessionTicketNo}` : '人工客服正在查看当前会话' }}，您可在下方继续补充信息。
    </p>
    <el-collapse-transition>
      <div v-show="!handoffDetailsCollapsed" class="handoff-detail-content">
        <dl>
          <div>
            <dt>请求时间</dt>
            <dd>{{ session?.human_requested_at || '-' }}</dd>
          </div>
          <div>
            <dt>最近更新</dt>
            <dd>{{ session?.updated_at || '-' }}</dd>
          </div>
          <div>
            <dt>关联工单</dt>
            <dd>{{ sessionTicketNo || '-' }}</dd>
          </div>
          <div>
            <dt>预计等待</dt>
            <dd>{{ session?.handoff_status === 'PENDING' ? '排队中' : '-' }}</dd>
          </div>
        </dl>
        <div class="handoff-summary-card">
          <strong>上下文摘要</strong>
          <p>当前订单：{{ selectedOrder?.orderNo || '未选择订单' }}</p>
          <p>当前工单：{{ sessionTicketNo || '暂无关联工单' }}</p>
          <p>{{ session?.ai_summary || '人工客服可查看当前会话上下文，您也可以在下方继续补充关键信息。' }}</p>
        </div>
      </div>
    </el-collapse-transition>
  </div>
</template>
