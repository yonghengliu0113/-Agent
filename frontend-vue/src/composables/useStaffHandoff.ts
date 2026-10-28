import { ElMessage } from 'element-plus'
import { computed, ref, watch, type Ref } from 'vue'

import { staffHandoffApi } from '@/api/staff'
import { useAuthStore } from '@/stores/auth'
import type { ChatMessage, StaffHandoffDetail, StaffHandoffSession } from '@/types/api'

/**
 * 人工接管会话状态与操作。
 * 负责待接入/我的会话列表、详情消息、按需展开更早历史、已读游标持久化，
 * 以及接入、回复、结束接管与创建跟进工单等写操作。
 */
export function useStaffHandoff(options: { acting: Ref<boolean> }) {
  const auth = useAuthStore()

  const handoffSessions = ref<StaffHandoffSession[]>([])
  const handoffMessages = ref<ChatMessage[]>([])
  // 座席默认只读取交接摘要与最近相关窗口，更早历史必须由座席主动展开。
  const handoffSummary = ref<StaffHandoffDetail['handoff_summary'] | null>(null)
  const handoffHistoryAvailable = ref(false)
  const handoffHistoryAccessAllowed = ref(false)
  const handoffHistoryLoading = ref(false)
  const selectedHandoffSessionId = ref<string | null>(null)
  const handoffLoading = ref(false)
  const handoffReply = ref('')
  const handoffCloseMessage = ref('人工服务已结束，后续可继续由智能助手协助。')
  const handoffScope = ref<'pending' | 'mine'>('pending')
  const latestHandoffMessageId = ref(0)

  // 已读游标按坐席持久化到 localStorage，刷新页面后未读红点不丢失。
  const seenStoreKey = computed(() => `eca_staff_seen_${auth.user?.user_id ?? 'anonymous'}`)
  function loadSeenHandoffIds(): Record<string, number> {
    try {
      return JSON.parse(localStorage.getItem(seenStoreKey.value) || '{}') as Record<string, number>
    } catch {
      return {}
    }
  }
  const seenHandoffMessageIds = ref<Record<string, number>>(loadSeenHandoffIds())

  function markHandoffSeen(sessionId: string, messageId: number) {
    if (messageId > (seenHandoffMessageIds.value[sessionId] || 0)) {
      seenHandoffMessageIds.value[sessionId] = messageId
      try {
        localStorage.setItem(seenStoreKey.value, JSON.stringify(seenHandoffMessageIds.value))
      } catch {
        /* 存储不可用时仅保留内存中的已读状态。 */
      }
    }
  }

  let handoffDetailRequestVersion = 0

  const selectedHandoff = computed(() => handoffSessions.value.find((item) => item.session_id === selectedHandoffSessionId.value) ?? null)
  const visibleHandoffs = computed(() => {
    const items = handoffSessions.value.filter((item) => handoffScope.value === 'pending' ? item.handoff_status === 'PENDING' : item.handoff_status === 'ACTIVE')
    // 待接入按排队先后(FIFO)；我的会话按最近活跃排序，最新消息在最上面。
    return [...items].sort((a, b) => handoffScope.value === 'pending'
      ? String(a.human_requested_at || '').localeCompare(String(b.human_requested_at || ''))
      : String(b.latest_message_at || '').localeCompare(String(a.latest_message_at || '')))
  })
  const canOperateHandoff = computed(() => {
    return selectedHandoff.value?.handoff_status === 'ACTIVE' && selectedHandoff.value.human_assigned_staff_id === String(auth.user?.user_id)
  })

  /** 刷新人工会话列表；keepSelection=false 时回退到列表首个会话。 */
  async function loadHandoffSessions(keepSelection = true) {
    handoffLoading.value = true
    try {
      const previousSelection = selectedHandoffSessionId.value
      const { data } = await staffHandoffApi.list()
      handoffSessions.value = data
      if (!keepSelection || !selectedHandoffSessionId.value || !data.some((item) => item.session_id === selectedHandoffSessionId.value)) {
        selectedHandoffSessionId.value = data[0]?.session_id ?? null
      }
      if (selectedHandoffSessionId.value && (previousSelection !== selectedHandoffSessionId.value || !handoffMessages.value.length)) {
        await loadHandoffDetail(selectedHandoffSessionId.value)
      } else if (!selectedHandoffSessionId.value) {
        // 只有当前会话被移出队列或不再可见时才清理历史，刷新同一会话不能覆盖本地消息。
        handoffMessages.value = []
        handoffSummary.value = null
        handoffHistoryAvailable.value = false
        handoffHistoryAccessAllowed.value = false
        latestHandoffMessageId.value = 0
      }
    } finally {
      handoffLoading.value = false
    }
  }

  // 切换待接入/我的会话时，若当前选择不在新列表内则自动选中第一条。
  watch(handoffScope, () => {
    const first = visibleHandoffs.value[0]
    if (first && !visibleHandoffs.value.some((item) => item.session_id === selectedHandoffSessionId.value)) {
      void selectHandoff(first)
    }
  })

  async function loadHandoffDetail(sessionId: string) {
    const requestVersion = ++handoffDetailRequestVersion
    const { data } = await staffHandoffApi.detail(sessionId)
    // 用户在网络请求期间切换了会话时，旧响应不能覆盖新会话的消息历史。
    if (selectedHandoffSessionId.value !== sessionId || requestVersion !== handoffDetailRequestVersion) return
    handoffMessages.value = data.messages
    handoffSummary.value = data.handoff_summary ?? null
    handoffHistoryAvailable.value = Boolean(data.history_available)
    handoffHistoryAccessAllowed.value = Boolean(data.history_access_allowed)
    latestHandoffMessageId.value = data.latest_message_id || Math.max(0, ...data.messages.map((item) => item.id))
    markHandoffSeen(sessionId, latestHandoffMessageId.value)
  }

  /**
   * 座席按需加载更早历史。该操作由后端再次校验会话归属并写入审计日志，
   * 避免默认暴露整段 AI 对话。
   */
  async function loadEarlierHandoffHistory() {
    const session = selectedHandoff.value
    const earliestMessageId = Math.min(...handoffMessages.value.map((item) => item.id))
    if (!session || !canOperateHandoff.value || !Number.isFinite(earliestMessageId) || handoffHistoryLoading.value) return

    handoffHistoryLoading.value = true
    try {
      const { data } = await staffHandoffApi.history(session.session_id, earliestMessageId)
      // 防止切换会话后旧请求把历史拼接到新会话。
      if (selectedHandoffSessionId.value !== session.session_id) return
      const known = new Set(handoffMessages.value.map((item) => item.id))
      handoffMessages.value = [...data.messages.filter((item) => !known.has(item.id)), ...handoffMessages.value]
      handoffHistoryAvailable.value = data.history_available
      ElMessage.success('已加载更早历史，本次查看已记录审计日志')
    } finally {
      handoffHistoryLoading.value = false
    }
  }

  /**
   * 轮询当前会话的增量消息；切换会话后丢弃旧响应。
   * 返回值交给轮询调度器判断是否需要指数退避：true 成功、false 失败、undefined 跳过本轮。
   */
  async function pollHandoffDetail() {
    const sessionId = selectedHandoffSessionId.value
    if (!sessionId || document.hidden) return undefined
    try {
      const { data } = await staffHandoffApi.detail(sessionId, latestHandoffMessageId.value)
      // 请求期间切换会话属于正常丢弃，不重置也不累加失败计数。
      if (selectedHandoffSessionId.value !== sessionId) return undefined
      const known = new Set(handoffMessages.value.map((item) => item.id))
      handoffMessages.value = [...handoffMessages.value, ...data.messages.filter((item) => !known.has(item.id))]
      latestHandoffMessageId.value = Math.max(latestHandoffMessageId.value, data.latest_message_id || 0)
      markHandoffSeen(sessionId, latestHandoffMessageId.value)
      return true
    } catch {
      // 轮询失败由调度器统一退避，不打断座席当前操作。
      return false
    }
  }

  /** 选择人工会话并清空上一会话的待发送回复。 */
  async function selectHandoff(session: StaffHandoffSession) {
    selectedHandoffSessionId.value = session.session_id
    handoffReply.value = ''
    await loadHandoffDetail(session.session_id)
  }

  async function acceptHandoff() {
    if (!selectedHandoff.value) return
    options.acting.value = true
    try {
      await staffHandoffApi.accept(selectedHandoff.value.session_id)
      ElMessage.success('已接入人工会话')
      await loadHandoffSessions(true)
    } finally {
      options.acting.value = false
    }
  }

  async function sendHandoffReply() {
    if (!selectedHandoff.value || !handoffReply.value.trim()) {
      ElMessage.warning('请先填写人工回复内容')
      return
    }
    options.acting.value = true
    try {
      await staffHandoffApi.reply(selectedHandoff.value.session_id, handoffReply.value)
      handoffReply.value = ''
      ElMessage.success('已发送给客户')
      await loadHandoffDetail(selectedHandoff.value.session_id)
    } finally {
      options.acting.value = false
    }
  }

  async function closeHandoff() {
    if (!selectedHandoff.value) return
    options.acting.value = true
    try {
      await staffHandoffApi.close(selectedHandoff.value.session_id, handoffCloseMessage.value)
      ElMessage.success('已结束人工接管，后续回到智能助手协助')
      await loadHandoffSessions(false)
    } finally {
      options.acting.value = false
    }
  }

  async function createHandoffTicket() {
    if (!selectedHandoff.value) return
    options.acting.value = true
    try {
      const { data } = await staffHandoffApi.createTicket(selectedHandoff.value.session_id)
      ElMessage.success(`跟进工单已就绪：${data.ticket.ticketNo}`)
    } finally {
      options.acting.value = false
    }
  }

  return {
    handoffSessions,
    handoffMessages,
    handoffSummary,
    handoffHistoryAvailable,
    handoffHistoryAccessAllowed,
    handoffHistoryLoading,
    selectedHandoffSessionId,
    handoffLoading,
    handoffReply,
    handoffCloseMessage,
    handoffScope,
    seenHandoffMessageIds,
    selectedHandoff,
    visibleHandoffs,
    canOperateHandoff,
    loadHandoffSessions,
    loadHandoffDetail,
    loadEarlierHandoffHistory,
    pollHandoffDetail,
    selectHandoff,
    acceptHandoff,
    sendHandoffReply,
    closeHandoff,
    createHandoffTicket
  }
}
