<script setup lang="ts">
import { ArrowDown, ArrowUp, Connection, DocumentCopy, Download, Headset, Message, Position, Refresh, Service, Tickets, UploadFilled, VideoPause } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'
import { computed, nextTick, onActivated, ref, watch } from 'vue'
import type { AgentReply, ChatMessage, ChatSession, CustomerOrder, Reference, Ticket } from '@/types/api'
import CitationMark from '@/components/customer/chat/CitationMark.vue'
import MessageActions from '@/components/customer/chat/MessageActions.vue'
import ReferenceDetailPanel from '@/components/customer/chat/ReferenceDetailPanel.vue'
import ReferenceList from '@/components/customer/chat/ReferenceList.vue'
import { normalizeReferences, parseContentCitations } from '@/utils/citations'

const props = defineProps<{
  messages: ChatMessage[]
  lastReply: AgentReply | null
  modelValue: string
  session: ChatSession | null
  submitting?: boolean
  selectedOrder: CustomerOrder | null
  selectedTicket: Ticket | null
  /** 当前输入框的受控业务语境，仅用于引导客户补充信息。 */
  composerHint?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'cancel-handoff': []
  // 单一对话流：提交时由父组件根据人工接管状态决定投递通道。
  submit: []
  cancel: []
  quick: [action: string]
  regenerate: [message: string]
  upload: [file: File]
  'download-attachment': [message: ChatMessage]
}>()

const chatWindowRef = ref<HTMLElement | null>(null)
const isComposing = ref(false)
// 人工接入信息默认展开；客户可收起大面积上下文卡片，避免遮挡会话内容。
const handoffDetailsCollapsed = ref(false)
const uploadInputRef = ref<HTMLInputElement | null>(null)

const inHumanHandoff = computed(() => ['PENDING', 'ACTIVE'].includes(String(props.session?.handoff_status || '')))
const inputPlaceholder = computed(() =>
  inHumanHandoff.value
    ? '请输入要补充给人工客服的信息...'
    : props.composerHint
      ? '请说明退货原因；可补充上门取件或方便取件的时间'
      : '请输入您的问题...'
)
const handoffStatusText = computed(() => ({ PENDING: '待接入', ACTIVE: '已接入', CLOSED: '已结束' }[String(props.session?.handoff_status)] || ''))
const handoffStatusType = computed(() => props.session?.handoff_status === 'ACTIVE' ? 'success' : props.session?.handoff_status === 'CLOSED' ? 'info' : 'warning')

/** 单一对话流：AI、人工与系统消息按时间顺序合并展示，不再区分页签。 */
const visibleMessages = computed(() => props.messages)
const visibleMessageEntries = computed(() =>
  visibleMessages.value.map((message, index, list) => ({
    message,
    timeDivider: shouldShowTimeDivider(message, list[index - 1]) ? formatTimeDivider(message) : ''
  }))
)

/** 参考文献交互状态：详情面板与展开列表按消息维度记录。 */
const detailVisible = ref(false)
const activeReference = ref<Reference | null>(null)
const activeReferenceMessageId = ref<number | null>(null)
const expandedReferencesMessageId = ref<number | null>(null)

function messageReferences(message: ChatMessage): Reference[] {
  return normalizeReferences(message.extra_data?.citations)
}

function messagePlainText(message: ChatMessage): string {
  return parseContentCitations(message.content, messageReferences(message)).plainText
}

const lastReplyReferences = computed(() => normalizeReferences(props.lastReply?.citations))
const streamingPlainText = computed(() =>
  parseContentCitations(props.lastReply?.customer_message || props.lastReply?.answer || '', lastReplyReferences.value).plainText
)

function openStreamingReference(index: number) {
  const reference = lastReplyReferences.value.find((item) => item.index === index) ?? null
  activeReference.value = reference
  activeReferenceMessageId.value = 0
  detailVisible.value = true
}

function toggleReferences(message: ChatMessage) {
  expandedReferencesMessageId.value = expandedReferencesMessageId.value === message.id ? null : message.id
}

function openReference(index: number, message: ChatMessage) {
  const references = messageReferences(message)
  const reference = references.find((item) => item.index === index) ?? null
  // 找不到对应文献时也打开面板展示“未找到”，符合多引用/数据缺失场景。
  activeReference.value = reference
  activeReferenceMessageId.value = message.id
  detailVisible.value = true
  if (references.length) {
    expandedReferencesMessageId.value = message.id
  }
}

/** 客户可见的会话工单号：优先取会话预建工单，其次取前端选中的工单。 */
const sessionTicketNo = computed(() => props.session?.ticket_no || props.selectedTicket?.ticketNo || '')

function isAttachmentMessage(message: ChatMessage) {
  return message.message_type === 'attachment' || Boolean(message.extra_data?.attachment)
}

function attachmentMeta(message: ChatMessage) {
  return (message.extra_data?.attachment || {}) as { name?: string; size?: number; content_type?: string; stored_name?: string }
}

function formatBytes(size?: number) {
  const bytes = Number(size || 0)
  if (!bytes) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const markdown = new MarkdownIt({
  breaks: true,
  html: false,
  linkify: true,
  typographer: false
})

function normalizeAssistantMarkdown(content: string) {
  // 客户侧不展示裸知识库 citation_id；后端仍保留结构化 citations 供评测、Trace 和坐席诊断使用。
  const normalized = String(content || '')
    .replace(/【(?:来源|引用)[:：]\s*kb-[^】]+】/g, '')
    .replace(/\r\n?/g, '\n')
    .trim()
  if (!normalized) return ''

  const lines = normalized.split('\n')
  const meaningfulLines = lines.filter((line) => line.trim())
  const firstLine = meaningfulLines[0]?.trim() || ''
  const hasMarkdownBlocks = lines.some((line) => /^\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s|>\s|```)/.test(line))
  const looksLikeTitle =
    meaningfulLines.length > 1 &&
    firstLine.length <= 24 &&
    /(?:说明|规则|指南|步骤|条件|流程|方式|建议|：|:)$/.test(firstLine)

  if (!hasMarkdownBlocks && looksLikeTitle) {
    const titleIndex = lines.findIndex((line) => line.trim() === firstLine)
    lines[titleIndex] = `### ${firstLine.replace(/[：:]$/, '')}`
    return lines.join('\n')
  }

  if (!hasMarkdownBlocks && !normalized.includes('\n\n') && normalized.length >= 180) {
    // 旧回复若仍是超长纯文本，按完整句子分段，避免改变原始语义或业务顺序。
    const sentences = normalized.match(/[^。！？!?；;]+[。！？!?；;]?/g)?.map((item) => item.trim()).filter(Boolean) || []
    if (sentences.length >= 4) {
      const paragraphs: string[] = []
      for (let index = 0; index < sentences.length; index += 2) {
        paragraphs.push(sentences.slice(index, index + 2).join(''))
      }
      return paragraphs.join('\n\n')
    }
  }

  return normalized
}

function renderMessageMarkdown(content: string) {
  // Markdown 禁用原始 HTML，并再次清洗生成结果，避免聊天内容注入可执行标签或属性。
  return DOMPurify.sanitize(markdown.render(normalizeAssistantMarkdown(content)), {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['style', 'iframe', 'form']
  })
}

type MessageTimeSource = ChatMessage & {
  createTime?: string | number | Date | null
  createdAt?: string | number | Date | null
  sendTime?: string | number | Date | null
  timestamp?: string | number | Date | null
}

function parseMessageDate(value: string | number | Date | null | undefined) {
  if (!value) return new Date()
  if (value instanceof Date) return value
  if (typeof value === 'number') return new Date(value)

  const normalized = value.includes('T') && !/[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? `${value}Z` : value
  const parsed = new Date(normalized)
  return Number.isNaN(parsed.getTime()) ? new Date() : parsed
}

function messageDate(message?: MessageTimeSource | null) {
  const rawTime = message?.created_at ?? message?.createdAt ?? message?.createTime ?? message?.sendTime ?? message?.timestamp
  return parseMessageDate(rawTime)
}

function isSameCalendarDay(left: Date, right: Date) {
  return left.getFullYear() === right.getFullYear()
    && left.getMonth() === right.getMonth()
    && left.getDate() === right.getDate()
}

function shouldShowTimeDivider(message: ChatMessage, previous?: ChatMessage) {
  // 第一条消息必须显示时间；跨天或距离上一条消息达到 10 分钟时显示新的时间分隔条。
  if (!previous) return true
  const currentDate = messageDate(message)
  const previousDate = messageDate(previous)
  if (!isSameCalendarDay(currentDate, previousDate)) return true
  return currentDate.getTime() - previousDate.getTime() >= 10 * 60 * 1000
}

function formatTimeDivider(message: ChatMessage) {
  const date = messageDate(message)
  const now = new Date()
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  const time = new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  }).format(date)
  if (isSameCalendarDay(date, now)) return `今天 ${time}`
  if (isSameCalendarDay(date, yesterday)) return `昨天 ${time}`
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day} ${time}`
}

function senderLabel(message: ChatMessage) {
  if (message.sender_type === 'staff') return '人工客服'
  if (message.sender_type === 'system') return '系统'
  return '智能助手'
}

function messageClass(message: ChatMessage) {
  if (message.sender_type === 'customer') return 'from-user'
  if (message.sender_type === 'staff') return 'from-staff'
  if (message.sender_type === 'system') return 'from-system'
  return 'from-agent'
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

function handleInputKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || isComposing.value) return
  event.preventDefault()
  if (props.submitting || !props.modelValue.trim()) return
  emit('submit')
}

function pickAttachment() {
  uploadInputRef.value?.click()
}

function onAttachmentPicked(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  emit('upload', file)
  // 允许连续选择同一文件时再次触发 change 事件。
  input.value = ''
}

async function scrollToBottom() {
  await nextTick()
  const target = chatWindowRef.value
  if (target) {
    // 首次进入、切换会话和历史消息回填必须直接定位，避免整段会话从顶部缓慢滑到底部。
    target.scrollTo({ top: target.scrollHeight, behavior: 'auto' })
  }
}

onActivated(() => {
  void scrollToBottom()
})

watch(
  () => [visibleMessages.value.length, props.lastReply?.answer],
  () => {
    void scrollToBottom()
  },
  { immediate: true }
)

watch(
  () => ({
    sessionId: props.session?.session_id || '',
    handoffStatus: props.session?.handoff_status || ''
  }),
  (current, previous) => {
    if (!previous || current.sessionId !== previous.sessionId) {
      // 切换会话后恢复展开，避免把上一会话的界面偏好误带入当前人工记录。
      handoffDetailsCollapsed.value = false
    }
  },
  { immediate: true }
)
</script>

<template>
  <section class="chat-panel dashboard-card">
    <div class="chat-header">
      <div>
        <h2>在线客服</h2>
        <p><span class="online-dot"></span>智能助手 · 7x24小时为您服务</p>
      </div>
      <div class="chat-header-actions">
        <el-button :icon="Headset" plain @click="emit('quick', '转人工客服')">转人工客服</el-button>
      </div>
    </div>

    <div class="chat-context-strip">
      <span v-if="selectedOrder">
        <el-icon><Message /></el-icon>
        当前订单：{{ selectedOrder.orderNo }}
      </span>
      <span v-if="sessionTicketNo">
        <el-icon><Tickets /></el-icon>
        当前工单：{{ sessionTicketNo }}
      </span>
      <span v-if="!selectedOrder && !sessionTicketNo">当前为无订单咨询，可直接提问规则、发票、会员或人工服务问题</span>
    </div>

    <div
      v-if="handoffStatusText"
      :class="['human-status-card', { 'is-collapsed': handoffDetailsCollapsed }]"
    >
      <div class="human-status-main">
        <div class="human-status-title">
          <span>当前状态</span>
          <strong>{{ handoffStatusText }}</strong>
        </div>
        <div class="human-status-actions">
          <el-button v-if="session?.handoff_status === 'PENDING'" size="small" @click="emit('cancel-handoff')">取消排队</el-button>
          <el-tag :type="handoffStatusType">{{ session?.handoff_status }}</el-tag>
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
                  @select="(reference) => { activeReference = reference; activeReferenceMessageId = entry.message.id; detailVisible = true }"
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

    <div class="quick-actions">
      <el-button :disabled="!selectedOrder" :icon="Connection" @click="emit('quick', '查询物流')">查看物流</el-button>
      <el-button :disabled="!selectedOrder" :icon="Refresh" @click="emit('quick', '申请退货')">申请退货退款</el-button>
      <el-button :icon="Tickets" @click="emit('quick', '催办工单')">催办工单</el-button>
      <el-button :icon="Service" @click="emit('quick', '转人工客服')">转人工客服</el-button>
    </div>

    <ReferenceDetailPanel v-model="detailVisible" :reference="activeReference" />

    <div class="chat-input-box">
      <div v-if="composerHint" class="composer-context-hint">
        <el-icon><Refresh /></el-icon>
        <span>{{ composerHint }}，请补充原因；不填写也可直接发送。</span>
      </div>
      <el-input
        :model-value="modelValue"
        :autosize="{ minRows: 1, maxRows: 5 }"
        :placeholder="inputPlaceholder"
        type="textarea"
        @compositionend="isComposing = false"
        @compositionstart="isComposing = true"
        @keydown="handleInputKeydown"
        @update:model-value="emit('update:modelValue', String($event))"
      />
      <div class="chat-input-footer">
        <div class="input-tools">
          <input ref="uploadInputRef" class="hidden-file-input" type="file" @change="onAttachmentPicked" />
          <el-tooltip content="上传附件" placement="top">
            <el-button class="input-tool-button" text circle :icon="UploadFilled" aria-label="上传附件" @click="pickAttachment" />
          </el-tooltip>
        </div>
        <el-tooltip v-if="submitting" content="停止本次生成，已显示的内容会保留" placement="top">
          <el-button class="generation-stop-button" :icon="VideoPause" aria-label="停止生成" @click="emit('cancel')">
            停止生成
          </el-button>
        </el-tooltip>
        <el-button v-else :icon="Position" circle type="primary" @click="emit('submit')" />
      </div>
    </div>
  </section>
</template>
