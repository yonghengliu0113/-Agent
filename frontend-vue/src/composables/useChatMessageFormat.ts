import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'

import type { ChatMessage, Reference } from '@/types/api'
import { normalizeReferences, parseContentCitations } from '@/utils/citations'

/**
 * 聊天消息展示格式化能力。
 * 只负责 Markdown 渲染、引用文本、附件信息与时间分隔等纯展示转换；
 * 不发起请求、不持有页面状态，供消息列表组件复用。
 */

const markdown = new MarkdownIt({
  breaks: true,
  html: false,
  linkify: true,
  typographer: false
})

/**
 * 把后端返回的 AI 文本整理成适合展示的 Markdown：
 * 1. 剔除客户侧不可见的裸知识库 citation_id；
 * 2. 旧数据没有 Markdown 结构时，把疑似标题或超长纯文本补成可读段落。
 */
export function normalizeAssistantMarkdown(content: string) {
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

/** 渲染 AI 回复 Markdown；禁用原始 HTML 并二次清洗，避免聊天内容注入可执行标签。 */
export function renderMessageMarkdown(content: string) {
  return DOMPurify.sanitize(markdown.render(normalizeAssistantMarkdown(content)), {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['style', 'iframe', 'form']
  })
}

/** 读取消息中的参考文献；兼容客户安全结构与旧 Citation 结构。 */
export function messageReferences(message: ChatMessage): Reference[] {
  return normalizeReferences(message.extra_data?.citations)
}

/** 提取消息正文的纯文本版本，用于复制与引用角标剥离。 */
export function messagePlainText(message: ChatMessage): string {
  return parseContentCitations(message.content, messageReferences(message)).plainText
}

/** 判断消息是否为附件消息（类型标记或扩展字段二者取其一）。 */
export function isAttachmentMessage(message: ChatMessage) {
  return message.message_type === 'attachment' || Boolean(message.extra_data?.attachment)
}

/** 读取附件元信息，缺失时返回空对象由展示层兜底。 */
export function attachmentMeta(message: ChatMessage) {
  return (message.extra_data?.attachment || {}) as { name?: string; size?: number; content_type?: string; stored_name?: string }
}

/** 把字节数格式化为易读的 B / KB / MB。 */
export function formatBytes(size?: number) {
  const bytes = Number(size || 0)
  if (!bytes) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** 消息时间的兼容字段集合，历史数据可能使用不同命名。 */
type MessageTimeSource = ChatMessage & {
  createTime?: string | number | Date | null
  createdAt?: string | number | Date | null
  sendTime?: string | number | Date | null
  timestamp?: string | number | Date | null
}

/** 解析后端时间字符串；无时区信息时按 UTC 处理，解析失败回退当前时间。 */
function parseMessageDate(value: string | number | Date | null | undefined) {
  if (!value) return new Date()
  if (value instanceof Date) return value
  if (typeof value === 'number') return new Date(value)

  const normalized = value.includes('T') && !/[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? `${value}Z` : value
  const parsed = new Date(normalized)
  return Number.isNaN(parsed.getTime()) ? new Date() : parsed
}

/** 从消息的任一兼容字段解析出日期对象。 */
export function messageDate(message?: MessageTimeSource | null) {
  const rawTime = message?.created_at ?? message?.createdAt ?? message?.createTime ?? message?.sendTime ?? message?.timestamp
  return parseMessageDate(rawTime)
}

/** 判断两个时间是否落在同一自然日。 */
export function isSameCalendarDay(left: Date, right: Date) {
  return left.getFullYear() === right.getFullYear()
    && left.getMonth() === right.getMonth()
    && left.getDate() === right.getDate()
}

/** 第一条消息、跨天或间隔达到 10 分钟时显示时间分隔条。 */
export function shouldShowTimeDivider(message: ChatMessage, previous?: ChatMessage) {
  if (!previous) return true
  const currentDate = messageDate(message)
  const previousDate = messageDate(previous)
  if (!isSameCalendarDay(currentDate, previousDate)) return true
  return currentDate.getTime() - previousDate.getTime() >= 10 * 60 * 1000
}

/** 时间分隔条文案：今天 / 昨天 / 具体日期 + 时间。 */
export function formatTimeDivider(message: ChatMessage) {
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

/** 消息发送方展示名称。 */
export function senderLabel(message: ChatMessage) {
  if (message.sender_type === 'staff') return '人工客服'
  if (message.sender_type === 'system') return '系统'
  return '智能助手'
}

/** 消息气泡的样式类名。 */
export function messageClass(message: ChatMessage) {
  if (message.sender_type === 'customer') return 'from-user'
  if (message.sender_type === 'staff') return 'from-staff'
  if (message.sender_type === 'system') return 'from-system'
  return 'from-agent'
}

/** 组合式入口：消息列表按需解构使用，避免重复创建 Markdown 解析器。 */
export function useChatMessageFormat() {
  return {
    normalizeAssistantMarkdown,
    renderMessageMarkdown,
    messageReferences,
    messagePlainText,
    isAttachmentMessage,
    attachmentMeta,
    formatBytes,
    messageDate,
    isSameCalendarDay,
    shouldShowTimeDivider,
    formatTimeDivider,
    senderLabel,
    messageClass
  }
}
