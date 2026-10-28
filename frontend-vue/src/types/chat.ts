import type { TicketResult } from './ticket'

/**
 * 会话与消息域类型：客户会话、聊天消息、AI 回复与参考文献。
 * Reference / CitationLike 同时服务于客户侧展示和内部评测结果。
 */

/** 客户会话主结构。 */
export interface ChatSession {
  id: number
  session_id: string
  customer_id: number
  status: string
  handoff_status: 'NONE' | 'PENDING' | 'ACTIVE' | 'CLOSED' | string
  title: string | null
  intent: string | null
  emotion: string | null
  priority: string | null
  ai_summary: string | null
  human_requested_at?: string | null
  human_assigned_staff_id?: string | null
  human_assigned_staff_name?: string | null
  human_accepted_at?: string | null
  human_closed_at?: string | null
  handoff_reason?: string | null
  ticket_no?: string | null
  created_at: string
  updated_at: string
  deleted_at?: string | null
  pinned_at?: string | null
}

/** AI 回复的参考文献条目，字段与后端 customer_reference_payloads 对应。 */
export interface Reference {
  id: string
  index: number
  title: string
  authors?: string[] | null
  source?: string | null
  collection?: string | null
  risk_level?: string | null
  year?: string | null
  url?: string | null
  abstract?: string | null
  content?: string | null
  snippet?: string | null
}

/** 后端 Citation 原始形态，用于兼容旧数据与轮询结果。 */
export interface CitationLike {
  citation_id?: string | null
  doc_name?: string | null
  paragraph?: string | null
  collection?: string | null
  business_scope?: string | null
  heading_path?: string[] | null
  risk_level?: string | null
  metadata?: Record<string, unknown> | null
  [key: string]: unknown
}

/** 单条聊天消息，extra_data 承载附件、引用与路由目标等扩展信息。 */
export interface ChatMessage {
  id: number
  session_id: string
  sender_type: 'customer' | 'ai' | 'staff' | string
  sender_id?: string | null
  content: string
  message_type: string
  extra_data: {
    ticket_result?: TicketResult
    customer_visible?: boolean
    route_target?: string
    message_source?: string
    attachment?: { name?: string; size?: number; content_type?: string; stored_name?: string }
    citations?: (Reference | CitationLike)[]
    [key: string]: unknown
  }
  created_at: string
}

/** 会话详情接口返回结构，包含最新消息游标。 */
export interface ChatSessionDetail {
  session: ChatSession | null
  messages: ChatMessage[]
  latest_message_id: number
}

/** Agent 单次回复结果，客户侧只消费其中的客户安全字段。 */
export interface AgentReply {
  session_id: string
  answer: string
  customer_message?: string
  service_status?: string
  auto_send: boolean
  need_human: boolean
  ticket_result?: TicketResult
  citations?: (Reference | CitationLike)[]
}

/** 消息投递通道：AI、人工或两者兼顾。 */
export type RouteTarget = 'ai' | 'human' | 'both'
