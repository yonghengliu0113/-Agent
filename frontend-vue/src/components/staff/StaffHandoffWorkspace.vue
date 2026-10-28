<script setup lang="ts">
import type { ChatMessage, StaffHandoffDetail, StaffHandoffSession } from '@/types/api'

/**
 * 人工接管工作区。
 * 展示交接摘要、最近相关对话与接管操作（接入、回复、建跟进工单、结束接管），
 * 数据与权限均由父页面传入，组件只负责展示和事件上抛。
 */
defineProps<{
  session: StaffHandoffSession | null
  summary: StaffHandoffDetail['handoff_summary'] | null
  messages: ChatMessage[]
  canOperateHandoff: boolean
  historyAvailable: boolean
  historyAccessAllowed: boolean
  historyLoading: boolean
  acting: boolean
  reply: string
  closeMessage: string
}>()

const emit = defineEmits<{
  'update:reply': [value: string]
  'update:closeMessage': [value: string]
  accept: []
  'send-reply': []
  'create-ticket': []
  close: []
  'load-history': []
}>()
</script>

<template>
  <el-empty v-if="!session" description="请选择人工会话" />
  <section v-else class="staff-grid handoff-grid">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>人工会话</span>
          <el-tag :type="session.handoff_status === 'ACTIVE' ? 'success' : 'warning'">
            {{ session.handoff_status === 'ACTIVE' ? '人工接管中' : '等待接入' }}
          </el-tag>
        </div>
      </template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="会话编号">{{ session.session_id }}</el-descriptions-item>
        <el-descriptions-item label="交接原因">{{ summary?.handoff_reason || session.handoff_reason || '-' }}</el-descriptions-item>
        <el-descriptions-item label="请求时间">{{ session.human_requested_at || '-' }}</el-descriptions-item>
        <el-descriptions-item label="接入坐席">{{ session.human_assigned_staff_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="当前意图">{{ summary?.intent || session.intent || '-' }}</el-descriptions-item>
        <el-descriptions-item label="关联工单">{{ summary?.linked_ticket_no || session.linked_ticket_no || '-' }}</el-descriptions-item>
      </el-descriptions>

      <section class="handoff-summary-card">
        <div class="handoff-summary-header">
          <strong>交接摘要</strong>
          <el-tag size="small" type="info">最小必要信息</el-tag>
        </div>
        <p>{{ summary?.ai_summary || session.ai_summary || session.title || '暂无可展示的交接摘要。' }}</p>
      </section>

      <div class="handoff-history-toolbar">
        <span>默认仅展示最近相关对话</span>
        <el-button
          v-if="historyAvailable && historyAccessAllowed"
          :loading="historyLoading"
          link
          type="primary"
          @click="emit('load-history')"
        >
          展开更早历史
        </el-button>
        <span v-else-if="session.handoff_status === 'PENDING'" class="handoff-history-hint">
          接入会话后可查看最近相关对话
        </span>
      </div>

      <el-empty
        v-if="!messages.length"
        :description="session.handoff_status === 'PENDING' ? '请先接入会话，系统将提供最近相关对话。' : '暂无可展示的会话消息。'"
        :image-size="72"
      />
      <div class="handoff-messages">
        <div
          v-for="message in messages"
          :key="message.id"
          :class="['handoff-message', message.sender_type]"
        >
          <small>{{ message.sender_type }} · {{ message.created_at }}</small>
          <p>{{ message.content }}</p>
        </div>
      </div>
    </el-card>

    <el-card shadow="never">
      <template #header>人工接管操作</template>
      <el-alert
        v-if="session.handoff_status === 'PENDING'"
        title="该客户正在等待人工接入，接入后智能助手会暂停自动回复。"
        :closable="false"
        type="warning"
        show-icon
      />
      <el-alert
        v-else-if="!canOperateHandoff"
        title="该会话已由其他坐席接入，当前账号不能回复。"
        :closable="false"
        type="info"
        show-icon
      />
      <div class="action-row section-gap">
        <el-button
          v-if="session.handoff_status === 'PENDING'"
          :loading="acting"
          type="primary"
          @click="emit('accept')"
        >
          接入会话
        </el-button>
      </div>
      <el-form label-position="top">
        <el-form-item label="人工回复">
          <el-input
            :model-value="reply"
            :disabled="!canOperateHandoff"
            :rows="8"
            placeholder="请输入要直接发送给客户的人工回复。"
            type="textarea"
            @update:model-value="emit('update:reply', String($event))"
          />
        </el-form-item>
        <el-button :disabled="!canOperateHandoff" :loading="acting" type="primary" @click="emit('send-reply')">
          发送给客户
        </el-button>
        <el-button :disabled="!canOperateHandoff" :loading="acting" @click="emit('create-ticket')">
          创建跟进工单
        </el-button>

        <el-divider />
        <el-form-item label="结束说明">
          <el-input
            :model-value="closeMessage"
            :disabled="!canOperateHandoff"
            :rows="3"
            type="textarea"
            @update:model-value="emit('update:closeMessage', String($event))"
          />
        </el-form-item>
        <el-button :disabled="!canOperateHandoff" :loading="acting" @click="emit('close')">
          结束人工接管
        </el-button>
        <el-alert
          :closable="false"
          type="info"
          title="“结束人工接管”只结束当前会话，不会关闭关联的业务工单；完结工单请到“工单”页签按“领取工单 → 开始处理 → 关闭工单”操作。"
        />
      </el-form>
    </el-card>
  </section>
</template>
