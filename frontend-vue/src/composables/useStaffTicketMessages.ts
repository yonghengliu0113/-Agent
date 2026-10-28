import { ref } from 'vue'

import { staffReplyApi } from '@/api/staff'
import type { ChatMessage } from '@/types/api'

/**
 * 工单会话消息。
 *
 * 工单页此前只能看到 AI 决策依据，没有客户对话正文，坐席无法在工单内与客户沟通。
 * 本 composable 通过 /staff/tickets/{ticketNo}/messages 拉取正文，并支持增量轮询，
 * 让工单模式与人工接管模式拥有一致的对话体验。
 */
export function useStaffTicketMessages() {
  const messages = ref<ChatMessage[]>([])
  const sessionId = ref<string | null>(null)
  const loading = ref(false)
  /** 当前消息列表对应的工单号，用于丢弃切换工单期间的过期响应 */
  const loadedTicketNo = ref<string | null>(null)

  /** 已加载到的最大消息 id，作为增量拉取游标 */
  function latestId(): number {
    return messages.value.reduce((max, item) => Math.max(max, item.id), 0)
  }

  /** 加载消息；append=true 时只取新增部分，用于轮询。 */
  async function load(ticketNo: string, append = false): Promise<boolean> {
    if (!append) loading.value = true
    try {
      const { data } = await staffReplyApi.messages(ticketNo, append ? latestId() : 0)
      // 请求期间坐席可能已切到别的工单，此时直接丢弃本次结果
      if (append && loadedTicketNo.value !== ticketNo) return false
      sessionId.value = data.session_id
      if (append) {
        const known = new Set(messages.value.map((item) => item.id))
        messages.value = [...messages.value, ...data.messages.filter((item) => !known.has(item.id))]
      } else {
        messages.value = data.messages
      }
      loadedTicketNo.value = ticketNo
      return true
    } catch {
      // 轮询失败由调度器退避，不打断坐席当前操作
      return false
    } finally {
      if (!append) loading.value = false
    }
  }

  /** 轮询入口：仅刷新当前工单的新增消息。 */
  async function refresh(ticketNo: string | null): Promise<boolean | undefined> {
    if (!ticketNo) return undefined
    if (loadedTicketNo.value !== ticketNo) return load(ticketNo)
    return load(ticketNo, true)
  }

  /** 切换工单或退出登录时清空，避免上一张工单的对话串到新工单上。 */
  function reset(): void {
    messages.value = []
    sessionId.value = null
    loadedTicketNo.value = null
  }

  return { messages, sessionId, loading, load, refresh, reset }
}
