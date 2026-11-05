import type { AdminProfile } from '../types'

/**
 * Admin 会话独立存储在 localStorage 中，键名与 C 端小程序完全无关。
 * Admin JWT 与 C 端用户 JWT 使用不同密钥，二者不可互换。
 */
export const ADMIN_SESSION_STORAGE_KEY = 'spark.admin.session.v1'
export const ADMIN_SESSION_EXPIRED_EVENT = 'spark:admin-session-expired'

export interface AdminSession {
  token: string
  admin: AdminProfile
  expiresAt: number
}

function isValidSession(value: unknown): value is AdminSession {
  if (!value || typeof value !== 'object') {
    return false
  }
  const candidate = value as Partial<AdminSession>
  const admin = candidate.admin as Partial<AdminProfile> | undefined
  return (
    typeof candidate.token === 'string' &&
    candidate.token.length > 0 &&
    typeof candidate.expiresAt === 'number' &&
    Number.isFinite(candidate.expiresAt) &&
    Boolean(admin) &&
    typeof admin?.id === 'number' &&
    typeof admin?.username === 'string' &&
    (admin?.role === undefined ||
      admin?.role === 'super' ||
      admin?.role === 'normal')
  )
}

/** 读取本地会话；过期或损坏的数据会被立即清除。 */
export function readAdminSession(): AdminSession | null {
  if (typeof window === 'undefined') {
    return null
  }
  try {
    const raw = window.localStorage.getItem(ADMIN_SESSION_STORAGE_KEY)
    if (!raw) {
      return null
    }
    const parsed: unknown = JSON.parse(raw)
    if (!isValidSession(parsed) || parsed.expiresAt <= Date.now()) {
      window.localStorage.removeItem(ADMIN_SESSION_STORAGE_KEY)
      return null
    }
    // 旧版本会话没有 role：按普通管理员（只读）处理，重新登录后升级。
    return {
      ...parsed,
      admin: {
        ...parsed.admin,
        role: parsed.admin.role === 'super' ? 'super' : 'normal'
      }
    }
  } catch {
    window.localStorage.removeItem(ADMIN_SESSION_STORAGE_KEY)
    return null
  }
}

export function writeAdminSession(session: AdminSession): void {
  if (typeof window === 'undefined') {
    return
  }
  try {
    window.localStorage.setItem(
      ADMIN_SESSION_STORAGE_KEY,
      JSON.stringify(session)
    )
  } catch {
    // 浏览器禁用存储时不阻断当前页面登录，但刷新后需要重新登录。
  }
}

export function clearAdminSession(): void {
  if (typeof window === 'undefined') {
    return
  }
  try {
    window.localStorage.removeItem(ADMIN_SESSION_STORAGE_KEY)
  } catch {
    // ignore
  }
}

export function getAdminToken(): string | null {
  return readAdminSession()?.token ?? null
}

/**
 * 401、Token 过期或跨标签页退出时调用：清空本地会话并广播事件。
 * 请求层不直接依赖 Redux；监听器负责同步 store 与跳转登录页。
 */
export function notifyAdminSessionExpired(
  message = '登录状态已过期，请重新登录'
): void {
  clearAdminSession()
  if (typeof window !== 'undefined') {
    window.dispatchEvent(
      new CustomEvent<string>(ADMIN_SESSION_EXPIRED_EVENT, { detail: message })
    )
  }
}
