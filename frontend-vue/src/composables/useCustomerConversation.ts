import { ElMessage } from 'element-plus'
import { computed, ref, type Ref } from 'vue'

import { customerApi } from '@/api/customer'
import { useCustomerSessionStore } from '@/stores/customerSessions'
import type { AgentReply, ChatMessage, ChatSession } from '@/types/api'

/**
 * 客户会话与消息状态。
 * 负责会话列表读取、当前会话选择、消息历史加载与新建会话；
 * 会话列表引用由父页面注入，保证侧栏与客服页复用同一份 Pinia 数据。
 */
export function useCustomerConversation(options: {
  sessions: Ref<ChatSession[]>
  selectedSessionId: Ref<string | null>
  onSessionsRefreshed: () => void
}) {
  const sessionStore = useCustomerSessionStore()

  const messages = ref<ChatMessage[]>([])
  const lastReply = ref<AgentReply | null>(null)
  const latestMessageId = ref(0)
  const loadingSessions = ref(false)
  const loadingMessages = ref(false)
  const creatingSession = ref(false)

  const selectedSession = computed(() => options.sessions.value.find((item) => item.session_id === options.selectedSessionId.value) ?? null)

  /** 刷新会话列表；keepSelection=false 时回退到最新会话。 */
  async function loadSessions(keepSelection = true) {
    loadingSessions.value = true
    try {
      const data = await sessionStore.refresh(true)
      options.onSessionsRefreshed()
      if (!keepSelection || !options.selectedSessionId.value) {
        options.selectedSessionId.value = data[0]?.session_id ?? null
      }
      if (options.selectedSessionId.value) {
        await loadMessages(options.selectedSessionId.value)
      } else {
        messages.value = []
      }
    } finally {
      loadingSessions.value = false
    }
  }

  /** 读取单个会话的消息历史，并同步最新消息游标。 */
  async function loadMessages(sessionId: string) {
    loadingMessages.value = true
    try {
      const { data } = await customerApi.sessionDetail(sessionId)
      messages.value = data.messages
      latestMessageId.value = data.latest_message_id || Math.max(0, ...data.messages.map((item) => item.id))
      if (data.session) sessionStore.prepend(data.session)
    } finally {
      loadingMessages.value = false
    }
  }

  /** 切换当前会话；重复选择同一会话时不重复请求。 */
  async function selectSession(sessionId: string) {
    if (options.selectedSessionId.value === sessionId) {
      return
    }
    options.selectedSessionId.value = sessionId
    lastReply.value = null
    await loadMessages(sessionId)
  }

  /** 新建咨询会话；创建期间只允许一个请求进入，避免重复建会话。 */
  async function createNewSession() {
    if (creatingSession.value) return null
    creatingSession.value = true
    try {
      const { data } = await customerApi.createSession()
      options.selectedSessionId.value = data.session_id
      sessionStore.prepend(data)
      messages.value = []
      lastReply.value = null
      ElMessage.success('已新建咨询')
      return data
    } finally {
      creatingSession.value = false
    }
  }

  /** 侧栏删除当前会话后主动回退到最新可用会话，避免继续请求已软删除的数据。 */
  async function handleSessionsChanged(payload: { sessionId: string; deleted: boolean }) {
    if (payload.deleted && options.selectedSessionId.value === payload.sessionId) {
      options.selectedSessionId.value = null
      messages.value = []
      lastReply.value = null
      await loadSessions(false)
      return
    }
    await loadSessions(true)
  }

  return {
    sessions: options.sessions,
    selectedSessionId: options.selectedSessionId,
    selectedSession,
    messages,
    lastReply,
    latestMessageId,
    loadingSessions,
    loadingMessages,
    creatingSession,
    loadSessions,
    loadMessages,
    selectSession,
    createNewSession,
    handleSessionsChanged
  }
}
