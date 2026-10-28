import type { Ticket, TicketResult } from '@/types/api'

export function ticketFromResult(ticketResult?: TicketResult): Ticket | null {
  if (!ticketResult || ticketResult.status !== 'success' || !ticketResult.data) {
    return null
  }
  return ticketResult.data
}

export function statusType(status?: string) {
  if (status === 'CLOSED') return 'success'
  if (status === 'PROCESSING') return 'warning'
  if (status === 'PENDING_ASSIGN' || status === 'PENDING_PROCESS') return 'info'
  if (status === 'TRANSFERRED' || status === 'REOPENED') return 'danger'
  return 'info'
}

/** 履约变更申请状态的中文展示，未知状态原样返回。 */
export function changeRequestStatusLabel(status: string) {
  const labels: Record<string, string> = {
    PENDING_REVIEW: '待审核',
    WAITING_CUSTOMER: '待客户补充',
    APPROVED: '已同意',
    REJECTED: '已拒绝'
  }
  return labels[status] || status
}
