/**
 * 通用域类型：登录身份与 Agent 运行状态。
 * 这些结构被登录页、客户首页和内部监控页共用，不隶属于单一业务域。
 */

/** 当前登录用户；role 同时兼容客户与座席两种身份。 */
export interface CurrentUser {
  user_id: number
  customer_id: number
  display_name: string
  role: 'customer' | 'staff' | string
}

/** 登录接口返回的令牌与当前用户信息。 */
export interface LoginResponse {
  token: string
  token_type: string
  user: CurrentUser
}

/** Agent 服务运行状态，用于客户首页提示与内部监控展示。 */
export interface AgentStatus {
  status: string
  error?: string
  llm?: {
    enabled?: boolean
    provider?: string | null
    model?: string | null
    base_url?: string | null
    timeout?: number
  }
  queue?: {
    enabled?: boolean
    active_worker?: boolean
  }
}
