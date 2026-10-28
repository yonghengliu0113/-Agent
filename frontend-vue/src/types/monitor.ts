import type { AgentStatus } from './common'

/**
 * 内部监控域类型：系统监控快照与缓存指标。
 * 仅在 /staff/system-monitor 内部页面使用，不对客户侧暴露。
 */

/** 单个缓存通道的命中指标。 */
export interface SystemMonitorCacheMetric {
  hit: number
  miss: number
  error: number
  hit_rate: number | null
}

/** 系统监控快照：队列、Worker、LLM 熔断与降级汇总。 */
export interface SystemMonitorSnapshot {
  agent_status: {
    status: string
    llm?: AgentStatus['llm']
  }
  queue: {
    available: boolean
    enabled: boolean
    stream_depth: number | null
    pending: number | null
    running: number | null
    retrying: number | null
    error?: string | null
  }
  worker: {
    active: boolean
  }
  dlq: {
    count: number | null
  }
  llm: {
    timeout: number | null
    rate_limit_429: number | null
    circuit_open: number | null
  }
  cache: Record<string, SystemMonitorCacheMetric>
  degraded: {
    total: number | null
    by_reason: Record<string, number>
  }
  updated_at: string
}
