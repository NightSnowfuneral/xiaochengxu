import { useEffect } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'

import {
  adminSessionInvalidated,
  selectAdminAuth
} from '../store/slices/adminAuthSlice'
import { useAppDispatch, useAppSelector } from '../store/hooks'

const MAX_TIMEOUT = 2_147_483_647

/** 无 Admin Token 或令牌过期时跳转登录页；后台路由统一经过此守卫。 */
export default function RequireAuth() {
  const dispatch = useAppDispatch()
  const location = useLocation()
  const { token, expiresAt } = useAppSelector(selectAdminAuth)
  const now = Date.now()
  const expired = Boolean(token && expiresAt && expiresAt <= now)

  useEffect(() => {
    if (!expiresAt) {
      return
    }
    const remaining = expiresAt - Date.now()
    if (remaining <= 0) {
      dispatch(adminSessionInvalidated('登录状态已过期，请重新登录'))
      return
    }
    if (remaining > MAX_TIMEOUT) {
      return
    }
    const timer = window.setTimeout(() => {
      dispatch(adminSessionInvalidated('登录状态已过期，请重新登录'))
    }, remaining)
    return () => window.clearTimeout(timer)
  }, [dispatch, expiresAt])

  if (!token || !expiresAt || expired) {
    return (
      <Navigate
        to="/login"
        replace
        state={{
          from: location.pathname + location.search,
          reason: expired ? '登录状态已过期，请重新登录' : undefined
        }}
      />
    )
  }

  return <Outlet />
}
