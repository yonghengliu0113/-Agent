import { ElMessage } from 'element-plus'
import { ref, watch, type ComputedRef, type Ref } from 'vue'

import { staffTicketApi } from '@/api/staff'
import type { Ticket, TicketChangeRequest } from '@/types/api'
import { changeRequestStatusLabel } from '@/utils/ticket'

/**
 * 工单关联的履约变更申请。
 * 只有工单处理人可以读取和审核；无权限或网络异常时静默降级为空列表，
 * 不影响工单主界面与主操作。
 */
export function useStaffChangeRequests(options: {
  selectedTicketNo: Ref<string | null>
  selectedTicket: ComputedRef<Ticket | null>
  canOperate: ComputedRef<boolean>
  loadTickets: () => Promise<void>
}) {
  const ticketChangeRequests = ref<TicketChangeRequest[]>([])
  const loadingChangeRequests = ref(false)
  const decidingChangeRequestNo = ref<string | null>(null)
  const changeRequestMessages = ref<Record<string, string>>({})

  /** 读取已领取工单的改约子申请；无权限或网络异常不影响工单主界面。 */
  async function loadChangeRequests(ticketNo = options.selectedTicketNo.value) {
    if (!ticketNo || !options.canOperate.value) {
      ticketChangeRequests.value = []
      return
    }
    loadingChangeRequests.value = true
    try {
      const { data } = await staffTicketApi.changeRequests(ticketNo)
      if (options.selectedTicketNo.value === ticketNo) ticketChangeRequests.value = data
    } catch {
      if (options.selectedTicketNo.value === ticketNo) ticketChangeRequests.value = []
    } finally {
      loadingChangeRequests.value = false
    }
  }

  /** 座席以客户可见说明审核改约；页面不提供直接覆写原工单字段的入口。 */
  async function decideChangeRequest(request: TicketChangeRequest, decision: 'APPROVE' | 'REJECT' | 'NEED_MORE_INFO') {
    const ticket = options.selectedTicket.value
    if (!ticket || !options.canOperate.value || decidingChangeRequestNo.value) return
    decidingChangeRequestNo.value = request.requestNo
    try {
      const { data } = await staffTicketApi.decideChangeRequest(
        ticket.ticketNo,
        request.requestNo,
        decision,
        changeRequestMessages.value[request.requestNo] || ''
      )
      ElMessage.success(`履约变更申请已处理：${changeRequestStatusLabel(data.status)}`)
      await options.loadTickets()
      await loadChangeRequests(ticket.ticketNo)
    } finally {
      decidingChangeRequestNo.value = null
    }
  }

  // 切换工单或处理权限变化时重新读取变更申请，保持与原页面时序一致。
  watch([options.selectedTicketNo, options.canOperate], () => {
    void loadChangeRequests()
  })

  return {
    ticketChangeRequests,
    loadingChangeRequests,
    decidingChangeRequestNo,
    changeRequestMessages,
    loadChangeRequests,
    changeRequestStatusLabel,
    decideChangeRequest
  }
}
