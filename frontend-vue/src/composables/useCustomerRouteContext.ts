import { ref, type Ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import type { ChatSession, CustomerOrder, Ticket } from '@/types/api'

/**
 * 客户智能客服页的外部入口上下文处理。
 * 负责把 URL 中的会话、订单、工单和首条消息应用到当前页面，
 * 并通过一次性标记避免 mounted / activated / watch 重复创建会话。
 */
export function useCustomerRouteContext(options: {
  sessions: Ref<ChatSession[]>
  orders: Ref<CustomerOrder[]>
  tickets: Ref<Ticket[]>
  selectedSessionId: Ref<string | null>
  selectedOrderNo: Ref<string | null>
  selectedTicketNo: Ref<string | null>
  messageText: Ref<string>
  selectSession: (sessionId: string) => Promise<void>
  createNewSession: () => Promise<ChatSession | null>
}) {
  const route = useRoute()
  const router = useRouter()
  const handledRouteContext = ref('')

  /** 应用外部入口携带的会话、订单和工单上下文，避免进入智能客服后丢失用户选择。 */
  async function applyRouteContext() {
    if (route.path !== '/customer/service' || handledRouteContext.value === route.fullPath) return
    // 在任何异步请求之前占用当前路由上下文，防止 mounted、activated 和 watch 重复创建会话。
    const contextPath = route.fullPath
    handledRouteContext.value = contextPath
    const sessionId = typeof route.query.sessionId === 'string' ? route.query.sessionId : ''
    const orderNo = typeof route.query.orderNo === 'string' ? route.query.orderNo : ''
    const ticketNo = typeof route.query.ticketNo === 'string' ? route.query.ticketNo : ''

    try {
      if (sessionId && options.sessions.value.some((item) => item.session_id === sessionId)) {
        await options.selectSession(sessionId)
      } else if (route.query.new === '1') {
        const createdSession = await options.createNewSession()
        // 创建成功后将一次性 new 标记替换为真实会话号，刷新和重复激活都不会再次创建。
        if (createdSession) {
          const nextQuery = { ...route.query }
          delete nextQuery.new
          nextQuery.sessionId = createdSession.session_id
          await router.replace({ path: route.path, query: nextQuery })
        }
      } else if (!orderNo && !ticketNo && typeof route.query.message !== 'string') {
        // 直接进入客服页时始终打开仓库排序后的首个会话，不能沿用空白的新会话。
        const primarySessionId = options.sessions.value[0]?.session_id
        if (primarySessionId) await options.selectSession(primarySessionId)
      }
      // 关联标识必须先经过当前客户已加载列表校验，不能直接信任 URL 参数。
      if (orderNo && options.orders.value.some((item) => item.orderNo === orderNo)) options.selectedOrderNo.value = orderNo
      if (ticketNo) {
        const linkedTicket = options.tickets.value.find((item) => item.ticketNo === ticketNo)
        if (linkedTicket) {
          options.selectedTicketNo.value = ticketNo
          // 从工单页进入客服页时，优先打开该工单绑定的会话。
          // 座席回复按 externalSessionNo 持久化；不做这一步会让客户留在无关会话而误以为未收到消息。
          const linkedSessionId = String(linkedTicket.externalSessionNo || '')
          if (!sessionId && linkedSessionId && options.sessions.value.some((item) => item.session_id === linkedSessionId)) {
            await options.selectSession(linkedSessionId)
          }
        }
      }
      if (typeof route.query.message === 'string') options.messageText.value = route.query.message
    } catch (error) {
      // 处理失败时释放占用，允许用户再次进入或刷新后重试。
      if (handledRouteContext.value === contextPath) handledRouteContext.value = ''
      throw error
    }
  }

  /** 离开智能客服后清空入口标记，用户再次从同一按钮进入时仍会新建正确上下文。 */
  function resetHandledContext() {
    handledRouteContext.value = ''
  }

  return { handledRouteContext, applyRouteContext, resetHandledContext }
}
