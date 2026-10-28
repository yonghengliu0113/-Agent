import { defineStore } from 'pinia'

import { authApi } from '@/api/auth'
import { useCustomerSessionStore } from '@/stores/customerSessions'
import type { CurrentUser } from '@/types/api'

type Role = 'customer' | 'staff'

// 货主沿用原 key 保证兼容；客服使用独立 key，避免两个端在同一浏览器互相覆盖登录态。
const TOKEN_KEYS: Record<Role, string> = { customer: 'eca_token', staff: 'eca_staff_token' }
const USER_KEYS: Record<Role, string> = { customer: 'eca_user', staff: 'eca_staff_user' }
const SESSION_TOKEN_KEYS: Record<Role, string> = { customer: 'eca_session_token', staff: 'eca_staff_session_token' }
const SESSION_USER_KEYS: Record<Role, string> = { customer: 'eca_session_user', staff: 'eca_staff_session_user' }

/** 根据当前 URL 判断本标签页属于哪个端：客服路由均在 /staff 下，其余视为货主端。 */
function roleFromPath(): Role {
  return typeof window !== 'undefined' && window.location.pathname.startsWith('/staff') ? 'staff' : 'customer'
}

/** 把服务端角色归一化，未知角色按货主处理。 */
function normalizeRole(role: unknown): Role {
  return role === 'staff' ? 'staff' : 'customer'
}

function roleKeys(role: Role) {
  return [TOKEN_KEYS[role], USER_KEYS[role], SESSION_TOKEN_KEYS[role], SESSION_USER_KEYS[role]]
}

function readStoredUser(role: Role): CurrentUser | null {
  const raw = localStorage.getItem(USER_KEYS[role]) || sessionStorage.getItem(SESSION_USER_KEYS[role])
  if (!raw) {
    return null
  }
  try {
    return JSON.parse(raw) as CurrentUser
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', {
  state: () => {
    // 页面加载时按 URL 恢复对应端的登录态，客服页不会读到货主的 Token，反之亦然。
    const role = roleFromPath()
    return {
      token: localStorage.getItem(TOKEN_KEYS[role]) || sessionStorage.getItem(SESSION_TOKEN_KEYS[role]),
      user: readStoredUser(role)
    }
  },
  actions: {
    async login(username: string, password: string, remember = true) {
      const { data } = await authApi.login(username, password)
      useCustomerSessionStore().clear()
      this.token = data.token
      this.user = data.user
      const role = normalizeRole(data.user.role)
      // “记住我”使用持久化存储；未勾选时仅保存到当前浏览器会话，关闭标签页后自动失效。
      const storage = remember ? localStorage : sessionStorage
      const tokenKey = remember ? TOKEN_KEYS[role] : SESSION_TOKEN_KEYS[role]
      const userKey = remember ? USER_KEYS[role] : SESSION_USER_KEYS[role]
      // 只清理本角色自己的历史登录态，不影响另一角色在其他标签页的会话。
      for (const key of roleKeys(role)) {
        localStorage.removeItem(key)
        sessionStorage.removeItem(key)
      }
      storage.setItem(tokenKey, data.token)
      storage.setItem(userKey, JSON.stringify(data.user))
      return data.user
    },
    logout() {
      useCustomerSessionStore().clear()
      // 优先按当前身份判断角色；身份缺失时(如 401 强制登出)按所在页面路径判断。
      const role = this.user ? normalizeRole(this.user.role) : roleFromPath()
      this.token = null
      this.user = null
      for (const key of roleKeys(role)) {
        localStorage.removeItem(key)
        sessionStorage.removeItem(key)
      }
    },
    async refreshCurrentUser() {
      const { data } = await authApi.currentUser()
      this.user = data
      const role = normalizeRole(this.user?.role)
      const storage = localStorage.getItem(TOKEN_KEYS[role]) ? localStorage : sessionStorage
      storage.setItem(storage === localStorage ? USER_KEYS[role] : SESSION_USER_KEYS[role], JSON.stringify(data))
      return data
    }
  }
})
