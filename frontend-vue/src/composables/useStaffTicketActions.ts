import { ElMessage } from 'element-plus'
import { ref, type ComputedRef, type Ref } from 'vue'

import { staffReplyApi, staffTicketApi } from '@/api/staff'
import { useAuthStore } from '@/stores/auth'
import type { StaffTicketContext, Ticket } from '@/types/api'

/**
 * 坐席工单写操作与 AI 辅助。
 * 负责领取/开始/关闭工单、读取 AI 决策依据、生成客户话术草稿与发送回复；
 * 所有请求继续走既有 staffTicketApi / staffReplyApi，不改变接口契约。
 */
export function useStaffTicketActions(options: {
  selectedTicket: ComputedRef<Ticket | null>
  selectedTicketNo: Ref<string | null>
  queueScope: Ref<'mine' | 'claimable'>
  acting: Ref<boolean>
  loadTickets: () => Promise<void>
  loadChangeRequests: () => Promise<void>
}) {
  const auth = useAuthStore()

  const closeReason = ref('问题已处理完成')
  const draftMessage = ref('')
  // 明确区分真实模型草稿与安全回退，避免座席把固定模板误认为 AI 已完成润色。
  const draftGenerationMode = ref<'llm' | 'fallback' | null>(null)
  const draftFallbackReason = ref<string | null>(null)
  const generatingDraft = ref(false)
  // 当前选中工单的 AI 决策依据，供坐席判断转人工原因与回复依据。
  const ticketAiContext = ref<StaffTicketContext | null>(null)
  const loadingTicketAiContext = ref(false)

  /** 切换工单时清空上一张工单的草稿与生成状态。 */
  function resetDraft() {
    draftMessage.value = ''
    draftGenerationMode.value = null
    draftFallbackReason.value = null
  }

  /** 读取工单关联会话中的 AI 决策依据；请求期间切工单时丢弃旧响应。 */
  async function loadTicketAiContext(ticketNo: string) {
    loadingTicketAiContext.value = true
    try {
      const { data } = await staffTicketApi.context(ticketNo)
      if (options.selectedTicketNo.value === ticketNo) ticketAiContext.value = data
    } catch {
      // 无关联会话或已过期时仅展示空态，不影响工单主操作。
      if (options.selectedTicketNo.value === ticketNo) ticketAiContext.value = null
    } finally {
      loadingTicketAiContext.value = false
    }
  }

  /** 领取工单：成功后切回“我的”队列并刷新工单与改约申请。 */
  async function claimTicket() {
    if (!options.selectedTicket.value || !auth.user) return
    options.acting.value = true
    try {
      const { data } = await staffTicketApi.assign(options.selectedTicket.value.ticketNo, options.selectedTicket.value.assignedGroup || '客服组')
      ElMessage.success(`已领取工单，当前状态：${data.status}`)
      options.queueScope.value = 'mine'
      await options.loadTickets()
      await options.loadChangeRequests()
    } finally {
      options.acting.value = false
    }
  }

  async function startTicket() {
    if (!options.selectedTicket.value || !auth.user) return
    options.acting.value = true
    try {
      const { data } = await staffTicketApi.start(options.selectedTicket.value.ticketNo)
      ElMessage.success(`已开始处理，当前状态：${data.status}`)
      await options.loadTickets()
      await options.loadChangeRequests()
    } finally {
      options.acting.value = false
    }
  }

  async function closeTicket() {
    if (!options.selectedTicket.value || !auth.user) return
    options.acting.value = true
    try {
      const { data } = await staffTicketApi.close(options.selectedTicket.value.ticketNo, closeReason.value)
      ElMessage.success(`已关闭工单，当前状态：${data.status}`)
      await options.loadTickets()
      await options.loadChangeRequests()
    } finally {
      options.acting.value = false
    }
  }

  /** 基于工单事实与最近会话生成客户话术草稿；模型不可用时后端返回安全兜底模板。 */
  async function generateDraft() {
    if (!options.selectedTicket.value || generatingDraft.value) return
    generatingDraft.value = true
    try {
      const { data } = await staffReplyApi.draft(options.selectedTicket.value.ticketNo, closeReason.value)
      draftMessage.value = data.draft_message
      draftGenerationMode.value = data.generation_mode ?? 'fallback'
      draftFallbackReason.value = data.fallback_reason ?? null
      // 模型暂不可用时后端会安全回退，明确提示坐席仍需按真实处理结果审核后发送。
      ElMessage.success(data.generation_mode === 'llm' ? '已根据工单与会话生成 AI 话术草稿' : '已生成安全话术草稿，请结合处理结果确认')
    } finally {
      generatingDraft.value = false
    }
  }

  /** 发送座席确认后的客户可见内容。 */
  async function sendReply() {
    if (!options.selectedTicket.value || !draftMessage.value.trim()) {
      ElMessage.warning('请先填写客户可见内容')
      return
    }
    await staffReplyApi.send(options.selectedTicket.value.ticketNo, draftMessage.value)
    draftMessage.value = ''
    ElMessage.success('已发送给客户')
  }

  return {
    closeReason,
    draftMessage,
    draftGenerationMode,
    draftFallbackReason,
    generatingDraft,
    ticketAiContext,
    loadingTicketAiContext,
    resetDraft,
    loadTicketAiContext,
    claimTicket,
    startTicket,
    closeTicket,
    generateDraft,
    sendReply
  }
}
