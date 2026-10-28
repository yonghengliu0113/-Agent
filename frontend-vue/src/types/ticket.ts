/**
 * 工单域类型：业务工单、工单处理结果与履约变更子申请。
 * 客户侧与座席侧共用同一份工单结构，客户安全字段由后端裁剪后返回。
 */

/** 工单主结构，字段与 Java 业务服务返回保持一致。 */
export interface Ticket {
  id?: number
  ticketNo: string
  title?: string
  ticketType?: string
  priority?: string
  customerId?: number
  orderNo?: string | null
  sessionId?: number | null
  externalSessionNo?: string | null
  content?: string
  aiSummary?: string
  assignedGroup?: string | null
  handlerId?: number | null
  assignedBy?: 'MANUAL' | 'AUTO_RULE' | 'AI_ASSISTED' | string | null
  assignmentReason?: string | null
  assignmentScore?: number | null
  assignedAt?: string | null
  status?: string
  slaDeadline?: string | null
  source?: string
  urgeCount?: number | null
  lastUrgedAt?: string | null
  lastUrgeReason?: string | null
  returnMethod?: string | null
  pickupTimeWindow?: string | null
  pickupStatus?: string | null
  createdAt?: string
  updatedAt?: string
}

/** 已提交履约变更的受控子申请；客户侧不会拿到审核人和幂等键。 */
export interface TicketChangeRequest {
  requestNo: string
  parentTicketNo?: string
  changeType: string
  previousReturnMethod?: string | null
  previousPickupTimeWindow?: string | null
  requestedReturnMethod?: string | null
  requestedPickupTimeWindow?: string | null
  parentTicketStatus?: string
  status: 'PENDING_REVIEW' | 'WAITING_CUSTOMER' | 'APPROVED' | 'REJECTED' | string
  customerMessage?: string | null
  createdAt?: string
  updatedAt?: string
}

/** Agent 工具创建工单后的结果包装，成功时携带最新工单快照。 */
export interface TicketResult {
  status: 'success' | 'failed' | string
  data?: Ticket
  error?: string
}
