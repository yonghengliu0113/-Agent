import { staffHandoffApi } from '@/api/staff'

/**
 * 坐席工作台轮询调度。
 * 队列轮询与当前会话轮询分别退避，页面隐藏时暂停，重新可见时立即补一次；
 * 同时维护坐席在线心跳。定时器生命周期由父页面在挂载/卸载时显式启停。
 */
export function useStaffPolling(options: {
  loadHandoffSessions: (keepSelection?: boolean) => Promise<void>
  pollHandoffDetail: () => Promise<boolean | undefined>
}) {
  let queuePollTimer: number | null = null
  let detailPollTimer: number | null = null
  let heartbeatTimer: number | null = null
  let handoffPolling = false
  let queuePollFailures = 0
  let detailPollFailures = 0

  /** 队列轮询：失败后按 3s、6s、12s… 退避，最长 15s。 */
  function scheduleQueuePoll(delay = 3000) {
    if (queuePollTimer !== null) window.clearTimeout(queuePollTimer)
    queuePollTimer = window.setTimeout(async () => {
      if (!document.hidden && !handoffPolling) {
        handoffPolling = true
        try {
          await options.loadHandoffSessions(true)
          queuePollFailures = 0
        } catch {
          queuePollFailures += 1
        } finally {
          handoffPolling = false
        }
      }
      scheduleQueuePoll(Math.min(15000, 3000 * 2 ** queuePollFailures))
    }, delay)
  }

  /** 详情轮询：失败后按 2s、4s、8s… 退避，最长 15s。 */
  function scheduleDetailPoll(delay = 2000) {
    if (detailPollTimer !== null) window.clearTimeout(detailPollTimer)
    detailPollTimer = window.setTimeout(async () => {
      const succeeded = await options.pollHandoffDetail()
      if (succeeded === true) detailPollFailures = 0
      else if (succeeded === false) detailPollFailures += 1
      scheduleDetailPoll(Math.min(15000, 2000 * 2 ** detailPollFailures))
    }, delay)
  }

  /** 启动轮询与心跳；重复调用不会创建第二组定时器。 */
  function startStaffPolling() {
    if (queuePollTimer !== null) return
    scheduleQueuePoll()
    scheduleDetailPoll()
    heartbeatTimer = window.setInterval(() => {
      if (!document.hidden) void staffHandoffApi.heartbeat().catch(() => undefined)
    }, 10000)
  }

  /** 停止全部定时器；离开页面或退出登录时调用。 */
  function stopStaffPolling() {
    if (queuePollTimer !== null) window.clearInterval(queuePollTimer)
    if (detailPollTimer !== null) window.clearInterval(detailPollTimer)
    if (heartbeatTimer !== null) window.clearInterval(heartbeatTimer)
    queuePollTimer = detailPollTimer = heartbeatTimer = null
  }

  /** 页面重新可见时立即心跳并各补一次轮询，缩短座席看到新消息的延迟。 */
  function handleStaffVisibility() {
    if (!document.hidden) {
      void staffHandoffApi.heartbeat().catch(() => undefined)
      scheduleQueuePoll(0)
      scheduleDetailPoll(0)
    }
  }

  return { startStaffPolling, stopStaffPolling, handleStaffVisibility }
}
