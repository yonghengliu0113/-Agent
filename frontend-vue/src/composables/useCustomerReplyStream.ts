import { ElMessage } from 'element-plus'
import type { Ref } from 'vue'

import { customerApi } from '@/api/customer'
import type { AgentReply } from '@/types/api'

/**
 * 单次 AI 回复的流式请求编排。
 * 负责 SSE 事件解析、断线续传、终态判定与结果查询兜底；
 * 不负责会话列表刷新、输入框状态或工单合并，这些由调用方处理。
 */
export function useCustomerReplyStream(options: {
  lastReply: Ref<AgentReply | null>
  activeRequestId: Ref<string>
  getSessionId: () => string | null
  getSignal: () => AbortSignal | undefined
}) {
  /**
   * 发起一次可续传的 Agent 回复请求。
   * 返回 isFinal=true 表示后端已持久化最终结果；pending=true 表示两分钟内仍未结束，
   * 调用方应保留临时消息与 request_id 状态，不能回刷成提问前的旧会话。
   */
  async function requestAgentReply(payload: Record<string, unknown>, idempotencyKey: string) {
    let streamedAnswer = ''
    let finalReply: AgentReply | null = null
    let requestId = ''
    let lastEventId = ''
    let terminalType = ''
    const reconnectDeadline = Date.now() + 120_000

    const handleStreamEvent = (event: { request_id?: string; event_type: string; payload: Record<string, unknown>; event_id: string }) => {
      requestId = event.request_id || requestId
      options.activeRequestId.value = requestId
      const stageMessages: Record<string, string> = {
        accepted: '已收到问题，正在准备处理…',
        queued: '请求已进入处理队列…',
        retrieving: '正在检索相关知识…',
        tool_calling: '正在查询相关业务信息…',
        generating: '已找到相关信息，正在组织回答…'
      }
      if (stageMessages[event.event_type] && !streamedAnswer) {
        const stageMessage = stageMessages[event.event_type]
        options.lastReply.value = {
          session_id: options.getSessionId() || 'pending',
          answer: stageMessage,
          customer_message: stageMessage,
          service_status: stageMessage,
          auto_send: false,
          need_human: false
        }
      }
      if (event.event_type === 'delta') {
        streamedAnswer += String(event.payload.text || '')
        options.lastReply.value = {
          session_id: options.getSessionId() || 'pending',
          answer: streamedAnswer,
          customer_message: streamedAnswer,
          auto_send: true,
          need_human: false
        }
      }
      if (event.event_type === 'completed' || event.event_type === 'degraded' || event.event_type === 'cancelled' || event.event_type === 'error') {
        const answer = String(event.payload.answer || event.payload.customer_message || streamedAnswer || '当前服务繁忙，请稍后查询处理进度。')
        options.lastReply.value = {
          session_id: options.getSessionId() || 'pending',
          answer,
          customer_message: answer,
          service_status: String(event.payload.service_status || ''),
          auto_send: event.event_type === 'completed' && !Boolean(event.payload.degraded),
          need_human: event.event_type !== 'completed' || Boolean(event.payload.degraded)
        }
      }
    }

    // 后端单次 SSE 订阅有时限；连接正常结束但任务未完成时自动续传，并用状态查询兜底。
    while (!terminalType && Date.now() < reconnectDeadline) {
      try {
        const streamResult = await customerApi.streamReply(payload, handleStreamEvent, {
          idempotencyKey,
          lastEventId: lastEventId || undefined,
          signal: options.getSignal()
        })
        requestId = streamResult.requestId || requestId
        lastEventId = streamResult.lastEventId || lastEventId
        terminalType = streamResult.terminalType || terminalType
      } catch (error) {
        // 尚未获得 request_id 时无法安全续传，保留原异常交给外层恢复输入框。
        if (!requestId) throw error
      }

      if (requestId) {
        try {
          const { data: state } = await customerApi.replyResult(requestId)
          if (['SUCCESS', 'DEGRADED', 'FAILED', 'DEAD_LETTER', 'CANCELLED'].includes(state.status)) {
            finalReply = state.result || null
            terminalType = state.status === 'SUCCESS' ? 'completed' : (state.status === 'CANCELLED' ? 'cancelled' : 'degraded')
            if (finalReply) {
              options.lastReply.value = finalReply
            }
            break
          }
        } catch {
          // 临时网络错误不应删除用户问题；下一轮仍用同一 request_id 和事件游标恢复。
        }
      }
      if (!terminalType) {
        options.lastReply.value = {
          session_id: options.getSessionId() || 'pending',
          answer: streamedAnswer || '请求仍在后台处理中，正在继续等待结果…',
          customer_message: streamedAnswer || '请求仍在后台处理中，正在继续等待结果…',
          service_status: '后台处理中',
          auto_send: false,
          need_human: false
        }
        await new Promise((resolve) => window.setTimeout(resolve, 500))
      }
    }

    if (!terminalType) {
      ElMessage.info('请求仍在后台处理中，可稍后刷新会话查看结果')
      return { data: null, isFinal: false, pending: true }
    }

    // 终态事件可能先于查询响应到达，统一再读取一次持久化结果。
    if (requestId && !finalReply) {
      try {
        const { data: state } = await customerApi.replyResult(requestId)
        finalReply = state.result || null
      } catch {
        // SSE 已提供客户可见终态时，即使结果查询临时失败也保留该回复。
      }
    }
    const data = finalReply || options.lastReply.value
    if (!data) throw new Error('未收到客服回复')
    return { data, isFinal: Boolean(finalReply), pending: false }
  }

  return { requestAgentReply }
}
