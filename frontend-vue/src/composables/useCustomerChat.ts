import { ElMessage } from 'element-plus'
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'

import { customerApi } from '@/api/customer'
import { useCustomerSessionStore } from '@/stores/customerSessions'
import type { AgentReply, ChatMessage, RouteTarget } from '@/types/api'

import type { useCustomerConversation } from './useCustomerConversation'
import { useCustomerReplyStream } from './useCustomerReplyStream'
import type { useCustomerWorkspace } from './useCustomerWorkspace'

type Conversation = ReturnType<typeof useCustomerConversation>
type Workspace = ReturnType<typeof useCustomerWorkspace>

/**
 * 客户聊天交互：输入框状态、消息提交（AI/人工通道）、流式回复、消息轮询、
 * 附件上传下载与快捷操作。
 * 会话列表和订单工单数据分别由 useCustomerConversation / useCustomerWorkspace 提供，
 * 本 composable 只做交互编排，不直接持有这些数据源。
 */
export function useCustomerChat(options: { conversation: Conversation; workspace: Workspace }) {
  const { conversation, workspace } = options
  const sessionStore = useCustomerSessionStore()
  const route = useRoute()

  const messageText = ref('')
  // 售后快捷入口只切换输入框的业务语境，订单号仍通过独立字段传给后端。
  const composerMode = ref<'default' | 'after_sale'>('default')
  const submitting = ref(false)
  const uploadingAttachment = ref(false)
  const activeRequestId = ref('')
  const stoppingGeneration = ref(false)
  let activeStreamController: AbortController | null = null
  let messagePollTimer: number | null = null
  let messagePollRunning = false
  let messagePollFailures = 0

  const replyStream = useCustomerReplyStream({
    lastReply: conversation.lastReply,
    activeRequestId,
    getSessionId: () => conversation.selectedSessionId.value,
    getSignal: () => activeStreamController?.signal
  })

  const composerHint = computed(() => {
    if (composerMode.value !== 'after_sale' || !workspace.selectedOrder.value) return ''
    return `正在为订单 ${workspace.selectedOrder.value.orderNo} 发起退货申请`
  })

  /** 清空输入框；新建会话时由父页面调用，保持与原逻辑一致（不重置售后语境）。 */
  function resetInput() {
    messageText.value = ''
  }

  /** 中止消息轮询定时器。 */
  function stopMessagePolling() {
    if (messagePollTimer !== null) window.clearTimeout(messagePollTimer)
    messagePollTimer = null
  }

  /** 仅当停留在智能客服页且页面可见时，继续按退避间隔轮询新消息。 */
  function scheduleMessagePolling(delay = 2000) {
    stopMessagePolling()
    if (document.hidden || route.path !== '/customer/service') return
    messagePollTimer = window.setTimeout(() => void pollCurrentSession(), delay)
  }

  /** 拉取当前会话增量消息；失败时按指数退避重试，不打断已展示内容。 */
  async function pollCurrentSession() {
    const sessionId = conversation.selectedSessionId.value
    if (!sessionId || messagePollRunning || submitting.value || document.hidden) {
      scheduleMessagePolling()
      return
    }
    messagePollRunning = true
    try {
      const { data } = await customerApi.sessionDetail(sessionId, conversation.latestMessageId.value)
      if (conversation.selectedSessionId.value !== sessionId) return
      const known = new Set(conversation.messages.value.map((item) => item.id))
      const additions = data.messages.filter((item) => !known.has(item.id))
      if (additions.length) conversation.messages.value = [...conversation.messages.value, ...additions]
      conversation.latestMessageId.value = Math.max(conversation.latestMessageId.value, data.latest_message_id || 0)
      if (data.session) sessionStore.prepend(data.session)
      messagePollFailures = 0
    } catch {
      messagePollFailures += 1
    } finally {
      messagePollRunning = false
      scheduleMessagePolling(Math.min(15000, 2000 * 2 ** messagePollFailures))
    }
  }

  function handleVisibilityChange() {
    if (document.hidden) stopMessagePolling()
    else scheduleMessagePolling(0)
  }

  /** 根据回复结果给出客户可见提示；普通知识咨询已在气泡中展示，不再重复弹窗。 */
  function showReplySubmitFeedback(reply: AgentReply) {
    const ticket = reply.ticket_result?.data
    if (reply.ticket_result?.status === 'success') {
      ElMessage.success(ticket?.ticketNo ? `已创建工单 ${ticket.ticketNo}` : '工单已提交')
      return
    }
    if (reply.service_status && reply.service_status !== '自动回复') {
      ElMessage.success(reply.service_status)
      return
    }
    if (reply.need_human) {
      // 人工接管有工作时间外、排队和等待接入等状态，后端未返回细分状态时才使用兜底文案。
      ElMessage.success('已记录人工服务请求')
      return
    }
    // 普通知识咨询或基础能力介绍已经在聊天气泡中展示，不再弹“问题已提交”误导用户。
  }

  /** 取消人工排队，并立即刷新会话状态与最新消息。 */
  async function cancelHandoff() {
    if (!conversation.selectedSessionId.value) return
    const { data } = await customerApi.cancelHandoff(conversation.selectedSessionId.value)
    sessionStore.prepend(data.session)
    await pollCurrentSession()
    ElMessage.success('已取消人工客服排队')
  }

  /**
   * 提交客户问题。
   * 人工排队中/已接入时消息直达人工通道，其余进入 AI 通道；
   * AI 通道复用同一幂等键完成 SSE 重连，避免重复执行 Agent 或重复建单。
   */
  async function submitQuestion() {
    if (submitting.value) {
      return
    }
    // 单一对话流：人工排队中/已接入时消息直达人工客服，其余进入 AI 通道。
    const handoffActive = conversation.selectedSession.value?.handoff_status === 'PENDING' || conversation.selectedSession.value?.handoff_status === 'ACTIVE'
    const submittedRouteTarget: RouteTarget = handoffActive ? 'human' : 'ai'
    // 售后模式下空白发送也代表“开始退货申请”，后端会基于已选订单继续追问真正缺失的槽位。
    const rawContent = messageText.value.trim()
    const submittedComposerMode = composerMode.value
    const content = submittedComposerMode === 'after_sale'
      ? (rawContent ? `我要申请退货，补充信息：${rawContent}` : '我要申请退货')
      : rawContent
    if (!content) {
      ElMessage.warning('请先输入问题')
      return
    }
    const tempMessageId = -Date.now()
    submitting.value = true
    activeRequestId.value = ''
    stoppingGeneration.value = false
    activeStreamController = new AbortController()
    messageText.value = ''
    composerMode.value = 'default'
    conversation.messages.value = [
      ...conversation.messages.value,
      {
        id: tempMessageId,
        session_id: conversation.selectedSessionId.value || 'pending',
        sender_type: 'customer',
        sender_id: null,
        content,
        message_type: 'text',
        extra_data: { route_target: submittedRouteTarget },
        created_at: new Date().toISOString()
      }
    ]
    // SSE 建连和首个 token 之间立即显示可见状态，避免客户误以为页面卡死。
    if (submittedRouteTarget === 'ai') {
      // 仅 AI 通道显示 SSE 阶段状态，避免人工确认信息串入智能助手页签。
      conversation.lastReply.value = {
        session_id: conversation.selectedSessionId.value || 'pending',
        answer: '正在接收您的问题…',
        customer_message: '正在接收您的问题…',
        service_status: '请求已发送',
        auto_send: false,
        need_human: false
      }
    } else {
      conversation.lastReply.value = null
    }
    try {
      // 同一次提交在所有 SSE 重连中复用幂等键，避免重复执行模型或重复创建工单。
      const idempotencyKey = `customer-web:${crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`}`
      const requestPayload = {
        message: content,
        session_id: conversation.selectedSessionId.value || null,
        selected_order_no: workspace.selectedOrderNo.value || null,
        selected_ticket_no: workspace.selectedTicketNo.value || null,
        route_target: submittedRouteTarget
      }
      if (submittedRouteTarget === 'human') {
        // 人工通道只执行消息落库，不入 Agent 队列，也不读取异步 request_id 的结果。
        const { data } = await customerApi.sendHandoffMessage(requestPayload)
        conversation.selectedSessionId.value = data.session_id || conversation.selectedSessionId.value
        await pollCurrentSession()
        await conversation.loadSessions(true)
        showReplySubmitFeedback(data)
        return
      }

      const result = await replyStream.requestAgentReply(requestPayload, idempotencyKey)
      // 两分钟内仍未结束时保留临时消息和 request_id 状态，不能回刷成提问前的旧会话。
      if (result.pending) return

      const data = result.data
      if (!data) throw new Error('未收到客服回复')
      conversation.selectedSessionId.value = data.session_id || conversation.selectedSessionId.value
      const ticketChanged = workspace.mergeReplyTicket(data)
      if (result.isFinal) {
        await conversation.loadSessions(true)
      }
      if (ticketChanged) {
        // 只有建单或工单状态发生变化时才后台刷新，普通 AI 回复不再触发工单接口。
        void workspace.loadTickets().catch(() => undefined)
      }
      // 只有确认后端已持久化结果后才清理临时回复，避免 DLQ/网络异常让回答从页面消失。
      if (result.isFinal) {
        conversation.lastReply.value = null
      }
      showReplySubmitFeedback(data)
    } catch (error) {
      // 主动 AbortController 关闭 SSE 是正常取消路径，不删除已显示的用户问题或部分回答。
      if (stoppingGeneration.value) return
      conversation.messages.value = conversation.messages.value.filter((item) => item.id !== tempMessageId)
      // 请求建立失败时恢复客户原本输入的补充信息，而不是恢复带有系统拼接前缀的提交文本。
      messageText.value = rawContent
      composerMode.value = submittedComposerMode
      throw error
    } finally {
      submitting.value = false
      activeRequestId.value = ''
      stoppingGeneration.value = false
      activeStreamController = null
    }
  }

  /** 停止当前生成：先通知后端，再关闭浏览器 SSE 读取，已输出文本继续保留。 */
  async function cancelCurrentGeneration() {
    const requestId = activeRequestId.value
    if (!requestId) {
      ElMessage.info('请求正在建立连接，稍后可停止生成')
      return
    }
    try {
      stoppingGeneration.value = true
      const { data } = await customerApi.cancelReply(requestId)
      if (conversation.lastReply.value && data.partial_answer) {
        conversation.lastReply.value = {
          ...conversation.lastReply.value,
          answer: data.partial_answer,
          customer_message: data.partial_answer,
          service_status: data.service_status
        }
      }
      activeStreamController?.abort()
      ElMessage.info(data.status === 'CANCELLED' ? '已停止本次生成' : '正在停止生成')
    } catch {
      ElMessage.warning('停止请求未完成，请稍后查看处理状态')
    }
  }

  /** 快捷操作：只改写输入框或直接提交，不绕过现有受鉴权的回复链路。 */
  function fillAndMaybeSend(action: string) {
    // 新的快捷操作不能沿用上一轮售后草稿语境，避免把普通咨询误包装为退货申请。
    if (action !== '申请退货') composerMode.value = 'default'
    if (action === '查询物流') {
      if (!workspace.selectedOrder.value) {
        ElMessage.warning('请先选择要查询物流的订单')
        return
      }
      messageText.value = `请帮我查询订单 ${workspace.selectedOrder.value.orderNo} 的物流`
      return
    }
    if (action === '申请退货') {
      if (!workspace.selectedOrder.value) {
        ElMessage.warning('请先选择要申请售后的订单')
        return
      }
      composerMode.value = 'after_sale'
      // 输入框只承载用户自行补充的内容；已选订单会由 selected_order_no 安全传递。
      messageText.value = ''
      ElMessage.info('请补充退货原因；也可以直接发送，由助手继续引导')
      return
    }
    if (action === '催办工单') {
      if (!workspace.selectedTicket.value) {
        ElMessage.warning('请先选择需要催办的工单')
        return
      }
      messageText.value = `请帮我催办工单 ${workspace.selectedTicket.value.ticketNo}`
      void submitQuestion()
      return
    }
    if (action === '发票问题') {
      messageText.value = workspace.selectedOrder.value ? `订单 ${workspace.selectedOrder.value.orderNo} 我想咨询发票问题` : '我想咨询发票问题'
      return
    }
    messageText.value = '请帮我转人工客服'
  }

  /** 重新提交该 AI 回复关联的原始问题，保留订单、工单和会话上下文。 */
  function regenerateAnswer(message: string) {
    if (submitting.value || !message.trim()) return
    composerMode.value = 'default'
    messageText.value = message
    ElMessage.info('正在重新生成回复')
    void submitQuestion()
  }

  /** 上传会话附件：先建会话再落盘，成功后刷新当前会话消息。 */
  async function handleUploadAttachment(file: File) {
    if (uploadingAttachment.value) return
    let sessionId = conversation.selectedSessionId.value
    if (!sessionId) {
      // 首次对话尚未建会话时先创建会话，附件才能挂到正确的聊天记录下。
      try {
        const { data } = await customerApi.createSession(file.name.slice(0, 40) || '新会话')
        sessionId = data.session_id
        conversation.selectedSessionId.value = sessionId
        await conversation.loadSessions(true)
      } catch {
        ElMessage.error('会话创建失败，请先发送一条消息后再上传附件')
        return
      }
    }
    uploadingAttachment.value = true
    try {
      const { data } = await customerApi.uploadAttachment(sessionId, file)
      if (data.session_id) conversation.selectedSessionId.value = data.session_id
      await pollCurrentSession()
      ElMessage.success('附件已发送')
    } catch {
      ElMessage.error('附件上传失败，请稍后重试')
    } finally {
      uploadingAttachment.value = false
    }
  }

  /** 下载当前会话中的附件。 */
  async function handleDownloadAttachment(message: ChatMessage) {
    const sessionId = conversation.selectedSessionId.value
    if (!sessionId || !message.id) return
    try {
      const response = await customerApi.downloadAttachment(sessionId, message.id)
      const attachment = message.extra_data?.attachment as { name?: string } | undefined
      const blob = response.data as Blob
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = attachment?.name || '附件'
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
    } catch {
      ElMessage.error('附件下载失败')
    }
  }

  return {
    messageText,
    composerMode,
    submitting,
    uploadingAttachment,
    activeRequestId,
    stoppingGeneration,
    composerHint,
    submitQuestion,
    cancelCurrentGeneration,
    fillAndMaybeSend,
    regenerateAnswer,
    handleUploadAttachment,
    handleDownloadAttachment,
    cancelHandoff,
    pollCurrentSession,
    stopMessagePolling,
    scheduleMessagePolling,
    handleVisibilityChange,
    resetInput
  }
}
