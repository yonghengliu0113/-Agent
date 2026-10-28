/**
 * 客户消息域类型：站内通知与异步跟进任务。
 * 仅客户本人可见，后端按登录身份过滤。
 */

/** 客户站内通知。 */
export interface CustomerNotification {
  notification_id: string
  session_id: string
  followup_id?: string | null
  type: string
  title: string
  content: string
  is_read: boolean
  created_at: string
  read_at?: string | null
}

/** 客户异步跟进任务，如物流提醒或售后回访。 */
export interface CustomerFollowup {
  followup_id: string
  session_id: string
  task_type: string
  order_no: string
  scheduled_at: string
  status: 'PENDING' | 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED' | string
  result?: Record<string, unknown> | null
  created_at: string
  updated_at: string
}
