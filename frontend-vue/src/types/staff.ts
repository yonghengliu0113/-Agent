import type { ChatMessage } from './chat'
import type { Ticket } from './ticket'

/**
 * 座席域类型：人工接管会话、工单 AI 决策依据与座席回复草稿。
 * 这些结构只允许出现在 /staff 内部页面，不得下发给客户侧。
 */

/** 座席回复草稿及其生成来源，供坐席判断是否需要重点润色。 */
export interface StaffReplyDraft {
  ticket_no: string
  session_id: string
  draft_message: string
  /** 草稿生成来源，仅供坐席判断是否需要重点润色。 */
  generation_mode?: 'llm' | 'fallback'
  /** 模型未可用时的安全原因，不返回供应商异常或请求详情。 */
  fallback_reason?: 'not_configured' | 'timeout' | 'rate_limit_429' | 'circuit_open' | 'network_error' | '5xx' | 'unsafe_output' | 'generation_error' | null
}

/** 人工接管队列中的会话摘要。 */
export interface StaffHandoffSession {
  session_id: string
  customer_id: number
  status: string
  session_status: string
  handoff_status: 'PENDING' | 'ACTIVE' | 'CLOSED' | string
  title?: string | null
  intent?: string | null
  emotion?: string | null
  priority?: string | null
  ai_summary?: string | null
  handoff_reason?: string | null
  human_requested_at?: string | null
  human_assigned_staff_id?: string | null
  human_assigned_staff_name?: string | null
  human_accepted_at?: string | null
  human_closed_at?: string | null
  waiting_seconds?: number
  linked_ticket_no?: string | null
  latest_message_id?: number
  latest_message_at?: string | null
  last_sender_type?: string | null
  updated_at?: string | null
}

/** 工单关联会话中的 AI 决策依据，供坐席判断转人工原因与回复依据。 */
export interface StaffTicketAiEvidence {
  message_id: number
  created_at?: string | null
  customer_message?: string | null
  decision_type?: string | null
  service_status?: string | null
  risk_reasons: string[]
  internal_suggestion?: string | null
  citations: Array<{
    citation_id?: string
    doc_name?: string
    paragraph?: string
    risk_level?: string
    collection?: string
    business_scope?: string
  }>
  tool_results: Array<{
    tool_name?: string
    query_type?: string
    status?: string
    error?: string
    retryable?: boolean
    data?: unknown
  }>
  ticket_result?: { ticketNo?: string | null; status?: string | null } | null
}

/** 工单 AI 决策上下文。 */
export interface StaffTicketContext {
  ticket_no: string
  ticket: Ticket
  session_id?: string | null
  handoff_reason?: string | null
  ai_evidence: StaffTicketAiEvidence[]
}

/** 人工会话详情，默认只返回最近相关窗口。 */
export interface StaffHandoffDetail {
  session: StaffHandoffSession
  messages: ChatMessage[]
  latest_message_id: number
  handoff_summary?: {
    title: string
    intent?: string | null
    priority?: string | null
    handoff_reason?: string | null
    ai_summary: string
    linked_ticket_no?: string | null
  }
  history_available?: boolean
  history_access_allowed?: boolean
}

/** 座席按需展开的更早历史分页。 */
export interface StaffHandoffHistoryPage {
  messages: ChatMessage[]
  history_available: boolean
  next_before_message_id?: number | null
}

/** 座席成员状态，用于排班与在线状态展示。 */
export interface StaffMemberStatus {
  userId: number
  displayName: string
  role: 'staff' | string
  groupName: string
  skills: string[]
  online: boolean
  maxActiveTickets: number
  acceptingTickets: boolean
  activeTickets: number
  currentWork: string[]
  recentFeedback: string[]
}
