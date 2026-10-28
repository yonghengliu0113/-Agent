import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { staffHandoffApi } from '@/api/staff'
import { useStaffChangeRequests } from '@/composables/useStaffChangeRequests'
import { useStaffHandoff } from '@/composables/useStaffHandoff'
import { useStaffPolling } from '@/composables/useStaffPolling'
import { useStaffTicketActions } from '@/composables/useStaffTicketActions'
import { useStaffTicketMessages } from '@/composables/useStaffTicketMessages'
import { useStaffTicketQueue } from '@/composables/useStaffTicketQueue'
import { useAuthStore } from '@/stores/auth'
import type { ChatMessage, Ticket } from '@/types/api'

type Tone = 'accent' | 'ok' | 'warn' | 'danger' | 'default'

/**
 * 坐席工作台的页面级状态与数据编排。
 *
 * 从 StaffHome.vue 抽出，让页面文件只保留模板与少量交互绑定。
 * 这里负责：模式切换、面板折叠、队列/对话/上下文三类数据源串联、
 * 轮询调度、发送编排与生命周期。
 */
export function useStaffWorkspace() {
  const router = useRouter()
  const auth = useAuthStore()

  const workMode = ref<'tickets' | 'handoff'>('tickets')
  const acting = ref(false)
  const sending = ref(false)
  const queueCollapsed = ref(false)
  const contextCollapsed = ref(false)
  const contextTab = ref<'detail' | 'evidence'>('detail')

  const queue = useStaffTicketQueue()
  const ticketMessages = useStaffTicketMessages()
  const changeRequests = useStaffChangeRequests({
    selectedTicketNo: queue.selectedTicketNo,
    selectedTicket: queue.selectedTicket,
    canOperate: queue.canOperate,
    loadTickets: queue.loadTickets
  })
  const ticketActions = useStaffTicketActions({
    selectedTicket: queue.selectedTicket,
    selectedTicketNo: queue.selectedTicketNo,
    queueScope: queue.queueScope,
    acting,
    loadTickets: queue.loadTickets,
    loadChangeRequests: changeRequests.loadChangeRequests
  })
  const handoff = useStaffHandoff({ acting })
  const polling = useStaffPolling({
    // 队列轮询同时刷新工单与人工会话，避免工单队列长时间不更新
    loadHandoffSessions: async (keepSelection?: boolean) => {
      await Promise.all([handoff.loadHandoffSessions(keepSelection), queue.loadTickets()])
    },
    // 详情轮询按当前模式分流：工单取会话正文，人工会话取接管详情
    pollHandoffDetail: async () => {
      if (workMode.value === 'tickets') return ticketMessages.refresh(queue.selectedTicketNo.value)
      return handoff.pollHandoffDetail()
    }
  })

  /**
   * 选中工单后统一加载三份数据：客户对话、履约变更申请、AI 判断依据。
   * 用 watch 而不是在多处手动调用，保证"自动选中第一条"与"手动点击"行为一致。
   */
  watch(
    queue.selectedTicketNo,
    (ticketNo) => {
      ticketActions.resetDraft()
      ticketMessages.reset()
      if (!ticketNo) return
      void ticketMessages.load(ticketNo)
      void changeRequests.loadChangeRequests(ticketNo)
      void ticketActions.loadTicketAiContext(ticketNo)
    },
    { immediate: true }
  )

  const isTicketMode = computed(() => workMode.value === 'tickets')

  /** 中间主区消息：工单取工单会话正文，人工模式取接管详情。 */
  const conversationMessages = computed<ChatMessage[]>(() =>
    isTicketMode.value ? ticketMessages.messages.value : handoff.handoffMessages.value
  )

  /** 主区标题以"对方是谁"为主，工单号/会话号作为副标题。 */
  const conversationTitle = computed(() => {
    if (isTicketMode.value) {
      return queue.selectedTicket.value ? `工单 ${queue.selectedTicket.value.ticketNo}` : '未选择工单'
    }
    return handoff.selectedHandoff.value ? `客户 #${handoff.selectedHandoff.value.customer_id}` : '未选择会话'
  })

  const conversationSubtitle = computed(() => {
    if (isTicketMode.value) {
      const ticket = queue.selectedTicket.value
      return ticket?.title || ticket?.content || '从左侧队列选择工单'
    }
    const session = handoff.selectedHandoff.value
    return session ? `会话 ${session.session_id}` : '从左侧队列选择待接入会话'
  })

  const TICKET_STATUS: Record<string, { text: string; tone: Tone }> = {
    PENDING_ASSIGN: { text: '待分派', tone: 'warn' },
    ASSIGNED: { text: '已分派', tone: 'warn' },
    PROCESSING: { text: '处理中', tone: 'accent' },
    CLOSED: { text: '已关闭', tone: 'ok' },
    CANCELLED: { text: '已取消', tone: 'default' }
  }

  const conversationTags = computed<{ text: string; tone: Tone }[]>(() => {
    if (isTicketMode.value) {
      const status = String(queue.selectedTicket.value?.status || '')
      if (!status) return []
      return [TICKET_STATUS[status] || { text: status, tone: 'default' }]
    }
    const session = handoff.selectedHandoff.value
    if (!session) return []
    return [
      session.handoff_status === 'ACTIVE' ? { text: '接管中', tone: 'ok' } : { text: '等待接入', tone: 'warn' }
    ]
  })

  /** 是否可发送，以及不可发送的原因（直接展示在输入框上方）。 */
  const canReply = computed(() => {
    if (isTicketMode.value) return queue.canOperate.value && Boolean(queue.selectedTicket.value)
    return handoff.canOperateHandoff.value && handoff.selectedHandoff.value?.handoff_status === 'ACTIVE'
  })

  const replyHint = computed(() => {
    if (isTicketMode.value) {
      if (queue.canClaim.value) return '先领取工单后才能回复客户'
      if (!queue.canOperate.value) return '该工单由其他坐席处理，当前只能查看对话'
      return ''
    }
    const status = handoff.selectedHandoff.value?.handoff_status
    if (status === 'PENDING') return '先接入会话后才能回复客户'
    if (!handoff.canOperateHandoff.value) return '该会话已由其他坐席接入，当前只能查看'
    return ''
  })

  /**
   * 输入框内容：工单模式复用 draftMessage（AI 草稿会直接落到输入框），
   * 人工模式复用 handoffReply，两侧发送逻辑因此都不需要改动。
   */
  const composerDraft = computed({
    get: () => (isTicketMode.value ? ticketActions.draftMessage.value : handoff.handoffReply.value),
    set: (value: string) => {
      if (isTicketMode.value) ticketActions.draftMessage.value = value
      else handoff.handoffReply.value = value
    }
  })

  function selectTicket(ticket: Ticket) {
    queue.selectedTicketNo.value = ticket.ticketNo
  }

  function handleChangeRequestMessage(payload: { requestNo: string; value: string }) {
    changeRequests.changeRequestMessages.value = {
      ...changeRequests.changeRequestMessages.value,
      [payload.requestNo]: payload.value
    }
  }

  function switchMode(mode: 'tickets' | 'handoff') {
    workMode.value = mode
    contextTab.value = 'detail'
  }

  /** 发送：两种模式各自走既有接口，发送后由对应 composable 刷新消息。 */
  async function sendMessage() {
    if (!composerDraft.value.trim() || sending.value) return
    sending.value = true
    try {
      if (isTicketMode.value) {
        await ticketActions.sendReply()
        await ticketMessages.refresh(queue.selectedTicketNo.value)
      } else {
        await handoff.sendHandoffReply()
      }
    } finally {
      sending.value = false
    }
  }

  async function refreshQueue() {
    if (isTicketMode.value) await queue.loadTickets()
    else await handoff.loadHandoffSessions(false)
  }

  /** 退出登录：先停轮询并下线，再清理本地登录态。 */
  async function logout() {
    polling.stopStaffPolling()
    await staffHandoffApi.leave().catch(() => undefined)
    auth.logout()
    await router.push('/staff/login')
  }

  onMounted(async () => {
    await staffHandoffApi.heartbeat().catch(() => undefined)
    await Promise.all([queue.loadTickets(), handoff.loadHandoffSessions()])
    document.addEventListener('visibilitychange', polling.handleStaffVisibility)
    polling.startStaffPolling()
  })

  onBeforeUnmount(() => {
    polling.stopStaffPolling()
    document.removeEventListener('visibilitychange', polling.handleStaffVisibility)
    void staffHandoffApi.leave().catch(() => undefined)
  })

  return {
    // 页面级 UI 状态
    auth,
    router,
    workMode,
    acting,
    sending,
    queueCollapsed,
    contextCollapsed,
    contextTab,
    isTicketMode,
    switchMode,
    // 队列
    queue,
    selectTicket,
    refreshQueue,
    // 对话
    conversationMessages,
    conversationTitle,
    conversationSubtitle,
    conversationTags,
    canReply,
    replyHint,
    composerDraft,
    ticketMessages,
    handoff,
    sendMessage,
    // 工单上下文
    ticketActions,
    changeRequests,
    handleChangeRequestMessage,
    // 账号
    logout
  }
}
