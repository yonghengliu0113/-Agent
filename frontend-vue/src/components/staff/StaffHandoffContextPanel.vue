<script setup lang="ts">
import { computed, ref } from 'vue'

import type { StaffHandoffDetail, StaffHandoffSession } from '@/types/api'

/**
 * 人工接管上下文面板（右栏）。
 *
 * 承载接管类事实与动作：等待状态、交接原因、AI 摘要、接入/建单/结束接管。
 * 客户对话在中间主区，这里不重复渲染消息列表。
 */
const props = defineProps<{
  session: StaffHandoffSession | null
  summary: StaffHandoffDetail['handoff_summary'] | null
  canOperateHandoff: boolean
  acting: boolean
  closeMessage: string
  historyAvailable: boolean
  historyAccessAllowed: boolean
  historyLoading: boolean
}>()

const emit = defineEmits<{
  'close-message-change': [value: string]
  accept: []
  'create-ticket': []
  close: []
  'load-history': []
}>()

/** 结束接管需要填写说明，默认收起，避免长期占位挤压信息区。 */
const closing = ref(false)

const statusMeta = computed(() => {
  const status = String(props.session?.handoff_status || '')
  if (status === 'ACTIVE') return { label: '人工接管中', tone: 'ok' }
  if (status === 'PENDING') return { label: '等待接入', tone: 'warn' }
  if (status === 'CLOSED') return { label: '已结束', tone: 'default' }
  return { label: status || '-', tone: 'default' }
})

/** 把等待秒数转成便于扫读的时长。 */
const waitingText = computed(() => {
  const seconds = props.session?.waiting_seconds
  if (typeof seconds !== 'number' || seconds <= 0) return null
  if (seconds < 60) return `已等待 ${seconds} 秒`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `已等待 ${minutes} 分钟`
  return `已等待 ${Math.round(minutes / 60)} 小时`
})

const summaryText = computed(
  () => props.summary?.ai_summary || props.session?.ai_summary || props.session?.title || ''
)
</script>

<template>
  <aside class="ws-context">
    <div class="ws-context__tabs">
      <button class="ws-context__tab is-active">会话详情</button>
    </div>

    <div class="ws-context__scroll">
      <template v-if="!session">
        <div class="ws-empty" style="height: auto; padding: 24px 0">
          <p class="ws-empty__title">未选择会话</p>
          <p class="ws-empty__desc">从左侧队列选择一条待接入的人工会话。</p>
        </div>
      </template>

      <template v-else>
        <div class="ws-field">
          <span class="ws-field__k">状态</span>
          <span class="ws-field__v">
            <span :class="['ws-tag', `ws-tag--${statusMeta.tone}`]">{{ statusMeta.label }}</span>
            <span v-if="waitingText" class="ws-composer__tip" style="margin-left: 6px">{{ waitingText }}</span>
          </span>
        </div>
        <div class="ws-field">
          <span class="ws-field__k">会话编号</span>
          <span class="ws-field__v">{{ session.session_id }}</span>
        </div>
        <div class="ws-field">
          <span class="ws-field__k">转人工原因</span>
          <span class="ws-field__v">{{ summary?.handoff_reason || session.handoff_reason || '-' }}</span>
        </div>
        <div class="ws-field">
          <span class="ws-field__k">请求时间</span>
          <span class="ws-field__v">{{ session.human_requested_at || '-' }}</span>
        </div>
        <div class="ws-field">
          <span class="ws-field__k">接入坐席</span>
          <span class="ws-field__v">{{ session.human_assigned_staff_name || '未接入' }}</span>
        </div>
        <div class="ws-field">
          <span class="ws-field__k">关联工单</span>
          <span class="ws-field__v">{{ summary?.linked_ticket_no || session.linked_ticket_no || '无' }}</span>
        </div>
        <div class="ws-field">
          <span class="ws-field__k">当前意图</span>
          <span class="ws-field__v">{{ summary?.intent || session.intent || '-' }}</span>
        </div>

        <section v-if="summaryText" class="ws-section">
          <div class="ws-section__head">
            <h3 class="ws-section__title">AI 交接摘要</h3>
          </div>
          <div class="ws-note">{{ summaryText }}</div>
        </section>

        <section class="ws-section">
          <div class="ws-section__head">
            <h3 class="ws-section__title">接管操作</h3>
          </div>

          <div style="display: flex; flex-wrap: wrap; gap: 8px">
            <button
              v-if="session.handoff_status === 'PENDING'"
              class="ws-btn ws-btn--primary"
              :disabled="acting"
              @click="emit('accept')"
            >
              接入会话
            </button>
            <button class="ws-btn" :disabled="!canOperateHandoff || acting" @click="emit('create-ticket')">
              创建跟进工单
            </button>
            <button class="ws-btn" :disabled="!canOperateHandoff" @click="closing = !closing">
              {{ closing ? '取消结束' : '结束接管' }}
            </button>
          </div>

          <div v-if="closing" style="margin-top: 10px">
            <textarea
              :value="closeMessage"
              class="ws-composer__box"
              style="width: 100%; min-height: 64px; padding: 10px 12px; font: inherit; font-size: 12px; resize: vertical"
              placeholder="填写结束说明（可选），仅内部记录"
              @input="emit('close-message-change', ($event.target as HTMLTextAreaElement).value)"
            />
            <div style="display: flex; gap: 8px; margin-top: 8px">
              <button class="ws-btn ws-btn--primary" :disabled="!canOperateHandoff || acting" @click="emit('close')">
                确认结束
              </button>
            </div>
          </div>

          <p v-if="!canOperateHandoff && session.handoff_status !== 'PENDING'" class="ws-note ws-note--warn" style="margin-top: 10px">
            该会话已由其他坐席接入，当前账号只能查看。
          </p>
        </section>

        <section v-if="historyAvailable && historyAccessAllowed" class="ws-section">
          <button class="ws-btn ws-btn--sm" :disabled="historyLoading" @click="emit('load-history')">
            {{ historyLoading ? '加载中…' : '查看更早历史' }}
          </button>
        </section>
      </template>
    </div>
  </aside>
</template>
