<script setup lang="ts">
import { DocumentCopy, Download, Service } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, nextTick, onActivated, ref, watch } from 'vue'

import CitationMark from '@/components/customer/chat/CitationMark.vue'
import MessageActions from '@/components/customer/chat/MessageActions.vue'
import ReferenceDetailPanel from '@/components/customer/chat/ReferenceDetailPanel.vue'
import ReferenceList from '@/components/customer/chat/ReferenceList.vue'
import { useChatMessageFormat } from '@/composables/useChatMessageFormat'
import type { AgentReply, ChatMessage, Reference } from '@/types/api'
import { normalizeReferences, parseContentCitations } from '@/utils/citations'

/**
 * 聊天消息列表：合并展示客户、AI、人工与系统消息，并承载时间分隔、附件、
 * 参考文献交互与流式回复气泡。滚动与复制等纯展示行为均在本组件内完成。
 */
const props = defineProps<{
  messages: ChatMessage[]
  lastReply: AgentReply | null
  submitting?: boolean
}>()

const emit = defineEmits<{
  regenerate: [message: string]
  'download-attachment': [message: ChatMessage]
}>()

const {
  renderMessageMarkdown,
  messageReferences,
  messagePlainText,
  isAttachmentMessage,
  attachmentMeta,
  formatBytes,
  shouldShowTimeDivider,
  formatTimeDivider,
  senderLabel,
  messageClass
} = useChatMessageFormat()

const chatWindowRef = ref<HTMLElement | null>(null)

/** 参考文献交互状态：详情面板与展开列表按消息维度记录。 */
const detailVisible = ref(false)
const activeReference = ref<Reference | null>(null)
const activeReferenceMessageId = ref<number | null>(null)
const expandedReferencesMessageId = ref<number | null>(null)

/** 单一对话流：AI、人工与系统消息按时间顺序合并展示，不再区分页签。 */
const visibleMessageEntries = computed(() =>
  props.messages.map((message, index, list) => ({
    message,
    timeDivider: shouldShowTimeDivider(message, list[index - 1]) ? formatTimeDivider(message) : ''
  }))
)

const lastReplyReferences = computed(() => normalizeReferences(props.lastReply?.citations))
const streamingPlainText = computed(() =>
  parseContentCitations(props.lastReply?.customer_message || props.lastReply?.answer || '', lastReplyReferences.value).plainText
)

/** 打开流式回复中的引用详情，消息 id 记为 0 与已落库消息区分。 */
function openStreamingReference(index: number) {
  const reference = lastReplyReferences.value.find((item) => item.index === index) ?? null
  activeReference.value = reference
  activeReferenceMessageId.value = 0
  detailVisible.value = true
}

/** 展开/收起单条消息的参考文献列表。 */
function toggleReferences(message: ChatMessage) {
  expandedReferencesMessageId.value = expandedReferencesMessageId.value === message.id ? null : message.id
}

/** 点击正文角标打开参考文献详情；找不到对应文献时也打开面板展示“未找到”。 */
function openReference(index: number, message: ChatMessage) {
  const references = messageReferences(message)
  const reference = references.find((item) => item.index === index) ?? null
  activeReference.value = reference
  activeReferenceMessageId.value = message.id
  detailVisible.value = true
  if (references.length) {
    expandedReferencesMessageId.value = message.id
  }
}

/** 从展开的文献列表选择条目时同步高亮并打开详情。 */
function selectReferenceFromList(reference: Reference, message: ChatMessage) {
  activeReference.value = reference
  activeReferenceMessageId.value = message.id
  detailVisible.value = true
}

/** 找到该 AI 回复之前的客户问题，用于通过现有受鉴权的回复链路重新生成。 */
function regeneratePrompt(message: ChatMessage) {
  const index = props.messages.findIndex((item) => item.id === message.id)
  for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
    const candidate = props.messages[cursor]
    if (candidate.sender_type === 'customer' && candidate.extra_data?.route_target !== 'human') return candidate.content
  }
  return ''
}

/** 复制客户可见的原始消息文本；Markdown 渲染结果不参与复制，避免混入页面结构。 */
async function copyMessage(content: string) {
  const text = String(content || '').trim()
  if (!text) {
    ElMessage.warning('暂无可复制内容')
    return
  }
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      // HTTP 或受限浏览器无法使用 Clipboard API 时，使用临时文本框完成兼容复制。
      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.setAttribute('readonly', '')
      textarea.style.cssText = 'position:fixed;opacity:0;pointer-events:none;'
      document.body.appendChild(textarea)
      textarea.select()
      const copied = document.execCommand('copy')
      document.body.removeChild(textarea)
      if (!copied) throw new Error('copy_failed')
    }
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败，请手动选择文本复制')
  }
}

/** 定位到消息底部；首次进入、切换会话和流式输出都直接对齐，避免缓慢滚动。 */
async function scrollToBottom() {
  await nextTick()
  const target = chatWindowRef.value
  if (target) {
    target.scrollTo({ top: target.scrollHeight, behavior: 'auto' })
  }
}

onActivated(() => {
  void scrollToBottom()
})

watch(
  () => [props.messages.length, props.lastReply?.answer],
  () => {
    void scrollToBottom()
  },
  { immediate: true }
)
</script>

<template>
  <div ref="chatWindowRef" class="chat-window">
    <template v-if="visibleMessageEntries.length">
      <template v-for="entry in visibleMessageEntries" :key="entry.message.id">
        <time v-if="entry.timeDivider" class="chat-time-divider">{{ entry.timeDivider }}</time>
        <div v-if="entry.message.sender_type === 'system'" class="handoff-system-notice" role="status">
          <el-icon><Service /></el-icon>
          <span>{{ entry.message.content }}</span>
        </div>
        <div
          v-else-if="isAttachmentMessage(entry.message)"
          :class="['chat-message', 'attachment-message', messageClass(entry.message)]"
        >
          <div class="attachment-card">
            <div class="attachment-card__name">{{ attachmentMeta(entry.message).name || '附件' }}</div>
            <div class="attachment-card__meta">
              <span>{{ formatBytes(attachmentMeta(entry.message).size) }}</span>
              <el-button
                link
                type="primary"
                size="small"
                :icon="Download"
                @click="emit('download-attachment', entry.message)"
              >下载</el-button>
            </div>
          </div>
        </div>
        <div
          v-else
          :class="['chat-message', messageClass(entry.message), { 'ai-flat': entry.message.sender_type === 'ai' }]"
        >
          <div class="message-stack">
            <span v-if="entry.message.sender_type === 'staff'" class="message-sender">{{ senderLabel(entry.message) }}</span>
            <!-- AI 回复占满对话框，无气泡；客户与人工客服消息保留气泡。 -->
            <div v-if="entry.message.sender_type === 'ai'" class="ai-flat-body">
              <CitationMark
                :content="entry.message.content"
                :references="messageReferences(entry.message)"
                :active-id="activeReferenceMessageId === entry.message.id ? activeReference?.id : null"
                @select-reference="(index) => openReference(index, entry.message)"
              />
              <MessageActions
                :references-count="messageReferences(entry.message).length"
                :references-expanded="expandedReferencesMessageId === entry.message.id"
                :submitting="submitting"
                :disabled="!regeneratePrompt(entry.message)"
                @copy="copyMessage(messagePlainText(entry.message))"
                @regenerate="emit('regenerate', regeneratePrompt(entry.message))"
                @toggle-references="toggleReferences(entry.message)"
              />
              <ReferenceList
                v-if="expandedReferencesMessageId === entry.message.id && messageReferences(entry.message).length"
                :references="messageReferences(entry.message)"
                :active-id="activeReferenceMessageId === entry.message.id ? activeReference?.id : null"
                @select="(reference) => selectReferenceFromList(reference, entry.message)"
              />
            </div>
            <div v-else class="message-bubble-shell">
              <div class="chat-bubble">
                <p v-if="entry.message.sender_type === 'customer'">{{ entry.message.content }}</p>
                <div v-else class="message-markdown" v-html="renderMessageMarkdown(entry.message.content)" />
              </div>
              <div class="message-bubble-actions">
                <el-tooltip content="复制" placement="bottom">
                  <el-button class="message-copy-action" text circle size="small" :icon="DocumentCopy" aria-label="复制消息" @click="copyMessage(entry.message.content)" />
                </el-tooltip>
              </div>
            </div>
          </div>
        </div>
      </template>
    </template>
    <div v-else class="chat-message from-agent ai-flat">
      <div class="message-stack">
        <div class="ai-flat-body">
          <p>
            您好，我可以帮您咨询售后规则、发票、会员权益或转人工服务；如需查询物流或申请退货退款，请先选择对应订单。
          </p>
        </div>
      </div>
    </div>
    <div v-if="lastReply" class="chat-message from-agent ai-flat">
      <div class="message-stack">
        <div class="ai-flat-body">
          <CitationMark
            :content="lastReply.customer_message || lastReply.answer"
            :references="lastReplyReferences"
            :active-id="activeReferenceMessageId === 0 ? activeReference?.id : null"
            @select-reference="(index) => openStreamingReference(index)"
          />
          <!-- 流式回复仅用于展示生成进度；在请求完成并落库前不提供复制，避免复制临时状态文案。 -->
          <div v-if="!submitting" class="message-bubble-actions"><el-tooltip content="复制" placement="bottom"><el-button class="message-copy-action" text circle size="small" :icon="DocumentCopy" aria-label="复制消息" @click="copyMessage(streamingPlainText)" /></el-tooltip></div>
        </div>
      </div>
    </div>
  </div>

  <ReferenceDetailPanel v-model="detailVisible" :reference="activeReference" />
</template>
