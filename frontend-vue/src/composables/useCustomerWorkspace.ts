import { computed, ref, type Ref } from 'vue'

import { customerApi } from '@/api/customer'
import { useAuthStore } from '@/stores/auth'
import { useCustomerSessionStore } from '@/stores/customerSessions'
import type { AgentReply, AgentStatus, ChatSession, CustomerOrder, Ticket } from '@/types/api'

/** 路由切换间保留的客户安全数据快照，避免反复展示骨架屏。 */
interface CustomerWorkspaceCache {
  customerId: number | string
  agentStatus: AgentStatus | null
  orders: CustomerOrder[]
  tickets: Ticket[]
  sessions: ChatSession[]
}

// 模块级缓存：同一浏览器内跨组件实例保留已读数据，与原实现保持一致。
let workspaceCache: CustomerWorkspaceCache | null = null

/**
 * 客户工作区数据：Agent 状态、订单、工单与缓存恢复。
 * 会话列表与消息由 useCustomerConversation 管理，这里只通过传入的引用读取，
 * 避免两个 composable 互相依赖。
 */
export function useCustomerWorkspace(options: {
  sessions: Ref<ChatSession[]>
  selectedSessionId: Ref<string | null>
}) {
  const auth = useAuthStore()
  const sessionStore = useCustomerSessionStore()

  const agentStatus = ref<AgentStatus | null>(null)
  const orders = ref<CustomerOrder[]>([])
  const tickets = ref<Ticket[]>([])
  const selectedOrderNo = ref<string | null>(null)
  const selectedTicketNo = ref<string | null>(null)
  const loadingOrders = ref(false)
  const loadingTickets = ref(false)

  const selectedOrder = computed(() => orders.value.find((item) => item.orderNo === selectedOrderNo.value) ?? null)
  const selectedTicket = computed(() => tickets.value.find((item) => item.ticketNo === selectedTicketNo.value) ?? null)

  /** 把当前已读数据写入模块级缓存；身份缺失时不做任何缓存。 */
  function cacheCustomerWorkspace() {
    const customerId = auth.user?.customer_id
    if (customerId === undefined || customerId === null) return
    workspaceCache = {
      customerId,
      agentStatus: agentStatus.value,
      orders: orders.value,
      tickets: tickets.value,
      sessions: options.sessions.value
    }
  }

  /** 恢复同身份的缓存数据；恢复成功时返回 true，由父页面决定是否后台静默刷新。 */
  function restoreCustomerWorkspace() {
    const customerId = auth.user?.customer_id
    if (!workspaceCache || customerId === undefined || customerId === null || workspaceCache.customerId !== customerId) return false
    agentStatus.value = workspaceCache.agentStatus
    orders.value = workspaceCache.orders
    tickets.value = workspaceCache.tickets
    if (!sessionStore.loaded) sessionStore.replace(workspaceCache.sessions)
    options.selectedSessionId.value = options.sessions.value[0]?.session_id ?? null
    selectedTicketNo.value = tickets.value[0]?.ticketNo ?? null
    return true
  }

  /** 读取 Agent 运行状态，供首页展示模型提供方。 */
  async function loadAgentStatus() {
    const { data } = await customerApi.agentStatus()
    agentStatus.value = data
    cacheCustomerWorkspace()
  }

  /** 读取客户订单；showLoading=false 用于后台静默刷新。 */
  async function loadOrders(showLoading = true) {
    if (showLoading) loadingOrders.value = true
    try {
      const { data } = await customerApi.orders()
      orders.value = data
      cacheCustomerWorkspace()
      if (selectedOrderNo.value && !data.some((item) => item.orderNo === selectedOrderNo.value)) {
        selectedOrderNo.value = null
      }
    } finally {
      if (showLoading) loadingOrders.value = false
    }
  }

  /** 读取客户工单；首次加载时默认选中第一张工单。 */
  async function loadTickets(showLoading = true) {
    if (showLoading) loadingTickets.value = true
    try {
      const { data } = await customerApi.tickets()
      tickets.value = data
      cacheCustomerWorkspace()
      if (!selectedTicketNo.value && data.length) {
        selectedTicketNo.value = data[0].ticketNo
      }
    } finally {
      if (showLoading) loadingTickets.value = false
    }
  }

  /**
   * 把 AI 回复携带的最新工单合并进本地列表。
   * 返回是否发生建单/状态变化，供调用方决定是否后台刷新工单接口。
   */
  function mergeReplyTicket(reply: AgentReply) {
    const ticket = reply.ticket_result?.data
    if (reply.ticket_result?.status !== 'success' || !ticket?.ticketNo) {
      return false
    }

    // 回复已携带最新工单时先更新本地列表，后台校准期间页面不会短暂显示旧状态。
    const ticketIndex = tickets.value.findIndex((item) => item.ticketNo === ticket.ticketNo)
    if (ticketIndex >= 0) {
      tickets.value = tickets.value.map((item, index) => (index === ticketIndex ? { ...item, ...ticket } : item))
    } else {
      tickets.value = [ticket, ...tickets.value]
    }
    return true
  }

  return {
    agentStatus,
    orders,
    tickets,
    selectedOrderNo,
    selectedTicketNo,
    loadingOrders,
    loadingTickets,
    selectedOrder,
    selectedTicket,
    cacheCustomerWorkspace,
    restoreCustomerWorkspace,
    loadAgentStatus,
    loadOrders,
    loadTickets,
    mergeReplyTicket
  }
}
