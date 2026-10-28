import { computed, ref } from 'vue'

import { staffTicketApi } from '@/api/staff'
import { useAuthStore } from '@/stores/auth'
import type { Ticket } from '@/types/api'

/**
 * 坐席工单队列状态。
 * 只负责工单列表拉取、队列范围/状态筛选与当前选中工单计算；
 * 领取、开始、关闭等写操作由 useStaffTicketActions 负责。
 */
export function useStaffTicketQueue() {
  const auth = useAuthStore()

  const tickets = ref<Ticket[]>([])
  const selectedTicketNo = ref<string | null>(null)
  const queueScope = ref<'mine' | 'claimable'>('mine')
  const selectedStatuses = ref(['PENDING_ASSIGN', 'PENDING_PROCESS', 'PROCESSING', 'REOPENED'])
  const loading = ref(false)

  const statusOptions = ['PENDING_ASSIGN', 'PENDING_PROCESS', 'PROCESSING', 'REOPENED', 'CLOSED']

  const selectedTicket = computed(() => tickets.value.find((item) => item.ticketNo === selectedTicketNo.value) ?? null)
  const visibleTickets = computed(() => {
    if (queueScope.value === 'claimable') {
      return tickets.value.filter((ticket) => !ticket.handlerId || ticket.status === 'PENDING_ASSIGN')
    }
    return tickets.value.filter((ticket) => ticket.handlerId === auth.user?.user_id)
  })
  const canClaim = computed(() => {
    return Boolean(selectedTicket.value && !selectedTicket.value.handlerId && selectedTicket.value.status === 'PENDING_ASSIGN')
  })
  const canOperate = computed(() => selectedTicket.value?.handlerId === auth.user?.user_id)

  /** 按当前状态筛选拉取工单；选中工单被过滤掉时回退到队列首个工单。 */
  async function loadTickets() {
    loading.value = true
    try {
      const { data } = await staffTicketApi.list(selectedStatuses.value.join(','))
      tickets.value = data
      if (!selectedTicketNo.value || !data.some((item) => item.ticketNo === selectedTicketNo.value)) {
        selectedTicketNo.value = visibleTickets.value[0]?.ticketNo ?? null
      }
    } finally {
      loading.value = false
    }
  }

  return {
    tickets,
    selectedTicketNo,
    queueScope,
    selectedStatuses,
    statusOptions,
    loading,
    selectedTicket,
    visibleTickets,
    canClaim,
    canOperate,
    loadTickets
  }
}
